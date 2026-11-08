"""Model selection and isolated CLI execution for factory roles.

The runner supplies command, progress and cleanup adapters. This module owns
provider routing, credentials, CLI policy and budget integration; it never imports
or inspects the factory runner. Durable run checkpointing stays with the caller.
"""
from dataclasses import asdict, dataclass
import copy
import threading
import uuid
from functools import lru_cache
from contextlib import contextmanager
from typing import Callable
import json
import os
import pathlib
import pwd
import re
import shutil
import subprocess
import sys
import tempfile
import time
from budget import BudgetError, run_budgeted, case_spending, require_case_budget, invocation_role
import model_router
from token_prices import FREE_ROUTES, GATED_OPENROUTER
import model_call_gate
from model_router import family
from registry import atomic_json

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
OPENCODE_BIN = os.environ.get("FACTORY_OPENCODE_BIN", "opencode")
CODEX_VERSION, CLAUDE_VERSION = "0.162.1", "2.1.299"
CLAUDE_PREFIX = pathlib.Path(tempfile.gettempdir()) / "factory-claude-cli"
CODEX_OFF = ["multi_agent", "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
             "in_app_browser", "computer_use", "image_generation"]
INTERRUPTED_LOCK = threading.Lock()


def accounting_work(c):
    """Comparison keeps scientific scratch separate from the owning ledger receipts."""
    return getattr(c, 'accounting_work', c.work)


def invocation_maximum(c, lease):
    from decimal import Decimal, ROUND_CEILING
    if not model_router.valid_lease(lease, getattr(lease, 'route', None),
            getattr(c, 'router_accounts', model_router.ACCOUNTS)):
        raise BudgetError('route_maximum_unknown')
    return Decimal(str(lease.max_usd)).quantize(Decimal('.000000001'), rounding=ROUND_CEILING)


def codex_usage_feed(home, user=None):
    """Read a Codex call's own session logs (CODEX_HOME/sessions/**/rollout-*.jsonl): their token_count
    events are its per-request usage. A walled user's home is private, so that user reads them."""
    script = ('[ -d "$1/sessions" ] || exit 0; '
              'find "$1/sessions" -type f -name "rollout-*.jsonl" -print0 | sort -z | xargs -0 -r cat -- '
              '| grep -F \'"token_count"\'; [ $? -le 1 ]')   # only the usage lines: the log also holds every item
    cmd = ['sh', '-c', script, 'sh', str(home)]
    if user: cmd = ['sudo', '-n', '-H', '-u', user] + cmd
    def feed():
        try: result = subprocess.run(cmd, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired): return None
        return result.stdout.decode(errors='replace') if result.returncode == 0 else None
    return feed


def role_timeout(c, name, timeout):
    """The stress-review cap applies to stress review, not to the attacker's freshness search."""
    if invocation_role(name) == 'stress_tester' and not name.endswith('-freshness'):
        return min(timeout or c.args.agent_timeout, attacker_timeout(c))
    return timeout


def attacker_timeout(c):
    # Stress review reads the case's files. Keep a twenty-minute exploration
    # base, add a minute per input file, bounded by forty minutes/operator cap.
    files = sum(p.is_file() for p in c.case.rglob('*'))
    return min(c.args.agent_timeout, 2400, 1200 + 60 * files)


def _read_json(path, default=None):
    try: return json.loads(pathlib.Path(path).read_text())
    except (OSError, ValueError): return default


@lru_cache(maxsize=None)
def _opencode_flags(binary):
    # CLI discovery belongs to execution, not importing the factory or its tests.
    if shutil.which(binary) and "--standalone" in subprocess.run(
            [binary, "run", "--help"], capture_output=True, text=True).stdout:
        return ("--standalone",)
    return ()


def select_models(c, *, log):
    """Pin role families/effort; the shared router selects effective provider/account."""
    a = c.args
    roles = rotation(a.rotation_slot or 1, getattr(a, 'rotation_table', None))
    flags = {'writer': 'builder', 'stress_tester': 'attacker', 'reviewer': 'reviewer1', 'strong_calibrator': 'strong_calibrator'}
    for role, flag in flags.items():
        if getattr(a, flag): roles[role] = {'model': getattr(a, flag), 'effort': getattr(a, flag + '_effort') or model_effort(getattr(a, flag))}
        elif getattr(a, flag + '_effort'): roles[role]['effort'] = getattr(a, flag + '_effort')
    roles['easy_calibrator'] = {'model': a.easy_calibrator, 'effort': a.easy_calibrator_effort or model_effort(a.easy_calibrator)}
    if a.reviewer2: roles['reviewer2'] = {'model': a.reviewer2, 'effort': a.reviewer2_effort or model_effort(a.reviewer2)}
    if getattr(c, "engine", None) is None:
        from free_models import apply as apply_free_models
        roles = apply_free_models(c, roles)
    families = [family(roles[r]['model']) for r in flags]
    if len(set(families)) != 4: raise ValueError('Writer, stress-tester, strong calibrator and reviewer must be four different families')
    if a.reviewer2 and family(a.reviewer2) in (family(roles['writer']['model']), family(roles['stress_tester']['model'])):
        raise ValueError('Every reviewer must be independent from the writer and stress tester')
    if not roles['strong_calibrator']['model'].startswith(('claude/', 'codex/')):
        raise ValueError('Strong calibrator must use the Claude or Codex subscription')
    if family(roles['easy_calibrator']['model']) in ('anthropic', 'openai'):
        raise ValueError('Easy calibrator must not be a contestant family')
    for data in roles.values(): data['family'] = family(data['model'])
    c.card['roles'], c.card['rotation_slot'] = roles, a.rotation_slot
    m = {"builder": [roles['writer']['model']], "attacker": [roles['stress_tester']['model']],
         "reviewers": [[roles['reviewer']['model']]] + ([[a.reviewer2]] if a.reviewer2 else []),
         "strong_calibrator": [roles['strong_calibrator']['model']], "easy_calibrator": [a.easy_calibrator]}
    if any(len(chain) != 1 or ',' in chain[0] for chain in [m['builder'], m['attacker'], *m['reviewers'], m['strong_calibrator'], m['easy_calibrator']]):
        raise ValueError("Select one requested model per role; the router owns approved fallbacks")
    log(c, "models", json.dumps(m))
    return m


