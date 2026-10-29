"""Model selection and isolated CLI execution for factory roles.

The runner supplies command, progress and cleanup adapters. This module owns
provider routing, credentials, CLI policy and budget integration; it never imports
or inspects the factory runner. Durable run checkpointing stays with the caller.
"""
from dataclasses import dataclass
from functools import lru_cache
from typing import Callable
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
from budget import BudgetError, run_budgeted, case_spending, require_case_budget, invocation_role

PROMPTS = pathlib.Path(__file__).resolve().parent / "prompts"
OPENCODE_BIN = os.environ.get("FACTORY_OPENCODE_BIN", "opencode")
CODEX_VERSION, CLAUDE_VERSION = "0.162.1", "2.1.299"
CLAUDE_PREFIX = pathlib.Path("/tmp/factory-claude-cli")
CODEX_OFF = ["multi_agent", "apps", "plugins", "remote_plugin", "browser_use", "browser_use_external",
             "in_app_browser", "computer_use", "image_generation"]
PROVIDER_ROUTES = {
    # 2026-10-26: same DeepSeek weights on paid OpenRouter; keep recorded role names.
    "opencode/deepseek-v4.1-flash-free": "openrouter/deepseek/deepseek-v4.1-flash",
    "opencode-go/mimo-v2.6-pro": "openrouter/xiaomi/mimo-v2.6-pro",
    "opencode/minimax-m3.1-flash-free": "openrouter/minimax/minimax-m3.1-flash:free",
}
FREE_FALLBACK = {"opencode/glm-5.3-flash-free": "opencode-go/glm-5.3-flash"}
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
    """One explicit model per role; quota/provider failure stops the factory."""
    a = c.args
    roles = rotation(a.rotation_slot or 1, getattr(a, 'rotation_table', None))
    flags = {'writer': 'builder', 'stress_tester': 'attacker', 'reviewer': 'reviewer1', 'strong_calibrator': 'strong_calibrator'}
    for role, flag in flags.items():
        if getattr(a, flag): roles[role] = {'model': getattr(a, flag), 'effort': getattr(a, flag + '_effort') or model_effort(getattr(a, flag))}
        elif getattr(a, flag + '_effort'): roles[role]['effort'] = getattr(a, flag + '_effort')
    roles['easy_calibrator'] = {'model': a.easy_calibrator, 'effort': a.easy_calibrator_effort or model_effort(a.easy_calibrator)}
    if a.reviewer2: roles['reviewer2'] = {'model': a.reviewer2, 'effort': a.reviewer2_effort or model_effort(a.reviewer2)}
    from free_models import apply as apply_free_models
    roles = apply_free_models(c, roles)
    families = [family(roles[r]['model']) for r in flags]
    if len(set(families)) != 4: raise ValueError('Writer, stress-tester, strong calibrator and reviewer must be four different families')
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
        raise ValueError("Automatic model fallback is disabled; select one model per role")
    log(c, "models", json.dumps(m))
    return m


def family(model):
    if model.startswith(('claude/', 'anthropic/')) or '/anthropic/' in model: return 'anthropic'
    if model.startswith(('codex/', 'openai/')) or '/openai/' in model: return 'openai'
    if 'minimax' in model.lower(): return 'minimax'
    if 'deepseek' in model.lower(): return 'deepseek'
    if 'mimo' in model.lower(): return 'xiaomi'
    if 'muse-spark' in model.lower(): return 'meta'
    if 'grok' in model.lower(): return 'xai'
    if 'qwen' in model.lower(): return 'alibaba'
    if 'glm' in model.lower(): return 'z-ai'
    if model.startswith('openrouter/'): return model.split('/')[1]
    return model.split('/')[0]


def model_effort(model):
    return 'high' if model.startswith(('claude/', 'codex/')) else 'xhigh' if family(model) == 'meta' else 'default'


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


