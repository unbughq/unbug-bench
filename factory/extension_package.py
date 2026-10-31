"""Retain one admitted round's gate execution across ordinary checkpoint restores."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from budget import BudgetError
import extension_compare as comparison
import extensions
import gate_state
import job_authority
from registry import atomic_json
from run_validity import InvalidInfra

# Execution/authority is current worker state, never restored by a scientific score.
EXCLUDED = frozenset('''case_budget continuation_budget job_money route_receipts models_used
 diagnosis_state extension_history factory_bug factory_bug_resume_count gates gate_results
 gate_minutes status terminal_stop infrastructure_gate failed_gate failed_detail resume
 resume_operation wall_minutes error checkpoint_error durable_checkpoint cleanup_errors
 public_progress_error router_waits router_interrupted_calls sha256 archive r2_object
 early_gates early_probe roles rotation_slot provider_accounts account_handoffs continuations
 calls_delta cost_delta case source seed dry_run models model kind verdict build_deferred
 budget_raised rounds_raised recovery_config limits restore_adjustment resume_rereview
 salvaged_from kept_from_previous_run kept_gate_source free_model_fallback model_transition
 provider_routes provider_preflight driver_qualification audit_source audit_inputs_sha256
 source_inputs_sha256 review_bench_sha256 digest_version inputs_unchanged audit_runtime_preparation
 delivery_provenance statement_cipher_sha256 dry_run_roundtrip wipe audit_calls_total
 audit_cost_total legacy_import builder_rounds candidate_attempts repairs batch_release_sha256
 job_identity calibration_interruptions router_pending_requests gate_continuation
 founder_ruling call_cap_ruling freshness_archive_ruling'''.split())
CONTEXT = ('statement', 'votes', 'votes_hash', 'pilot_passes', 'prepared_factory_slots')
PREPARATION = {'bench_workers_effective', 'factory_slots_prepared'}


def refuse(label='extension_snapshot_changed'):
    raise BudgetError(label)


def workspace(c, r):
    return comparison.Workspace(c.case, c.work, r.BENCH, c.args, c.models, c.card,
                                c.seed, getattr(c, 'factory_slot', 0), c.case_id)


def project(card):
    return copy.deepcopy({k: v for k, v in card.items() if k not in EXCLUDED})


class Records:
    def __init__(self, c, r, row):
        self.c, self.r, self.row = c, r, row
        self.root = c.work / 'extension-package' / str(row['extension_id'])
        self.completed = row['outcome'] is not None
        self.prepared = False

    def load(self, stage, *, check_version=True):
        path = self.root / stage / 'record.json'
        if not path.exists() and not path.is_symlink(): return None
        try:
            value = extensions._writer_json(path, self.c.work)
            data = value['record']
            if set(value) != {'record', 'sha256'} or extensions.digest(data) != value['sha256']:
                refuse()
            if set(data) != {'schema_version', 'writer_operation_id', 'round', 'case_sha256',
                    'scientific_version', 'ok', 'info', 'support', 'card', 'deleted', 'context'}:
                refuse()
            if (type(data['schema_version']) is not int or data['schema_version'] != 1 or
                    data['writer_operation_id'] != self.row['writer_operation_id'] or
                    type(data['round']) is not int or data['round'] != self.row['round'] or
                    data['case_sha256'] != self.r.case_hash(self.c) or
                    not isinstance(data['card'], dict) or set(data['card']) & EXCLUDED or
                    not isinstance(data['context'], dict) or set(data['context']) - set(CONTEXT) or
                    not isinstance(data['deleted'], list) or
                    any(not isinstance(k, str) or k in EXCLUDED for k in data['deleted']) or
                    comparison._pending(data['ok'], data['info']) or
                    not isinstance(data['support'], dict) or not data['support']):
                refuse()
            for name, sha in data['support'].items():
                if not name.startswith((self.root / stage / 'support').relative_to(self.c.work).as_posix() + '/'):
                    refuse()
                if gate_state.digest(comparison._path(self.c.work, name)) != sha: refuse()
            if stage == 'G3':
                count = data['card'].get('bench_workers_effective')
                if type(count) is not int or count < 1: refuse()
                self.c.args.bench_workers = count
            if check_version and data['scientific_version'] != gate_state.scientific_version(self.c, stage, self.r.BENCH):
                refuse('extension_comparison_pending')
            return data
        except (KeyError, ValueError, TypeError, OSError):
            refuse()

    def restore(self, stage, data):
        for key in data['deleted']:
            if not (self.prepared and key in PREPARATION): self.c.card.pop(key, None)
        for key, value in data['card'].items():
            if not (self.prepared and key in PREPARATION): self.c.card[key] = copy.deepcopy(value)
        for key, value in data['context'].items():
            if self.prepared and key == 'prepared_factory_slots': continue
            if key == 'pilot_passes':
                value = [comparison._path(self.c.work, name) if (self.c.work / name).is_file()
                         else self._guard(name) for name in value]
            setattr(self.c, key, copy.deepcopy(value))

    def _guard(self, name):
        path = Path(name)
        if path.is_absolute() or '..' in path.parts: refuse()
        target = self.c.work / path
        if any(p.is_symlink() for p in (target, *target.parents) if p.is_relative_to(self.c.work)):
            refuse()
        if not target.is_dir(): refuse()
        return target

    def replay(self, c, stage):
        data = self.load(stage)
        if data is None:
            if self.completed: refuse('extension_outcome_changed')
            return None
        if stage == 'G3' and not self.completed: return None
        self.restore(stage, data)
        return data['ok'], data['info']

    def sources(self, stage, before):
        c, r = self.c, self.r
        found = {}
        for key, path in gate_state.inventory(c, r.BENCH).items():
            if before.get(key) != gate_state.digest(path): found['/'.join(key)] = path
        cache = c.work / 'gate-cache' / (stage + '.json')
        if stage in gate_state.REUSABLE and gate_state.load(c, stage, r.BENCH) is not None:
            record = json.loads(cache.read_text())
            found['work/gate-cache/' + cache.name] = cache
            for item in record['evidence']:
                paths = ([r.BENCH / 'results' / item['path'], c.work / 'bench-results' / item['path']]
                         if item['kind'] == 'bench' else [c.work / item['path']])
                source = next((p for p in paths if p.is_file() and gate_state.digest(p) == item['sha256']), None)
                if source is None: refuse()
                found[item['kind'] + '/' + item['path']] = source
        # Predicate inputs are retained even when the gate emits only diagnostics.
        for path in c.case.rglob('*'):
            if path.is_file(): found['case/' + path.relative_to(c.case).as_posix()] = path
        roots = {'G10': ('strong_calibrator', 'easy_calibrator', 'early_probe'),
                 'G11': ('strong_calibrator', 'easy_calibrator', 'early_probe', 'g11-evidence'),
                 'G16': ('judge_breadth', 'fairness-g16-inputs', 'fairness-replacement-*'),
                 'G17': ('strong_calibrator', 'fairness-g17-inputs', 'fairness-replacement-*'),
                 'G2': ('public-search.json', 'freshness-verdict.json', 'g2-confirm-*', 'confirmation-retrieval-*'),
                 'stress': ('attack-state.json', 'attacks', 'stress-*', 'freshness-verdict.json',
                            'g2-confirm-*', 'confirmation-retrieval-*')}.get(stage, ())
        for pattern in roots:
            for root in c.work.glob(pattern):
                calibration = root.name in ('strong_calibrator', 'easy_calibrator', 'early_probe', 'judge_breadth') or root.name.startswith('fairness-replacement-')
                for path in root.rglob('*') if root.is_dir() else (root,):
                    if not path.is_file(): continue
                    if calibration and path.name not in ('results.json', 'execution.json') and 'guard' not in path.relative_to(root).parts:
                        continue
                    found['work/' + path.relative_to(c.work).as_posix()] = path
        if stage in ('G10', 'G11', 'G16', 'G17', 'stress'):
            for pattern in ('strong-calibrator-*.jsonl', 'easy-calibrator-*.jsonl', 'attacker-*.jsonl'):
                for path in (c.work / 'transcripts').glob(pattern):
                    found['work/' + path.relative_to(c.work).as_posix()] = path
        return found

    def save(self, stage, ok, info, before, old_card):
        if comparison._pending(ok, info): raise InvalidInfra('invalid package gate result')
        c, r = self.c, self.r
        target = self.root / stage
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix='.stage-', dir=self.root))
        try:
            support = {}
            inputs = (gate_state.judge_dependencies(c, r.BENCH) if stage == 'stress'
                      else gate_state.inputs(c, stage, r.BENCH))
            atomic_json(temporary / 'inputs.json', inputs)
            sources = self.sources(stage, before)
            sources['inputs.json'] = temporary / 'inputs.json'
            for name, source in sources.items():
                anchor = c.work if source.is_relative_to(c.work) else r.BENCH
                if any(p.is_symlink() for p in (source, *source.parents) if p.is_relative_to(anchor)): refuse()
                dest = temporary / 'support' / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(source.read_bytes())
                support[(target / 'support' / name).relative_to(c.work).as_posix()] = gate_state.digest(dest)
            context = {k: copy.deepcopy(getattr(c, k)) for k in CONTEXT if hasattr(c, k)}
            if 'pilot_passes' in context:
                context['pilot_passes'] = [str(Path(p).relative_to(c.work)) for p in context['pilot_passes']]
            card = project(c.card)
            data = dict(schema_version=1, writer_operation_id=self.row['writer_operation_id'],
                round=self.row['round'], case_sha256=r.case_hash(c),
                scientific_version=gate_state.scientific_version(c, stage, r.BENCH), ok=ok,
                info=info, support=support, card=card, deleted=sorted(set(old_card) - set(card)), context=context)
            atomic_json(temporary / 'record.json', {'record': data, 'sha256': extensions.digest(data)})
            extensions._sync_tree(temporary)
            if target.exists(): refuse()
            temporary.rename(target)
            extensions._sync_directory(self.root)
            return data
        finally:
            if temporary.exists(): shutil.rmtree(temporary)

    def capture(self, c, stage, invoke):
        old = self.load(stage) if stage == 'G3' else None
        before = {k: gate_state.digest(p) for k, p in gate_state.inventory(c, self.r.BENCH).items()}
        card, case = project(c.card), self.r.case_hash(c)
        ok, info = invoke()
        if self.r.case_hash(c) != case: refuse()
        if stage == 'G3':
            self.prepared = True
            if old is not None:
                if c.args.bench_workers != old['card']['bench_workers_effective']:
                    refuse('extension_comparison_pending')
                if not ok: raise InvalidInfra('G3 setup failed')
                return old['ok'], old['info']
        self.save(stage, ok, info, before, card)
        return ok, info

    def evidence(self, w, stage):
        data = self.load(stage)
        if data is None: return None
        return data['ok'], data['info'], list(data['support'])


def stress(c, r, records):
    retained = records.load('stress')
    if retained is not None: return retained
    if records.completed: refuse('extension_outcome_changed')
    receipt = extensions._writer_json(c.work / 'attack-state.json', c.work)
    report = c.work / 'attacks' / f"round-{records.row['round']}.json"
    completed = receipt.get('review_completed', {})
    if (receipt.get('actor') != 'stress_tester' or receipt.get('phase') != 'validated' or
            receipt.get('round') != records.row['round'] or receipt.get('report') != report.name or
            receipt.get('round_limit') != records.row['round'] or not report.is_file() or
            completed.get('attempt') != receipt.get('review_attempt') or
            completed.get('binding') != hashlib.sha256(json.dumps(receipt.get('binding'), sort_keys=True).encode()).hexdigest() or
            completed.get('report_sha256') != gate_state.digest(report)):
        refuse('extension_execution_pending')
    if receipt.get('binding') != r.attack_binding(c): refuse('extension_comparison_pending')
    result = r.attack_report(report)
    if result is None: refuse()
    if result.get('freshness_review') or result.get('freshness_review_malformed'):
        from late_recovery import cleared_stress
        try: result, _ = cleared_stress(c, receipt, report, result)
        except (OSError, ValueError, KeyError, TypeError): refuse('extension_execution_pending')
    if (not result['complete'] or result['unfinished_validation'] or r.attack_diagnostic_unfinished(c, records.row['round'])):
        refuse('extension_execution_pending')
    ok = not result['blocking']
    if ok and receipt.get('next_phase') != 'extension_comparison': refuse()
    if not ok and not (receipt.get('exhausted') is True and receipt.get('stop_reason') == 'rounds_exhausted'):
        refuse()
    c.card['stress_review'] = {'status': 'completed', 'round': records.row['round']}
    return records.save('stress', ok, result, {}, project(c.card))


def completed_route(c, row):
    """Validate package proof before routing a committed outcome's lagging card."""
    import run as r
    data = Records(c, r, row).load('stress', check_version=False)
    if data is None: refuse('extension_outcome_changed')