def model_effort(model):
    return 'high' if model.startswith(('claude/', 'codex/')) else 'xhigh' if family(model) == 'meta' else 'default'


def require_bounded_models(c):
    """Reject a guaranteed later-route failure before authoring spends anything."""
    models = c.models
    roles = [('writer', models['builder']), ('stress_tester', models['attacker']),
             ('strong_calibrator', models['strong_calibrator']), ('easy_calibrator', models['easy_calibrator'])]
    roles += [('reviewer' if i == 0 else 'reviewer2', chain) for i, chain in enumerate(models['reviewers'])]
    for role, chain in roles:
        # A walled role is never leased a free route (ModelRuntime._call).
        if not any(model_router.route_maximum(row['route']) is not None
                   and not (role in model_router.WALLED_ROLES and row['route'] in FREE_ROUTES)
                   for row in model_router.routes(chain[0], getattr(c, 'router_accounts', model_router.ACCOUNTS))):
            raise model_router.ProviderWait(role, model_router.Wait('unbounded_route',
                model_router.retry_at('unbounded_route'), route=chain[0]))


def rotation(slot, table_name=None):
    # Default rotation-3writers.json: GPT only calibrates and reviews while OpenAI's filter refuses case
    # writing (2026-10-16). rotation.json (4 writer families) once Daybreak access is granted.
    table = _read_json(PROMPTS.parent / (table_name or os.environ.get('FACTORY_ROTATION', 'rotation-3writers.json')))
    if not isinstance(slot, int) or not 1 <= slot <= len(table['slots']): raise ValueError('rotation slot must be 1..8')
    row = table['slots'][slot - 1]
    if len(set(row.values())) != 4 or row['strong_calibrator'] not in ('anthropic', 'openai') or row['strong_calibrator'] == row['writer']:
        raise ValueError('invalid family rotation')
    for fam, roles in (table.get('refused') or {}).items():
        if any(row.get(r) == fam for r in roles): raise ValueError(f'{fam} is refused as {"/".join(roles)}: {table.get("refused_why", "")}')
    return {role: dict(table['families'][fam]) for role, fam in row.items()}


def opencode_config(model=None, case=None, *, diagnosis=False):
    """Merged over the user config: provider keys come from the environment (factory/launch.sh loads
    them from ~/.secrets; boat's paid relay is off since 2026-10-16), and boat's desktop `computer`
    MCP off (about 28k prompt tokens a call, unneeded). In /tmp so the pilot user can read it; no secret."""
    path = pathlib.Path(tempfile.gettempdir()) / ("factory-" + model.replace("/", "-").replace(":", "-") + ".json" if model else "factory-opencode.json")
    base = None if diagnosis else os.environ.get("OPENCODE_API_KEY_BASE_URL")
    from token_prices import runtime_prices as price
    cfg = {"mcp": {"computer": {"enabled": False}},
           "compaction": {"auto": True}, "permission": {"task": "deny"},  # on since 2026-10-17: off, MiMo re-read ~500k tokens a step
           "provider": {"openrouter": {"models": {
               "deepseek/deepseek-v4.1-flash": {"cost": price('openrouter/deepseek/deepseek-v4.1-flash')},
               "meta/muse-spark-1.3-contributor": {
               "cost": price('openrouter/meta/muse-spark-1.3-contributor')}}}}}
    if model: cfg["small_model"] = model  # Compaction shares the admitted model/family/account.
    if diagnosis: cfg['permission'].update(webfetch='deny', websearch='deny')
    # OpenCode v1.19 does not know Muse Contributor's price; without one the budget guard stops the run.
    go = {"models": {"muse-spark-1.3-contributor": {"cost": price('opencode-go/muse-spark-1.3-contributor')}}}
    go["options"] = {"apiKey": "{env:OPENCODE_API_KEY}"}
    if base: go["options"]["baseURL"] = base.rstrip("/") + "/go/v1"
    cfg["provider"]["opencode-go"] = go
    # Founder 2026-10-19: OpenCode v1.x answers Muse with "Invalid credential" unless the opencode provider points at Zen.
    cfg["provider"]["opencode"] = {"options": {"baseURL": "https://opencode.ai/zen/v1"}}
    if model in ("opencode/minimax-m3.1-flash-free", "opencode/deepseek-v4.1-flash-free"):
        from free_models import provider_config
        cfg["provider"]["opencode"] = provider_config(case, model)
        cfg["small_model"] = model
        path = path.with_name("factory-opencode-" + model.split("/", 1)[1] + ".json")
    elif model and model.startswith(("openrouter/", "opencode-go/")):
        cfg["small_model"] = model  # compaction follows the same approved provider/model
        path = path.with_name("factory-" + model.replace("/", "-").replace(":", "-") + ".json")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:
        json.dump(cfg, staged)
    os.chmod(staged.name, 0o644); os.replace(staged.name, path)
    return path