def opencode_config(model=None, case=None):
    """Merged over the user config: provider keys come from the environment (factory/launch.sh loads
    them from ~/.secrets; boat's paid relay is off since 2026-10-16), and boat's desktop `computer`
    MCP off (about 28k prompt tokens a call, unneeded). In /tmp so the pilot user can read it; no secret."""
    model = PROVIDER_ROUTES.get(model, model)
    path = pathlib.Path("/tmp/factory-opencode.json")
    base = os.environ.get("OPENCODE_API_KEY_BASE_URL")
    cfg = {"mcp": {"computer": {"enabled": False}},
           "compaction": {"auto": True}, "permission": {"task": "deny"},  # on since 2026-10-17: off, MiMo re-read ~500k tokens a step
           "provider": {"openrouter": {"models": {
               "deepseek/deepseek-v4.1-flash": {"cost": {"input": 0.02, "output": 1.00}},
               "meta/muse-spark-1.3-contributor": {
               "cost": {"input": 0.10, "output": 0.20, "cache_read": 0.002, "cache_write": 0.10}}}}}}
    # OpenCode v1.19 does not know Muse Contributor's price; without one the budget guard stops the run.
    go = {"models": {"muse-spark-1.3-contributor": {"cost": {"input": 0.10, "output": 0.20, "cache_read": 0.002, "cache_write": 0.10}}}}
    go["options"] = {"apiKey": "{env:OPENCODE_API_KEY}"}
    if base: go["options"]["baseURL"] = base.rstrip("/") + "/go/v1"
    cfg["provider"]["opencode-go"] = go
    # Founder 2026-10-19: OpenCode v1.x answers Muse with "Invalid credential" unless the opencode provider points at Zen.
    cfg["provider"]["opencode"] = {"options": {"baseURL": "https://opencode.ai/zen/v1"}}
    if model == "opencode/minimax-m3.1-flash-free":
        from free_models import provider_config
        cfg["provider"]["opencode"] = provider_config(case, model)
        cfg["small_model"] = model
        path = path.with_name("factory-opencode-" + model.split("/", 1)[1] + ".json")
    elif model in PROVIDER_ROUTES.values():
        cfg["small_model"] = model  # compaction follows the same approved provider/model
        path = path.with_name("factory-" + model.replace("/", "-").replace(":", "-") + ".json")
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, prefix=path.name, delete=False) as staged:
        json.dump(cfg, staged)
    os.chmod(staged.name, 0o644); os.replace(staged.name, path)
    return path


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
    summary = {**{k: v for k, v in c.card.get('case_budget', {}).items() if k == 'unpriced_model'},
               'limit_usd': getattr(c.args, 'case_budget', 50.0),
               **case_spending(ledger, c.card.get('models_used'))}
    c.card['case_budget'] = summary
    return ledger, summary


def case_budget_boundary(c, model=None):
    ledger, summary = update_case_budget(c)
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


