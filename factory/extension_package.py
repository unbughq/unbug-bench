"""Retain one admitted round's gate execution across ordinary checkpoint restores."""
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
import uuid

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


def writer_feedback(stage, data):
    if data is None or data['ok'] is not False: refuse()
    info = data['info']
    if stage == 'G1':
        feedback = info.get('problems')
    else:
        observation = info.get('writer_observation')
        if (not isinstance(observation, dict) or set(observation) != {'feedback', 'bench_workers'} or
                type(observation['bench_workers']) is not int or observation['bench_workers'] < 1): refuse()
        feedback = observation['feedback']
    if not isinstance(feedback, list) or not feedback or any(not isinstance(p, str) or not p for p in feedback): refuse()
    return copy.deepcopy(feedback)


class Records:
    def __init__(self, c, r, row=None, *, observation_id=None, round_number=None, expected_versions=None):
        self.c, self.r, self.row = c, r, row
        self.expected_versions = copy.deepcopy(expected_versions)
        if row is not None:
            if observation_id is not None or round_number is not None: raise ValueError('two record owners')
            self.root = c.work / 'extension-package' / str(row['extension_id'])
            self.operation_id, self.round_number = row['writer_operation_id'], row['round']
            self.completed = row['outcome'] is not None
        else:
            from diagnosis import _uuid4
            if not _uuid4(observation_id) or type(round_number) is not int or round_number < 0:
                raise ValueError('invalid observation owner')
            self.root = c.work / 'entry-records' / observation_id
            self.operation_id, self.round_number, self.completed = None, round_number, False
        self.prepared = False
        self.observed = {}

    def version(self, stage):
        if stage == 'saved-cheats':
            return extensions.digest(dict(kind=stage,
                g6=gate_state.scientific_version(self.c, 'G6', self.r.BENCH),
                source=gate_state.source_inputs('early_cheat_check')))
        return (self.expected_versions[stage] if self.expected_versions is not None else
                gate_state.scientific_version(self.c, stage, self.r.BENCH))

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
                    data['writer_operation_id'] != self.operation_id or
                    type(data['round']) is not int or data['round'] != self.round_number or
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
            if check_version and data['scientific_version'] != self.version(stage):
                refuse('extension_snapshot_changed' if self.expected_versions is not None else 'extension_comparison_pending')
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
                      else gate_state.inputs(c, 'G6' if stage == 'saved-cheats' else stage, r.BENCH))
            if stage == 'saved-cheats':
                inputs.update(kind=stage, sample_source=gate_state.source_inputs('early_cheat_check'))
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
            data = dict(schema_version=1, writer_operation_id=self.operation_id,
                round=self.round_number, case_sha256=r.case_hash(c),
                scientific_version=self.version(stage), ok=ok,
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
        old = self.load(stage)
        if old is not None and stage != 'G3':
            self.restore(stage, old)
            return old['ok'], old['info']
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

    def writer_g1(self, c, invoke):
        """Retain the actual post-writer rejection, never an early pass."""
        old = self.load('G1')
        if old is not None:
            if old['ok'] is not False: refuse()
            self.restore('G1', old)
            return old['ok'], old['info']
        before = {k: gate_state.digest(p) for k, p in gate_state.inventory(c, self.r.BENCH).items()}
        card, case = project(c.card), self.r.case_hash(c)
        ok, info = invoke()
        if (ok is False and not comparison._pending(ok, info) and
                isinstance(info.get('problems'), list) and info['problems'] and
                all(isinstance(p, str) and p for p in info['problems'])):
            if self.r.case_hash(c) != case: refuse()
            self.save('G1', ok, info, before, card)
        return ok, info

    def replay_writer_early(self):
        stages = ('G15', 'G3', 'G4', 'G5', 'saved-cheats')
        found = [stage for stage in stages if (self.root / stage / 'record.json').exists()
                 or (self.root / stage / 'record.json').is_symlink()]
        if not found: return None
        if len(found) != 1 or (self.root / 'G1/record.json').exists() or (self.root / 'G1/record.json').is_symlink():
            refuse()
        c, stage = self.c, found[0]
        receipt = extensions.writer_receipt(c)
        if (not isinstance(receipt, dict) or receipt.get('actor') != 'writer' or
                receipt.get('phase') not in ('completed', 'validated') or
                receipt.get('repair_pending') is not False or receipt.get('output_sha256') != self.r.case_hash(c)):
            refuse()
        probe = copy.copy(c)
        probe.args, probe.card = copy.deepcopy(c.args), copy.deepcopy(c.card)
        reader = Records(probe, self.r, self.row)
        data = reader.load(stage, check_version=False)
        feedback = writer_feedback(stage, data)
        observation = data['info']['writer_observation']
        probe.args.bench_workers = observation['bench_workers']
        data = reader.load(stage)
        self.restore(stage, data)
        c.early = {}
        if hasattr(c, 'early_hash'): del c.early_hash
        markers = c.card.setdefault('early_gates', {})
        if stage == 'saved-cheats':
            summary = data['info'].get('summary')
            if summary is None: markers.pop('saved_cheats', None)
            else: markers['saved_cheats'] = copy.deepcopy(summary)
        else:
            markers[stage] = {'ok': False, 'minutes': 0}  # replay, not execution time
        return feedback

    def writer_early(self, c):
        retained = self.replay_writer_early()
        if retained is not None: return retained
        before = {k: gate_state.digest(p) for k, p in gate_state.inventory(c, self.r.BENCH).items()}
        card, case = project(c.card), self.r.case_hash(c)
        def rejected(c, stage, info, problems):
            if comparison._pending(False, info): return
            if (stage not in ('G15', 'G3', 'G4', 'G5', 'saved-cheats') or
                    'writer_observation' in info or not isinstance(problems, list) or not problems or
                    any(not isinstance(p, str) or not p for p in problems) or
                    type(c.args.bench_workers) is not int or c.args.bench_workers < 1 or
                    self.r.case_hash(c) != case):
                refuse()
            detail = copy.deepcopy(info)
            detail['writer_observation'] = dict(feedback=copy.deepcopy(problems), bench_workers=c.args.bench_workers)
            self.save(stage, False, detail, before, card)
        return self.r.early_checks(c, on_rejection=rejected)

    def observe_gate(self, c, stage, invoke):
        """Observe ordinary execution without changing its verdict or retry policy."""
        self.observed[stage] = False
        try:
            before = {key: gate_state.digest(path) for key, path in gate_state.inventory(c, self.r.BENCH).items()}
            old_card, case = project(c.card), self.r.case_hash(c)
        except CAPTURE_ERRORS:
            before = None
        result = invoke()  # Execution exceptions belong only to the ordinary pipeline.
        if before is None: return result
        try:
            ok, info = result
            if comparison._pending(ok, info): return result
            if case != self.r.case_hash(c): return result
            self.save(stage, ok, info, before, old_card)
            self.observed[stage] = True
        except CAPTURE_ERRORS:
            # Even a failure after rename cannot authorize entry: no close marker.
            try: shutil.rmtree(self.root / stage)
            except OSError: pass
        return result

    def evidence(self, w, stage):
        data = self.load(stage)
        if data is None: return None
        return data['ok'], data['info'], list(data['support'])


def scientific_binding(binding):
    value = copy.deepcopy(binding)
    value['bench'].pop('seed', None)
    for key in ('bench_workers', 'concurrent_roles'):
        value['bench']['settings'].pop(key, None)
    return value


def stress(c, r, records):
    retained = records.load('stress')
    if retained is not None: return retained
    if records.completed: refuse('extension_outcome_changed')
    receipt = extensions._writer_json(c.work / 'attack-state.json', c.work)
    report = c.work / 'attacks' / f"round-{records.row['round']}.json"
    completed = receipt.get('review_completed', {})
    if (receipt.get('actor') != 'stress_tester' or receipt.get('phase') != 'validated' or
            receipt.get('review_pending') is not False or
            receipt.get('round') != records.row['round'] or receipt.get('report') != report.name or
            receipt.get('round_limit') != records.row['round'] or not report.is_file() or
            completed.get('attempt') != receipt.get('review_attempt') or
            completed.get('binding') != hashlib.sha256(json.dumps(receipt.get('binding'), sort_keys=True).encode()).hexdigest() or
            completed.get('report_sha256') != gate_state.digest(report)):
        refuse('extension_execution_pending')
    # Match scientific_version's execution-only exclusions at the pre-G3 seam.
    if scientific_binding(receipt['binding']) != scientific_binding(r.attack_binding(c)):
        refuse('extension_comparison_pending')
    result = r.attack_report(report)
    if result is None: refuse()
    findings = [item for item in r.freshness_only_clearance(result)['blocking']
                if item.strip().lower() != 'review incomplete']
    if not findings and (result.get('freshness_review') or result.get('freshness_review_malformed')):
        from late_recovery import cleared_stress
        try: result, _ = cleared_stress(c, receipt, report, result)
        except (OSError, ValueError, KeyError, TypeError): refuse('extension_execution_pending')
    if not findings and (not result['complete'] or result['blocking'] or result['unfinished_validation']
                         or r.attack_diagnostic_unfinished(c, records.row['round'])):
        refuse('extension_execution_pending')
    ok = not findings
    if ok and receipt.get('next_phase') != 'extension_comparison': refuse()
    if not ok and not (receipt.get('exhausted') is True and receipt.get('stop_reason') == 'rounds_exhausted'):
        refuse()
    c.card['stress_review'] = {'status': 'completed', 'round': records.row['round']}
    return records.save('stress', ok, result, {}, project(c.card))


def unchanged_receipt(c, r, row, receipt):
    return (isinstance(receipt, dict) and receipt.get('actor') == 'writer' and
        receipt.get('phase') == 'completed' and receipt.get('repair_pending') is False and
        receipt.get('next_phase') == 'G1' and type(receipt.get('repair_requested')) is bool and
        type(receipt.get('round')) is int and receipt['round'] == row['round'] and
        type(receipt.get('round_limit')) is int and receipt['round_limit'] == row['round'] and
        type(receipt.get('extension_id')) is int and receipt['extension_id'] == row['extension_id'] and
        receipt.get('operation_id') == row['writer_operation_id'] and
        receipt.get('before_repair_sha256') == receipt.get('output_sha256') == r.case_hash(c))


def terminal_name(row):
    return f"extension-terminal/{row['extension_id']}.json"


def unchanged_outcome(c, r, row):
    """Verify immutable no-change proof without reopening writer or gate work."""
    outcome, entry = row['outcome'], row['entry']
    name = terminal_name(row)
    if outcome is None or name not in outcome['evidence']: return False
    try:
        for phase in ('entry', 'outcome'):
            extensions._verify_case(c, row['extension_id'], phase, row[phase])
        root = c.work / 'extension-snapshots' / str(row['extension_id']) / 'outcome'
        proof = extensions._writer_json(root / 'evidence' / name, root)
        retained = copy.copy(c)
        retained.case = root / 'case'
        if (set(proof) != {'schema_version', 'kind', 'extension_id', 'writer_operation_id',
                          'round', 'entry_sha256', 'case_sha256', 'receipt'} or
                type(proof['schema_version']) is not int or proof['schema_version'] != 1 or
                proof['kind'] != 'unchanged_writer' or
                type(proof['extension_id']) is not int or type(proof['round']) is not int or
                any(proof[key] != row[key] for key in ('extension_id', 'round', 'writer_operation_id')) or
                proof['entry_sha256'] != extensions.digest(entry) or
                proof['case_sha256'] != entry['case_sha256'] or
                any(outcome[key] != entry[key] for key in ('case_sha256', 'stages', 'frontier')) or
                entry['frontier'] == len(entry['stages']) or name in entry['evidence'] or
                outcome['evidence'] != {**entry['evidence'], name: gate_state.digest(root / 'evidence' / name)} or
                not unchanged_receipt(retained, r, row, proof['receipt'])):
            refuse()
    except (OSError, ValueError, KeyError, TypeError):
        refuse()
    except BudgetError:
        refuse()
    return True


def complete_unchanged(c, r, row):
    receipt = extensions.writer_receipt(c)
    if not unchanged_receipt(c, r, row, receipt): return False
    entry = row['entry']
    if extensions.digest(extensions.tree(c.case)) != entry['case_sha256']:
        return False
    if entry['frontier'] == len(entry['stages']): refuse()
    extensions._verify_case(c, row['extension_id'], 'entry', entry)
    name = terminal_name(row)
    if name in entry['evidence']: refuse()
    with tempfile.TemporaryDirectory(prefix='unbug-terminal-') as directory:
        root = Path(directory)
        source = c.work / 'extension-snapshots' / str(row['extension_id']) / 'entry/evidence'
        extensions._save_evidence(source, root, entry)
        proof = dict(schema_version=1, kind='unchanged_writer', extension_id=row['extension_id'],
            writer_operation_id=row['writer_operation_id'], round=row['round'],
            entry_sha256=extensions.digest(entry), case_sha256=entry['case_sha256'], receipt=receipt)
        (root / name).parent.mkdir(parents=True)
        atomic_json(root / name, proof)
        outcome = copy.deepcopy(entry)
        outcome['source_generation'] = job_authority.for_case(c).source_generation
        outcome['evidence'][name] = gate_state.digest(root / name)
        extensions.complete(c, outcome, evidence_root=root)
    return True


def stop_unchanged(c, row):
    entry = row['entry']
    for key in ('failed_gate', 'failed_detail', 'infrastructure_gate'):
        c.card.pop(key, None)
    c.card['gates'] = {stage['stage']: stage['status'] for stage in entry['stages']
                       if stage['stage'] != 'stress' and stage['status'] in ('pass', 'fail')}
    c.card['gate_results'] = {}
    frontier = entry['stages'][entry['frontier']]
    if frontier['status'] == 'fail':
        c.card['failed_gate'] = frontier['stage']
        c.card['failed_detail'] = dict(unchanged_writer=True,
            entry_sha256=extensions.digest(entry), retained_stage=frontier['stage'])
    c.card['stress_review'] = dict(status='not_run', reason='unchanged_writer')
    raise BudgetError('extension_incomplete')


def completed_route(c, row):
    """Validate package proof before routing a committed outcome's lagging card."""
    import run as r
    if unchanged_outcome(c, r, row): return
    import extension_public_match as public
    if public.verified(c, r, row): return
    import extension_writer_rejection as rejection
    if rejection.verified(c, r, row): return
    data = Records(c, r, row).load('stress', check_version=False)
    if data is None: refuse('extension_outcome_changed')


def run(c, r, previous, number):
    authority = job_authority.for_case(c)
    history = extensions.read(c)
    if type(number) is not int or not history or history[-1]['extension_id'] != number:
        refuse('extension_history_invalid')
    row = history[-1]
    if unchanged_outcome(c, r, row):
        if extensions.digest(extensions.tree(c.case)) != row['entry']['case_sha256']: refuse()
        stop_unchanged(c, row)
    import extension_public_match as public
    if public.verified(c, r, row):
        if extensions.digest(extensions.tree(c.case)) != row['outcome']['case_sha256']: refuse()
        public.stop(c, row)
    import extension_writer_rejection as rejection
    if rejection.verified(c, r, row):
        if extensions.digest(extensions.tree(c.case)) != row['outcome']['case_sha256']: refuse()
        rejection.stop(c, row)
    records = Records(c, r, row)
    if not records.completed and records.load('stress') is None:
        if complete_unchanged(c, r, row): stop_unchanged(c, row)
        if public.complete(c, r, row): public.stop(c, extensions.read(c)[-1])
        if rejection.complete(c, r, row): rejection.stop(c, extensions.read(c)[-1])
        try:
            with public.capture(c, r, row):
                r.write_and_attack(c, previous, extension_id=number,
                    writer_g1=lambda c: records.writer_g1(c, lambda: r.g1(c)),
                    writer_early=records.writer_early)
        except BudgetError as error:
            if str(error) == 'freshness_public_match':
                if public.complete(c, r, row): public.stop(c, extensions.read(c)[-1])
                raise
            if str(error) == 'stress_review_unresolved:unchanged_repair':
                if complete_unchanged(c, r, row): stop_unchanged(c, row)
                raise
            if str(error) == 'stress_review_unresolved:rounds_exhausted':
                if rejection.complete(c, r, row): rejection.stop(c, extensions.read(c)[-1])
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


CAPTURE_ERRORS = (BudgetError, InvalidInfra, OSError, ValueError, KeyError, TypeError)
EVIDENCE_STOPS = {'extension_reservation_mismatch', 'extension_snapshot_changed', 'extension_comparison_pending'}


def observation_enabled(c):
    import batch_service
    import model_runtime
    return (batch_service.DIAGNOSIS_ENABLED is True and model_runtime.factory_job(c)
            and not any(getattr(c.args, name, False) for name in
                        ('dry_run', 'rehearse_only', 'audit_fairness', 'late_gate_rehearsal'))
            and not hasattr(c, 'audit_source') and not hasattr(c, 'audit_gates'))


def safe_directory(c, path):
    if any(p.is_symlink() for p in (path, *path.parents) if p.is_relative_to(c.work)):
        refuse()


def observe_stress(c, r, records):
    """Only authenticated, completed clean stress can support a first entry."""
    records.observed['stress'] = False
    try:
        from late_recovery import gate_marker, cleared_stress
        receipt = extensions._writer_json(c.work / 'attack-state.json', c.work)
        number = receipt['round']
        if (type(number) is not int or number < 1 or number != records.round_number
                or receipt['report'] != f'round-{number}.json'
                or scientific_binding(receipt['binding']) != scientific_binding(r.attack_binding(c))
                or r.attack_diagnostic_unfinished(c, number)):
            return
        if gate_marker(c) is None: return
        report = c.work / 'attacks' / receipt['report']
        result = r.attack_report(report)
        if result.get('freshness_review') or result.get('freshness_review_malformed'):
            result, _ = cleared_stress(c, receipt, report, result)
        if not result['complete'] or result['blocking'] or result['unfinished_validation']: return
        before = {key: gate_state.digest(path) for key, path in gate_state.inventory(c, r.BENCH).items()}
        records.save('stress', True, result, before, project(c.card))
        records.observed['stress'] = True
    except CAPTURE_ERRORS:
        try: shutil.rmtree(records.root / 'stress')
        except OSError: pass


def observe(c, r, pipeline):
    """Capture one activated ordinary traversal; never replay its observations."""
    from diagnosis import _uuid4
    job_authority.for_case(c)
    number = c.card.get('builder_rounds', 0)
    records = Records(c, r, observation_id=str(uuid.uuid4()), round_number=number)
    safe_directory(c, records.root)
    records.root.mkdir(parents=True)
    identity = records.root.name
    pointer = dict(schema_version=1, observation_id=identity, round_number=number, case_sha256=r.case_hash(c))
    atomic_json(records.root.parent / 'current.json', pointer)
    for old in records.root.parent.iterdir():
        if old != records.root and _uuid4(old.name):
            safe_directory(c, old)
            shutil.rmtree(old)
    observe_stress(c, r, records)
    pipeline.overlap_reason = lambda c: 'entry evidence capture'
    result = pipeline.run(c, around_gate=records.observe_gate)
    if (records.observed and all(records.observed.values()) and not getattr(c, 'stopped', False)
            and 'infrastructure_gate' not in c.card):
        atomic_json(records.root / 'closed.json', dict(schema_version=1, observation_id=identity,
                                                      case_sha256=r.case_hash(c)))
    return result


def entry_prefix(owner, records, card):
    """Validate recorded evidence before treating a genuinely missing suffix as unreached."""
    stages = extensions.stages()
    live = extensions.tree(owner.case)
    without_freshness = lambda tree: {k: v for k, v in tree.items() if k != 'freshness.jsonl'}
    retained, hole, ended = [], None, False
    for index, stage in enumerate(stages):
        path = records.root / stage / 'record.json'
        present = path.exists() or path.is_symlink()
        if ended:
            if present: refuse()
            continue
        data = records.load(stage)
        if data is None:
            hole, ended = index, True
            continue
        root = records.root / stage / 'support/case'
        tree = extensions.tree(root)
        prefix = root.relative_to(owner.work).as_posix() + '/'
        bound = {k[len(prefix):]: v for k, v in data['support'].items() if k.startswith(prefix)}
        if tree != bound or without_freshness(tree) != without_freshness(live): refuse()
        if stage in ('G2', 'G8', 'G9') and tree.get('freshness.jsonl') != live.get('freshness.jsonl'): refuse()
        retained.append((stage, data, tree))
        if not data['ok']: ended = True
    if not retained or retained[0][0] != 'stress' or retained[0][1]['ok'] is not True: refuse()
    if retained[-1][2].get('freshness.jsonl') != live.get('freshness.jsonl'): refuse()
    if hole is not None and any(card.get('gates', {}).get(stage) in ('pass', 'fail') for stage in stages[hole:]): refuse()
    return hole


def entry(c, r):
    """Produce the first extension's entry from completed proof, without evaluation."""
    authority = job_authority.for_case(c)
    owner = copy.copy(c)
    owner.args, owner.card, owner.models = copy.deepcopy((c.args, c.card, c.models))
    if extensions.read(owner): return subsequent_entry(c, r)
    try:
        from diagnosis import _uuid4
        pointer = extensions._writer_json(owner.work / 'entry-records/current.json', owner.work)
        if (set(pointer) != {'schema_version', 'observation_id', 'round_number', 'case_sha256'}
                or type(pointer['schema_version']) is not int or pointer['schema_version'] != 1
                or not _uuid4(pointer['observation_id']) or type(pointer['round_number']) is not int
                or pointer['round_number'] != owner.card.get('builder_rounds', 0)
                or pointer['case_sha256'] != r.case_hash(owner)):
            refuse()
        records = Records(owner, r, observation_id=pointer['observation_id'], round_number=pointer['round_number'])
        close_path = records.root / 'closed.json'
        if close_path.exists() or close_path.is_symlink():
            closed = extensions._writer_json(close_path, owner.work)
            if (type(closed.get('schema_version')) is not int or
                    closed != {k: pointer[k] for k in ('schema_version', 'observation_id', 'case_sha256')}): refuse()
        records.load('G3')  # Restore workers on the copy before pinning the vector.
        hole = entry_prefix(owner, records, getattr(c, 'checkpoint_card', c.card))
        versions = comparison._versions(workspace(owner, r))
        for name in ('comparison-receipts', 'comparison-support'):
            target = owner.work / name
            safe_directory(owner, target)
            if target.exists(): shutil.rmtree(target)
        snapshot = comparison.snapshot(workspace(owner, r), authority.source_generation, records.evidence, versions=versions)
        if hole is not None:
            pending = [i for i, stage in enumerate(snapshot['stages']) if stage['status'] == 'pending']
            if pending != [hole]: refuse()
            stage = snapshot['stages'][hole]
            if stage['binding_sha256'] is not None or stage['evidence_sha256'] is not None: refuse()
            stage['status'] = 'unreached'
            extensions.validate_snapshot(snapshot)
        if snapshot['stages'][0]['status'] != 'pass' or any(row['status'] == 'pending' for row in snapshot['stages']):
            refuse('extension_comparison_pending')
        return snapshot
    except BudgetError as error:
        if str(error) not in EVIDENCE_STOPS: raise
        refuse('extension_comparison_pending')
    except (OSError, ValueError, KeyError, TypeError, comparison._Changed):
        refuse('extension_comparison_pending')


def subsequent_entry(c, r):
    """The sole current-version producer, before any subsequent writer admission."""
    import diagnosis
    import gate_attempt
    from extension_evaluator import Evaluator, EXECUTION
    authority = job_authority.for_case(c)
    history = extensions.read(c)
    state = diagnosis._state(c.card, extensions.public(history))
    if not state or state['status'] != 'completed' or state['outcome'] != 'close_to_passing':
        refuse('extension_diagnosis_required')
    if not history or history[-1]['outcome'] is None: refuse('extension_already_active')
    if len(history) >= extensions.LIMIT: refuse('retired_extension_limit')
    if any(row['exhaustion_id'] == state['exhaustion_id'] for row in history):
        refuse('extension_diagnosis_already_used')
    row = history[-1]
    if extensions.digest(extensions.tree(c.case)) != row['outcome']['case_sha256']: refuse()
    if unchanged_outcome(c, r, row): refuse('retired_no_progress')
    import extension_public_match as public
    if public.verified(c, r, row): refuse('retired_no_progress')
    import extension_writer_rejection as rejection
    if rejection.verified(c, r, row): refuse('retired_no_progress')
    number = row['extension_id']
    def selected():
        pair, valid, retained = comparison.current_pair(c, number, r.BENCH, execution=EXECUTION)
        if pair is not None and retained and not valid: refuse()
        return pair if valid else None
    def result(pair):
        progress = extensions.progress(pair['entry'], pair['outcome'])
        if progress != 'progress': refuse('retired_no_progress')
        value = copy.deepcopy(pair['outcome'])
        value['source_generation'] = authority.source_generation
        return value
    pair = selected()
    if pair is not None: return result(pair)
    versions = comparison._versions(workspace(c, r))
    evaluator = Evaluator(c, r, number, versions)
    missing = object()
    previous = {key: c.card.get(key, missing) for key in ('status', 'terminal_stop')}
    c.card.update(status='stopped', terminal_stop='runner_error:comparison_in_progress', failed_gate=None)
    for key in ('failed_detail', 'infrastructure_gate'): c.card.pop(key, None)
    evaluator.root.mkdir(parents=True, exist_ok=True)
    def invoke():
        with evaluator:
            status = comparison.compare(c, number, r.BENCH, evaluator, execution=EXECUTION)
            if status == 'pending':
                selected()  # Unverifiable scored proof is an evidence stop, not another roll.
                raise InvalidInfra('comparison incomplete or version changed')
            return True, {'progress': status}
    def crash(error):
        atomic_json(evaluator.root / 'pair-crash.json',
                    {'error_type': type(error).__name__, 'message': str(error)})
    try:
        outcome = gate_attempt.execute(invoke,
            publish=lambda status, *args: r.public_progress(c, 'comparison', status),
            record_crash=crash, interruption=BudgetError, attempts=2,
            journal=evaluator.root / 'pair-attempts.json', identity={
                'operation': 'extension-comparison', 'identity': evaluator.identity, 'versions': versions})
        if outcome.crashed: evaluator.exhausted('stress', pair=True)
        pair = selected()
        if pair is None: raise InvalidInfra('completed comparison proof unavailable')
        value = result(pair)
        durable = evaluator.checkpoint(force=True)
        # Only a remotely durable completed pair permits scratch deletion.
        if durable:
            for phase in ('entry', 'outcome'):
                for source in (evaluator.root / phase / 'work/transcripts').glob('*'):
                    if source.is_file():
                        target = c.work / 'transcripts' / (evaluator.identity + '-' + phase + '-' + source.name)
                        target.parent.mkdir(exist_ok=True)
                        shutil.copyfile(source, target)
            shutil.rmtree(evaluator.root)
        for key, old in previous.items():
            if old is missing: c.card.pop(key, None)
            else: c.card[key] = old
        return value
    finally:
        getattr(c, 'early', {}).pop('G3', None)
        for key in PREPARATION: c.card.pop(key, None)
        c.__dict__.pop('prepared_factory_slots', None)