def diagnosis_environment(env, driver, lease, home):
    """Only the selected transport account crosses the diagnosis UID boundary."""
    clean = {key: env[key] for key in ('PATH', 'LANG', 'LC_ALL') if key in env}
    clean.update(HOME=str(home), TMPDIR=str(home / '.cache'))
    key = ('CLAUDE_CODE_OAUTH_TOKEN' if driver == 'claude' else
           'OPENROUTER_API_KEY' if lease.account == 'openrouter-key' else
           'OPENCODE_API_KEY' if driver == 'opencode' and lease.account else None)
    if key and key in env: clean[key] = env[key]
    return clean


@contextmanager
def diagnosis_loopback(c, command, gate, enabled):
    """Permit exactly A's ephemeral listener, before the pilot LOCAL rejection."""
    rules = []
    try:
        if enabled:
            port = str(gate.server.server_port)
            for rule in (["-d", "127.0.0.1", "-p", "tcp", "--dport", port, "-j", "ACCEPT"],
                         ["-p", "tcp", "-m", "conntrack", "--ctdir", "ORIGINAL",
                          "--ctorigdst", "127.0.0.1", "--ctorigdstport", port, "-j", "ACCEPT"]):
                command(c, ['sudo', 'iptables', '-w', '5', '-I', 'factory-pilot', '1', *rule], check=True)
                rules.append(rule)
        yield
    finally:
        for rule in reversed(rules):
            command(c, ['sudo', 'iptables', '-w', '5', '-D', 'factory-pilot', *rule], check=True)


def pinned_cli(kind):
    """Path of the pinned codex/claude CLI; any other version stops the run (unmetered schemas)."""
    if kind == "codex":
        path, want = os.environ.get("FACTORY_CODEX_BIN", "codex"), CODEX_VERSION
    else:
        path, want = os.environ.get("FACTORY_CLAUDE_BIN", str(CLAUDE_PREFIX / "bin/claude")), CLAUDE_VERSION
        if not shutil.which(path):
            subprocess.run(["npm", "install", "-g", "--prefix", str(CLAUDE_PREFIX), f"@anthropic-ai/claude-code@{want}"],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=600)
    version = lambda p: subprocess.run([p, "--version"], capture_output=True, text=True).stdout.split() if shutil.which(p) else []
    found = version(path)
    npm_pin = "/usr/local/lib/node_modules/@openai/codex/bin/codex.js"  # boat re-links /usr/local/bin/codex to its newer build mid-run
    if kind == "codex" and want not in found and want in version(npm_pin): path, found = npm_pin, [want]
    if want not in found: raise BudgetError(f"{kind}_cli_not_{want}")
    return path


def diagnostic_env(c, name, role, env):
    """Bound prescribed author strategy diagnostics, never trusted gate execution."""
    env = {k: v for k, v in env.items() if not k.startswith('FACTORY_STRATEGY_')}
    if role in ('writer', 'stress_tester'):
        if not re.fullmatch(r'[A-Za-z0-9_-]+', name):
            raise ValueError('invalid diagnostic invocation name')
        env.update(FACTORY_STRATEGY_DIAGNOSTIC=str(c.work / 'diagnostic-budgets' / name),
                   FACTORY_STRATEGY_SECONDS='300',
                   FACTORY_STRATEGY_WORKERS=str(max(1, getattr(c.args, 'bench_workers', 1))))
    return env


def update_case_budget(c):
    ledger = _read_json(c.ledger, {}) if hasattr(c, 'ledger') else {}
    prior = c.card.get('case_budget', {})
    summary = {**{k: v for k, v in prior.items() if k == 'unpriced_model'},
               'limit_usd': getattr(c.args, 'case_budget', 50.0),
               **case_spending(ledger, c.card.get('models_used'))}
    c.card['case_budget'] = summary
    return ledger, summary


def case_budget_boundary(c, model=None):
    ledger, summary = update_case_budget(c)
    if getattr(c, 'engine', None) is not None:
        return
    try:
        require_case_budget(ledger, summary['limit_usd'], model)
    except BudgetError:
        if model and model.startswith('codex/'):
            from token_prices import CODEX_PRICES
            if model not in CODEX_PRICES: c.card['case_budget']['unpriced_model'] = model
        raise