@dataclass(frozen=True)
class ModelRuntime:
    """Execute one routed role call with caller-owned operational adapters."""
    home: pathlib.Path
    command: Callable
    progress: Callable
    cleanup: Callable
    pilot_home: Callable

    def call(self, c, models, text, cwd, name, user=None, timeout=None, deadline=None, before_attempt=None):
        """Apply explicit provider routes, then the remaining same-model OpenCode fallback."""
        routes = c.__dict__.setdefault("routes", {})
        model = PROVIDER_ROUTES.get(models[0], routes.get(models[0], models[0]))
        if models[0] in PROVIDER_ROUTES:
            c.card.setdefault("provider_routes", {})[models[0]] = model
        def invoke(selected):
            limit = timeout
            if deadline is not None:
                limit = min(timeout or c.args.agent_timeout, deadline - time.monotonic())
                if limit <= 0: raise BudgetError('timeout')
            if before_attempt is not None: before_attempt()
            return self._invoke(c, [selected], text, cwd, name, user=user, timeout=limit, deadline=deadline)
        try:
            return invoke(model)
        except BudgetError as error:
            alt = None if c.card.get("model_transition") else FREE_FALLBACK.get(model)
            if not alt or not (str(error) in ("opencode_error", "process_error") or str(error).startswith("provider_limit")): raise
            routes[models[0]] = alt
            c.card.setdefault("free_model_fallback", []).append({"from": model, "to": alt, "why": str(error)})
            c.force_budget_resume = True  # the failed call left a terminal stop in the ledger; archive it and go on
            return invoke(alt)


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
        case_budget_boundary(c, model)
        driver, _, model_id = model.partition("/")
        driver = driver if driver in ("codex", "claude") else "opencode"
        role = invocation_role(name)
        if role == 'stress_tester':
            timeout = min(timeout or c.args.agent_timeout, attacker_timeout(c))
        effort = c.card.get('roles', {}).get(role, {}).get('effort', model_effort(model))
        env, scratch = {**os.environ, **getattr(c, "model_env", {})}, None
        env = diagnostic_env(c, name, role, env)
        if user: env.pop("UNBUG_JUDGE", None)  # calibrators solve like contestants: no administrator judge reads
        if driver == "opencode":
            cli_model = model
            cmd = [OPENCODE_BIN, "run", *_opencode_flags(OPENCODE_BIN), "-m", cli_model, "--format", "json", "--auto", "--title", f"factory-{name}", text]
            if effort != 'default': cmd[2:2] = ['--variant', effort]
            if user: cmd = ["sudo", "--preserve-env", "-H", "-u", user] + cmd
            if user:
                scratch = pathlib.Path(tempfile.mkdtemp(prefix='factory-tester-state-'))
                self.command(c, ['sudo', 'chown', '-R', f'{user}:{user}', scratch], check=True)
            env.update({"OPENCODE_ENABLE_EXA": "1", "OPENCODE_CONFIG": str(opencode_config(cli_model, case=c.case_id)),
                        "XDG_DATA_HOME": str(scratch if user else env.get("XDG_DATA_HOME", self.home / ".local/share/factory-opencode"))})
        else:  # fresh config/state dir per call, no session files: roles share nothing but what run.py passes
            # Not /tmp: codex refuses its helper binaries under a temp dir. Prepared where the runner can write; an
            # isolated user's copy is then moved into that user's (private) home by hand_to().
            base = self.home / ".cache"; base.mkdir(exist_ok=True)
            scratch = pathlib.Path(tempfile.mkdtemp(prefix=f"factory-{driver}-", dir=base))
        if driver == "codex":
            # ChatGPT subscription: ~/.codex/auth.json (a dedicated login pushed by launch.sh), never an API key.
            src = pathlib.Path(env.get("CODEX_HOME", self.home / ".codex"))
            if (src / "auth.json").is_file():
                from codex_login import worker_auth
                try:
                    auth = worker_auth(json.loads((src / "auth.json").read_text()))
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
            cmd = [pinned_cli("codex"), "exec", "--json", "--ephemeral", "--skip-git-repo-check",
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
                cmd = ["sudo", "--preserve-env=CLAUDE_CODE_OAUTH_TOKEN,CLAUDE_CONFIG_DIR,DISABLE_AUTOUPDATER,PATH", "-H", "-u", user] + cmd
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
            result = run_budgeted(cmd, None if user else cwd, env, transcript, c.ledger, limit, max_cost=c.args.max_cost,
                                  max_calls=c.args.max_role_calls, max_total_calls=c.args.max_total_calls, driver=driver,
                                  progress_timeout=c.args.no_progress_minutes * 60, max_zero_tokens=c.args.max_zero_tokens,
                                  configured_model=model, resume=(bool(getattr(c.args, "resume", None)) and not getattr(c, "budget_resumed", False))
                                  or getattr(c, "force_budget_resume", False),
                                  concurrent=getattr(c.args, "concurrent_roles", False), cancel=getattr(c, "role_cancel", None),
                                  case_budget=getattr(c.args, 'case_budget', 50.0), role=role, invocation_name=name)
            update_case_budget(c)
            c.budget_resumed = True; c.force_budget_resume = False
            self.progress(c, 'role:' + progress_role, 'completed' if result.returncode == 0 else 'failed',
                            time.monotonic() - progress_started)
        except BudgetError:
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
                    ('model_scratch', lambda: self.cleanup(scratch, sudo=bool(user)) if scratch else None)):
                try: action()
                except Exception as error:
                    c.card.setdefault('cleanup_errors', []).append({'stage':stage, 'error':type(error).__name__})
                    cleanup_error = error
            if cleanup_error is not None and original is None:
                raise BudgetError('cleanup_failed') from cleanup_error
        return result.returncode