def run(c, r, previous, number):
    authority = job_authority.for_case(c)
    history = extensions.read(c)
    if type(number) is not int or not history or history[-1]['extension_id'] != number:
        refuse('extension_history_invalid')
    row = history[-1]
    records = Records(c, r, row)
    if not records.completed and records.load('stress') is None:
        try: r.write_and_attack(c, previous, extension_id=number)
        except BudgetError as error:
            if str(error) not in ('extension_comparison_pending', 'stress_review_unresolved:rounds_exhausted'):
                raise
    result = stress(c, r, records)
    records.restore('stress', result)
    for key in ('failed_gate', 'failed_detail'):
        c.card.pop(key, None)
    c.card['gates'], c.card['gate_results'] = {}, {}
    if result['ok']:
        for key in ('failed_gate', 'failed_detail', 'infrastructure_gate', 'terminal_stop', 'status'):
            c.card.pop(key, None)
        c.card['gates'], c.card['gate_results'] = {}, {}
        c.stopped = False
        from late_recovery import mark_gates
        mark_gates(c)
        getattr(c, 'early', {}).pop('G3', None)
        existed = hasattr(c.args, 'no_early_probe')
        probe = getattr(c.args, 'no_early_probe', None)
        c.args.no_early_probe = True
        try:
            r.run_gates(c, replay_gate=records.replay, around_gate=records.capture,
                        serial=True, replay_only=records.completed)
        finally:
            if existed: c.args.no_early_probe = probe
            else: del c.args.no_early_probe
        if c.stopped: return
    if records.completed:
        for stage in row['outcome']['stages']:
            expected = stage['status']
            actual = ('pass' if result['ok'] else 'fail') if stage['stage'] == 'stress' else c.card.get('gates', {}).get(stage['stage'], 'unreached')
            if actual != expected: refuse('extension_outcome_changed')
    else:
        snapshot = comparison.snapshot(workspace(c, r), authority.source_generation, records.evidence)
        extensions.complete(c, snapshot)
    if not result['ok'] or c.card.get('failed_gate'):
        raise BudgetError('extension_incomplete')