def writer_round_estimate(c):
    ledger, _ = update_case_budget(c)
    rounds = {}
    for event in ledger.get('events', []):
        cost = sum(event.get(k, 0) for k in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd'))
        match = re.fullmatch(r'(?:builder|attacker)-(\d+)', event.get('invocation') or '')
        if match:
            n = match[1]
            rounds[n] = rounds.get(n, 0) + cost
    # An evidenced killed writer has an explicit historical invocation floor.
    # Reserve that floor for its replacement too, without charging the waste
    # to a case or guessing round attribution for all legacy events.
    interrupted = [record['derivation']['maximum_observed_writer_list_cost_usd']
                   for record in ledger.get('infrastructure_waste', [])
                   if record.get('kind') == 'infrastructure_kill']
    return round(max([8.0, *rounds.values(), *interrupted]), 2)


def free_usage_settled(lease):
    """A failed free call's usage needs no settling before the next route: it is bounded at $0 and
    checked only against OpenCode's report (founder 2026-11-08). Its receipt keeps the evidence."""
    return lease.route in FREE_ROUTES and lease.max_usd == 0


def call_failure_reason(label, route):
    """A per-call failure that moves this call to its chain's next route, or None (the step fails).
    A free route's broken usage report or provider mismatch also moves on: the next route is gated."""
    if label.startswith('provider_limit'): return 'quota'
    if label in ('codex_login_expired', 'credential_expiring'): return 'credential_expiring'
    if label in ('opencode_error', 'claude_error', 'codex_error', 'process_error') or label.startswith('refusal:'): return 'outage'
    if route in FREE_ROUTES and label in ('missing_usage', 'invalid_usage', 'free_route_mismatch'): return 'outage'
    return None


@dataclass(frozen=True)
class ModelRuntime:
    """Execute one routed role call with caller-owned operational adapters."""
    home: pathlib.Path
    command: Callable
    progress: Callable
    cleanup: Callable
    pilot_home: Callable

    def call(self, c, models, text, cwd, name, user=None, timeout=None, deadline=None, before_attempt=None, lease=None, on_complete=None):
        def invoke():
            result = self._call(c, models, text, cwd, name, user=user, timeout=timeout,
                                deadline=deadline, before_attempt=before_attempt, lease=lease)
            # Persist the caller's completed-answer marker before publishing a snapshot.
            if on_complete is not None: on_complete()
            return result
        if getattr(c, 'engine', None) is not None and callable(getattr(c, 'engine_checkpoint', None)):
            from durable.checkpoints import model_call
            return model_call(c, models, cwd, name, invoke, text=text)
        return invoke()

    def _remove_state(self, c, scratch, *, memory=False, user=None, allow_absent=False):
        if memory:
            # Cleanup must survive the model's cancellation and expired deadline.
            import processes
            cleanup = copy.copy(c)
            cleanup.role_cancel = None
            with processes.deadline(30, independent=True):
                self.command(cleanup, ['sudo', 'umount', '--', str(scratch)], check=not allow_absent)
                shutil.rmtree(scratch)
        else:
            self.cleanup(scratch, sudo=bool(user))

    def _call(self, c, models, text, cwd, name, user=None, timeout=None, deadline=None, before_attempt=None, lease=None):
        """One family, shared admission, preserved accounting across provider attempts."""
        try:
            if len(models) != 1: raise ValueError('Select one requested model per role')
            requested, role = models[0], invocation_role(name)
            if hasattr(c, 'args'): case_budget_boundary(c, requested)
            pinned = c.card.get('roles', {}).get(role, {}).get('model')
            if pinned and family(pinned) != family(requested): raise ValueError('role family changed')
        except BaseException:
            if lease is not None:
                try:
                    if getattr(c, 'engine', None) is not None:
                        from budget import release_uninvoked
                        release_uninvoked(c.ledger, lease.lease_id)
                finally: model_router.finish(lease.lease_id, 'denied', None)
            raise
        context = copy.copy(c)
        if not hasattr(c, 'router_interrupted_calls'): c.router_interrupted_calls = []
        context.router_interrupted_calls = c.router_interrupted_calls
        context.router_model = requested
        context.role_cancel = getattr(c, 'role_cancel', None) or threading.Event()
        context.model_env = dict(getattr(c, 'model_env', {}))
        active_seconds, last_wait, prior_waits = 0, None, []
        call_group = uuid.uuid4().hex
        operation_id = getattr(c, 'model_operation_id', None) or str(uuid.uuid4())
        duration = timeout or getattr(getattr(c, 'args', None), 'agent_timeout', 2400)
        if user is not None or role in model_router.WALLED_ROLES:
            # A walled role reaches only a gate's port, and a free route has no gate: it takes the
            # family's gated or subscription route instead (model_call_gate.enforce refuses it too).
            # Calibrator preflights run unwalled but are excluded the same way, so they test the real route.
            accounts = getattr(c, 'router_accounts', model_router.ACCOUNTS)
            context.router_excluded = (*getattr(context, 'router_excluded', ()), *model_router.free_lanes(requested, accounts))
            if not [r for r in model_router._bounded_routes(requested, accounts)
                    if r['pool'] + '/' + r['route'] not in context.router_excluded]:
                raise model_router.ProviderWait(role, model_router.Wait('unbounded_route',
                    model_router.retry_at('unbounded_route'), route=requested))
        while True:
            if lease is None:
                if getattr(c, 'engine', None) is not None:
                    from budget import available_invocation_funding
                    from decimal import Decimal
                    funding = Decimal(available_invocation_funding(c.ledger, c.engine))
                    owner_models = getattr(c, 'exam_owner_models', None)
                    if owner_models and role in ('strong_calibrator', 'easy_calibrator'):
                        choices = model_router._bounded_routes(owner_models[0], getattr(c, 'router_accounts', model_router.ACCOUNTS))
                        if not choices:
                            raise model_router.ProviderWait('reviewer', model_router.Wait(
                                'unbounded_route', model_router.retry_at('unbounded_route'), route=owner_models[0]))
                        # The exam can ask its owner while this invocation is still in flight.
                        # Keep one qualified reviewer window outside the parent's hold.
                        funding -= max(Decimal(str(choice['max_usd'])) for choice in choices)
                        if funding <= 0: raise BudgetError('budget_exhausted:grant_insufficient')
                    context.router_funding_usd = format(funding, '.9f')
                try: lease = model_router.await_lease(role, context, deadline)
                except model_router.ProviderWait as error:
                    # Earlier serial attempts contribute usage, not additional
                    # reset constraints: only the currently awaited alternative
                    # controls when this logical call can continue.
                    error.previous_waits = [{**row, 'historical': True} for row in prior_waits]
                    raise
            if not model_router.valid_lease(lease, requested, getattr(context, 'router_accounts', model_router.ACCOUNTS)):
                identity = getattr(lease, 'lease_id', None)
                if isinstance(identity, str) and re.fullmatch(r'[a-f0-9]{32}', identity):
                    try:
                        if getattr(c, 'engine', None) is not None:
                            from budget import release_uninvoked
                            release_uninvoked(c.ledger, identity)
                    finally:
                        try: model_router.finish(identity, 'denied', None)
                        except model_router.RouterUnavailable: pass
                context.router_unbounded = True
                context.router_wait = model_router.Wait('unbounded_route', model_router.retry_at('unbounded_route'),
                    route=requested, lease_id=identity if isinstance(identity, str) and re.fullmatch(r'[a-f0-9]{32}', identity) else None)
                lease = None
                continue
            c.model_lease = context.model_lease = lease
            context.model_cap_used = model_call_gate.empty_usage(lease.route)
            receipt_row = {'invocation': name, 'requested_model': requested, 'call_group_id': call_group,
                           **asdict(lease), 'outcome': 'admitted'}
            c.card.setdefault('route_receipts', []).append(receipt_row)
            before = _read_json(getattr(c, 'ledger', '/nonexistent'), {})
            cleanup_before = len(c.card.get('cleanup_errors', []))
            outcome, receipt, failure, invoked, lost, cancelled = 'denied', None, None, False, None, False
            context.router_condition_since = None
            started = time.monotonic()
            try:
                if getattr(c, 'engine', None) is not None:
                    import budget
                    reservation = budget.reserve_invocation(c.ledger, lease, invocation_maximum(c, lease),
                        attempt=c.engine, operation_id=operation_id, call_name=name,
                        parent_call_name=getattr(c, 'parent_call_name', None))
                    c.invocation_reservation = context.invocation_reservation = reservation
                with model_router.running(lease, context.role_cancel) as lost:
                    model_router._start(lease)
                    context._model_launch_permit = lease.lease_id
                    if lease.account and not (model_router.SECRETS / lease.account).is_file():
                        raise BudgetError('codex_login_expired' if lease.account == 'codex-auth.json' else 'credential_expiring',
                            provider_failure={'reason': 'credential_expiring', 'scope': 'account', 'model': lease.route})
                    if lease.account and lease.account != 'codex-auth.json':
                        key = ('CLAUDE_CODE_OAUTH_TOKEN' if lease.account.startswith('claude') else
                               'OPENROUTER_API_KEY' if lease.account == 'openrouter-key' else 'OPENCODE_API_KEY')
                        context.model_env[key] = (model_router.SECRETS / lease.account).read_text().rstrip('\n')
                    limit = duration - active_seconds
                    if deadline is not None: limit = min(limit, deadline - time.monotonic())
                    if limit <= 0: raise BudgetError('timeout')
                    if before_attempt is not None: before_attempt()
                    invoked, outcome = True, 'interrupted'
                    context.model_process_state = {'started': False}
                    try:
                        code = self._invoke(context, [lease.route], text, cwd, name, user=user, timeout=limit, deadline=deadline)
                    finally:
                        if getattr(c, 'engine', None) is not None and not context.model_process_state['started']:
                            invoked, outcome = False, 'denied'
                    if lost.is_set(): raise model_router.RouterUnavailable('lease renewal uncertain')
                    if code: raise BudgetError('process_error')
                    outcome = 'done'
            except BudgetError as error:
                cancelled = str(error) == 'cancelled'
                failure = ({'reason': 'router_unavailable', 'model': lease.route} if lost is not None and lost.is_set()
                           else getattr(error, 'provider_failure', None))
                if failure is None:
                    reason = call_failure_reason(str(error), lease.route)
                    if reason: failure = {'reason': reason, 'model': lease.route, 'per_call': True}
                if not failure: raise
                from durable.classify import FAILURE_STOPS
                if failure.get('source_stop') not in FAILURE_STOPS:
                    failure = {k: v for k, v in failure.items() if k != 'source_stop'}
                if failure.get('per_call'):
                    stop = str(error).partition(':')[0]
                    if 'source_stop' not in failure and stop in FAILURE_STOPS:
                        failure = {**failure, 'source_stop': stop}
                    context.router_excluded = (*getattr(context, 'router_excluded', ()), lease.pool + '/' + lease.route)
                context.router_condition_since = time.monotonic()
                if failure.get('reason') == 'quota' and lease.route.startswith('claude/'):
                    reset = _read_json(getattr(c, 'ledger', '/nonexistent'), {}).get('claude_resets_at')
                    if model_router.finite(reset): failure = {**failure, 'reset_at': reset}
            except model_router.RouterUnavailable:
                failure = {'reason': 'router_unavailable', 'model': lease.route}
                context.router_condition_since = time.monotonic()
            finally:
                active_seconds += time.monotonic() - started
                for key in ('budget_resumed', 'force_budget_resume'):
                    if hasattr(context, key): setattr(c, key, getattr(context, key))
                try:
                    if hasattr(c, 'work'):
                        after = _read_json(getattr(c, 'ledger', '/nonexistent'), {})
                        old_ids = {e['id'] for e in before.get('events', []) if e.get('id')}
                        events = [e for e in after.get('events', []) if invoked and e.get('id') and e['id'] not in old_ids and e.get('invocation') == name]
                        unidentified = max(0, sum(not e.get('id') and e.get('invocation') == name for e in after.get('events', []))
                            - sum(not e.get('id') and e.get('invocation') == name for e in before.get('events', [])))
                        receipt = 'usage-receipts/' + lease.lease_id + '.json'
                        (accounting_work(c) / 'usage-receipts').mkdir(exist_ok=True)
                        atomic_json(accounting_work(c) / receipt, {'lease_id': lease.lease_id, 'invocation': name,
                            **{k: getattr(lease, k) for k in model_router.MAXIMUM_FIELDS},
                            'cap_used': dict(context.model_cap_used),
                            'booked_event_ids': [e['id'] for e in events],
                            'usage_delta': {k: sum(e.get(k, 0) for e in events) for k in ('cost', 'list_cost_usd', 'estimated_subscription_cost_usd')},
                            'events': events, 'unidentified_events': unidentified,
                            'final_usage_known': not invoked or (outcome == 'done' and not unidentified
                                and case_spending(after)['spent_usd'] is not None
                                and len(c.card.get('cleanup_errors', [])) == cleanup_before
                                and context.model_cap_used['closed']
                                and not context.model_cap_used['unknown_requests']
                                and not context.model_cap_used['in_flight_requests']),
                            'outcome': outcome,
                            'failure_reason': failure.get('reason') if failure and failure.get('reason') in model_router.REASONS else None,
                            'source_stop': failure.get('source_stop') if failure else None})
                        # Process-start evidence first: accounting below may raise.
                        receipt_row.update(outcome=outcome, call_id=receipt)
                        if getattr(c, 'engine', None) is not None and lease.lease_id in after.get('invocation_reservations', {}):
                            from budget import complete_invocation
                            complete_invocation(accounting_work(c), c.ledger, lease.lease_id)
                    receipt_row.update(outcome=outcome, call_id=receipt)
                    if cancelled and invoked and receipt:
                        with INTERRUPTED_LOCK:
                            c.router_interrupted_calls.append({
                                'role': role, 'lease_id': lease.lease_id, 'call_id': receipt,
                                'route': lease.route, 'account': lease.account})
                finally:
                    # Publish the shared limit before freeing its slot, closing the
                    # finish->observe race that would admit another worker to it.
                    if invoked and failure and failure['reason'] != 'router_unavailable' and not failure.get('per_call') and not failure.get('shared_paid'):
                        try:
                            model_router.observe(lease=lease, reason=failure['reason'], reset_at=failure.get('reset_at'),
                                observation_id=lease.lease_id + ':failure')
                        except model_router.RouterUnavailable:
                            failure = {'reason': 'router_unavailable', 'model': lease.route}
                    # Every exit attempts release. A lost acknowledgement must never cause another CLI call.
                    release_started = time.monotonic()
                    try: model_router.finish(lease.lease_id, outcome, receipt)
                    except model_router.RouterUnavailable:
                        if sys.exc_info()[1] is not None and failure is None and outcome != 'done':
                            c.card.setdefault('cleanup_errors', []).append({'stage':'lease_finish', 'error':'RouterUnavailable'})
                        else:
                            try:
                                model_router._finish_until_known(lease, outcome, receipt, role, context, deadline,
                                    since=context.router_condition_since or release_started)
                            except model_router.ProviderWait as error:
                                error.previous_waits = prior_waits
                                raise
            if failure is None: return code
            if getattr(c, 'engine', None) is not None:
                from durable.checkpoints import checkpoint
                checkpoint(c)
            last_wait = model_router.Wait(failure['reason'], model_router.retry_at(failure['reason'], reset_at=failure.get('reset_at')),
                evidence='interrupted', route=lease.route, account=lease.account,
                lease_id=lease.lease_id, call_id=receipt)
            if invoked:
                prior_waits.append({'role': role, **asdict(last_wait),
                                    **({'source_stop': failure['source_stop']} if failure.get('source_stop') else {})})
            if failure.get('shared_paid'):
                # Financial refusal must not restart a CLI even before the
                # general provider-wait rollout flag is enabled.
                error = model_router.ProviderWait(role, last_wait)
                error.previous_waits = prior_waits
                raise error
            context.router_wait = last_wait
            context.router_uncertain = last_wait.reason == 'router_unavailable'
            if context.router_uncertain and context.role_cancel.is_set():
                # Renewal cancelled the old CLI/peers. Waiting itself must not
                # turn that internal cancellation into a case recovery attempt.
                context.role_cancel = threading.Event()
            context.router_deferred = ((not invoked and last_wait.reason == 'credential_expiring')
                                       or len(c.card.get('cleanup_errors', [])) > cleanup_before
                                       or (last_wait.reason == 'router_unavailable'
                                           and os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1')
                                       or (getattr(c, 'engine', None) is not None and os.environ.get('UNBUG_PROVIDER_WAIT', '0') == '1'
                                           and not free_usage_settled(lease)
                                           and not _read_json(accounting_work(c) / receipt, {}).get('final_usage_known', False)))
            context.force_budget_resume = c.force_budget_resume = True
            lease = None


    def _hand_to(self, c, user, staged):
        """Move a prepared config dir into an isolated user's home and give it to that user. The runner cannot enter
        that home (700): creating the dir there directly failed with PermissionError at G10 (2026-10-17)."""
        cache = self.pilot_home(user) / ".cache"
        self.command(c, ["sudo", "install", "-d", "-o", user, "-g", user, "-m", "700", str(cache)], check=True)
        target = cache / staged.name
        self.command(c, ["sudo", "mv", str(staged), str(target)], check=True)
        self.command(c, ["sudo", "chown", "-R", f"{user}:{user}", str(target)], check=True)
        return target


    def _invoke(self, c, models, text, cwd, name, user=None, timeout=None, deadline=None):
        """One isolated CLI per role call (opencode-go/…, codex/…, claude/…), observed ceilings, no silent fallback."""
        if len(models) != 1: raise ValueError("Only one model per role is permitted")
        model = models[0]
        lease = getattr(c, 'model_lease', None)
        if (not model_router.valid_lease(lease, model)
                or c.__dict__.pop('_model_launch_permit', None) != lease.lease_id):
            raise model_router.ProviderWait(invocation_role(name), model_router.Wait(
                'unbounded_route', model_router.retry_at('unbounded_route'), route=model))
        prepare = getattr(getattr(c, 'engine', None), 'prepare_models', None)
        if prepare is not None and not os.environ.get('UNBUG_MODEL_CGROUP_ROOT'):
            prepare()  # Probe kernel containment before launching any model process.
        case_budget_boundary(c, model)
        driver, _, model_id = model.partition("/")
        if model in model_call_gate.CLAUDE_PROFILES:
            model_id = model_call_gate.claude_profile(model)['model'].partition('/')[2]
        driver = driver if driver in ("codex", "claude") else "opencode"
        role = invocation_role(name)
        timeout = role_timeout(c, name, timeout)
        effort = c.card.get('roles', {}).get(role, {}).get('effort', model_effort(model))
        memory_scratch = False
        env, scratch = {k: v for k, v in {**os.environ, **getattr(c, "model_env", {})}.items()
                        if not k.startswith("FACTORY_ROUTER_")}, None
        env = diagnostic_env(c, name, role, env)
        diagnosis = user == 'pilot' and name.startswith('diagnosis-')
        if diagnosis: env = diagnosis_environment(env, driver, lease, self.pilot_home(user))
        if user: env.pop("UNBUG_JUDGE", None)  # calibrators solve like contestants: no administrator judge reads
        if driver == "opencode":
            cli_model = model
            cmd = [OPENCODE_BIN, "run", *_opencode_flags(OPENCODE_BIN), "-m", cli_model, "--format", "json", "--auto", "--title", f"factory-{name}", text]
            if effort != 'default': cmd[2:2] = ['--variant', effort]
            if user: cmd = ["sudo", "--preserve-env", "-H", "-u", user] + cmd
            scratch = pathlib.Path(tempfile.mkdtemp(prefix='factory-tester-state-'))
            if getattr(c, 'engine', None) is not None and sys.platform == 'linux':
                # Executable private tmpfs: OpenCode's cache includes native helpers.
                try:
                    self.command(c, ['sudo', 'mount', '-t', 'tmpfs', '-o',
                        f'mode=0700,size=2g,nodev,nosuid,uid={os.getuid()},gid={os.getgid()}',
                        'tmpfs', str(scratch)], check=True)
                    memory_scratch = True
                except Exception:
                    self._remove_state(c, scratch, memory=True, allow_absent=True)
                    raise BudgetError('containment_unavailable') from None
            try:
                if user: self.command(c, ['sudo', 'chown', '-R', f'{user}:{user}', scratch], check=True)
            except BaseException:
                self._remove_state(c, scratch, memory=memory_scratch, user=user)
                raise
            if not diagnosis: env['OPENCODE_ENABLE_EXA'] = '1'
            env.update(XDG_CONFIG_HOME=str(scratch/'config'),
                       XDG_DATA_HOME=str(scratch/'data'), XDG_CACHE_HOME=str(scratch/'cache'))
            if model not in GATED_OPENROUTER:
                env['OPENCODE_CONFIG'] = str(opencode_config(cli_model, case=c.case_id, diagnosis=diagnosis))
        else:  # fresh config/state dir per call, no session files: roles share nothing but what run.py passes
            # Not /tmp: codex refuses its helper binaries under a temp dir. Prepared where the runner can write; an
            # isolated user's copy is then moved into that user's (private) home by hand_to().
            base = self.home / ".cache"; base.mkdir(exist_ok=True)
            scratch = pathlib.Path(tempfile.mkdtemp(prefix=f"factory-{driver}-", dir=base))
        if driver == "codex":
            # ChatGPT access token is re-read from RAM; CODEX_HOME supplies config.toml only.
            src = pathlib.Path(env.get("CODEX_HOME", self.home / ".codex"))
            auth_source = model_router.SECRETS / "codex-auth.json"
            from codex_login import worker_auth
            try:
                auth = worker_auth(json.loads(auth_source.read_text()))
                target = scratch / "auth.json"
                target.touch(mode=0o600)
                target.write_text(json.dumps(auth))
            except (OSError, ValueError, KeyError, TypeError):
                try: self.cleanup(scratch)
                except Exception as error:
                    c.card.setdefault('cleanup_errors', []).append({'stage':'model_scratch', 'error':type(error).__name__})
                raise BudgetError('codex_login_expired') from None
            keep, lines = True, []  # config minus MCP servers (boat's `computer` desktop tool)
            for line in ((src / "config.toml").read_text().splitlines() if (src / "config.toml").is_file() else []):
                if line.lstrip().startswith("["): keep = not line.lstrip().lstrip("[").startswith("mcp_servers")
                if keep: lines.append(line)
            (scratch / "config.toml").write_text("\n".join(lines) + "\n")
            env = {k: v for k, v in env.items() if not k.startswith(("OPENAI_", "AZURE_OPENAI_", "CODEX_"))}
            env["CODEX_HOME"] = str(scratch)
            # No subagents, no web (hosted search, browser, apps/plugins, computer use), no image generation.
            off = [x for f in CODEX_OFF for x in ("--disable", f)]
            # Not --ephemeral: the session log in CODEX_HOME is Codex's per-request usage report (usage_feed).
            cmd = [pinned_cli("codex"), "exec", "--json", "--skip-git-repo-check",
                   "--dangerously-bypass-approvals-and-sandbox", *off, "-m", model_id,
                   "-c", f'model_reasoning_effort="{effort}"', "-c", 'web_search="disabled"', "-C", str(cwd), text]
            if user:  # the pilot runs as its own Unix user with its own copy of the subscription config
                scratch = self._hand_to(c, user, scratch); env["CODEX_HOME"] = str(scratch)
                cmd = ["sudo", "--preserve-env=CODEX_HOME,PATH", "-H", "-u", user] + cmd
        elif driver == "claude":
            # Claude subscription: CLAUDE_CODE_OAUTH_TOKEN from launch.sh (`claude setup-token`); an API key would bill the API.
            env = {k: v for k, v in env.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
            env.update({"CLAUDE_CONFIG_DIR": str(scratch), "DISABLE_AUTOUPDATER": "1"})
            cmd = [pinned_cli("claude"), "-p", text, "--output-format", "stream-json", "--verbose", "--model", model_id,
                   "--effort", effort, "--dangerously-skip-permissions", "--no-session-persistence",
                   "--setting-sources", "user", "--strict-mcp-config", "--tools",
                   # no subagents; web only for the roles whose prompts require logged web/GitHub searches (G2)
                   "Bash,Edit,Read,Write" + (",WebSearch,WebFetch" if role in ("writer", "stress_tester") else "")]
            if user:
                scratch = self._hand_to(c, user, scratch); env["CLAUDE_CONFIG_DIR"] = str(scratch)
                cmd = ["sudo", "--preserve-env=" + ','.join(model_call_gate.ENV_KEYS), "-H", "-u", user] + cmd
        if user:  # the isolated user's dir is private (700): it changes into it itself; the runner never does
            i = cmd.index(user) + 1
            cmd = cmd[:i] + ["sh", "-c", 'cd "$1" && shift && exec "$@"', "sh", str(cwd)] + cmd[i:]
        c.card.setdefault("models_used", {})[name] = model
        transcript = c.work / "transcripts" / f"{name}.{time.time_ns()}.jsonl"
        progress_role = {'reviewer2': 'reviewer', 'strong_calibrator': 'strong_tester',
                         'easy_calibrator': 'easy_tester'}.get(role, role)
        progress_started = time.monotonic()
        self.progress(c, 'role:' + progress_role, 'running')
        try:
            limit = timeout or c.args.agent_timeout
            if deadline is not None:
                limit = min(limit, deadline - time.monotonic())
                if limit <= 0: raise BudgetError('timeout')
            attempt_kwargs = {}
            if getattr(c, 'engine', None) is not None:
                reservation = c.invocation_reservation
                attempt_kwargs = dict(attempt=c.engine, invocation_id=reservation['invocation_id'],
                    lease_id=reservation['lease_id'], on_started=lambda: c.model_process_state.update(started=True))
            if driver == "codex":
                # No gate: Codex's live usage holds the call to its reservation, or outside the engine to its lease maximum.
                attempt_kwargs['usage_feed'] = codex_usage_feed(scratch, user)
                if not attempt_kwargs.get('attempt'): attempt_kwargs['call_cap_usd'] = lease.max_usd
            with model_call_gate.enforce(lease, env, c.model_cap_used, limit, getattr(c, 'role_cancel', None), user=user) as gate:
                if diagnosis and driver == 'opencode':
                    env.pop('OPENCODE_ENABLE_EXA', None)
                    if model in GATED_OPENROUTER:
                        cfg = json.loads(env['OPENCODE_CONFIG_CONTENT'])
                        cfg['permission'].update(webfetch='deny', websearch='deny')
                        env['OPENCODE_CONFIG_CONTENT'] = json.dumps(cfg)
                    # The gate replaces env, including its inline config and isolation flags.
                    cmd[1] = '--preserve-env=' + ','.join(env)
                with diagnosis_loopback(c, self.command, gate, diagnosis):
                    result = run_budgeted(cmd, None if user else cwd, env, transcript, c.ledger, limit,
                                  max_cost=None if getattr(c, 'engine', None) is not None else c.args.max_cost,
                                  max_calls=c.args.max_role_calls, max_total_calls=c.args.max_total_calls, driver=driver,
                                  progress_timeout=c.args.no_progress_minutes * 60, max_zero_tokens=c.args.max_zero_tokens,
                                  configured_model=model, resume=(bool(getattr(c.args, "resume", None)) and not getattr(c, "budget_resumed", False))
                                  or getattr(c, "force_budget_resume", False),
                                  concurrent=getattr(c, 'engine', None) is not None or getattr(c.args, "concurrent_roles", False), cancel=gate,
                                  case_budget=getattr(c.args, 'case_budget', 50.0), role=role, invocation_name=name,
                                  containment=not user, **attempt_kwargs)
            update_case_budget(c)
            c.budget_resumed = True; c.force_budget_resume = False
            self.progress(c, 'role:' + progress_role, 'completed' if result.returncode == 0 else 'failed',
                            time.monotonic() - progress_started)
        except BudgetError as error:
            if str(error) in ('containment_unavailable', 'cancellation_failed'):
                c.card.setdefault('cleanup_errors', []).append(
                    {'stage': 'model_containment', 'error': str(error)})
            self.progress(c, 'role:' + progress_role, 'interrupted', time.monotonic() - progress_started)
            raise
        except Exception as error:
            self.progress(c, 'role:' + progress_role, 'failed', time.monotonic() - progress_started)
            raise BudgetError('usage_monitor:' + type(error).__name__) from error
        except BaseException:
            self.progress(c, 'role:' + progress_role, 'interrupted', time.monotonic() - progress_started)
            raise
        finally:
            original = sys.exc_info()[1]
            cleanup_error = None
            # sudo cannot pass SIGKILL on: after any stop the isolated user's CLI may survive the process-group kill.
            for stage, action in (
                    ('model_process', lambda: self.command(c, ["sudo", "pkill", "-KILL", "-u", user]) if user else None),
                    ('model_join', lambda: __import__('diagnosis_task')._quiet(pwd.getpwnam(user).pw_uid) if diagnosis else None),
                    ('model_scratch', lambda: self._remove_state(c, scratch, memory=memory_scratch, user=user) if scratch else None)):
                try: action()
                except Exception as error:
                    c.card.setdefault('cleanup_errors', []).append({'stage':stage, 'error':type(error).__name__})
                    cleanup_error = error
            if cleanup_error is not None and original is None:
                raise BudgetError('cleanup_failed') from cleanup_error
        return result.returncode

