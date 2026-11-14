"""One evidence-bound diagnosis; the engine owns all retry and extension policy.

Runtime seam: runner.invoke_diagnosis(c, *, model, prompt, inputs, output) -> bytes.
It must invoke the existing accounted model runtime in the isolated diagnosis
pilot, expose only inputs read-only, collect result.json, and dispose the pilot
even on failure. It receives no scope keys. No legacy dispatch authority applies.
"""
import json
from pathlib import Path
import shutil
import tempfile
import traceback

import diagnosis as scientific
import diagnosis_dispatch
import extensions
from budget import BudgetError
from extension_package import writer_feedback
from registry import atomic_json
from durable.artifacts import scope_for
from durable.contract import (ArtifactKind, Outcome, StepKind, StepResult, Usage,
                              Verdict, check_result_for)
from durable import worker_step


def _feedback(c, runner):
    # Preserve the existing writer information wall: diagnosis prose never becomes
    # repair instructions. Early gate observations already have a narrow extractor.
    stage = c.card.get('failed_gate')
    detail = c.card.get('failed_detail')
    if isinstance(detail, dict) and detail.get('ok') is False:
        problems = writer_feedback(stage, detail)
    else:
        problems = runner.writer_feedback(c, c.card) or []
    report = None
    state = runner.jload(c.work / 'attack-state.json', {})
    name = state.get('report')
    if name is not None and (state.get('repair_pending') or state.get('awaiting_stress')):
        # A writer round wrote this receipt, and it names the report of the stress round that
        # follows it, which does not exist yet. The report that round was repairing is the one its
        # own feedback named (run._feedback_input keeps it). Before this, every close_to_passing
        # verdict on a case stopped in a writer step raised "missing stress report" after the paid
        # diagnosis (f46dac-5 and 18681d-f2 on 10 November, diagnosis:processing_failed).
        given = runner.jload(c.work / 'engine-feedback.json', None)
        name = given.get('attack_report') if isinstance(given, dict) else None
    if name is not None:
        import re
        if not isinstance(name, str) or not re.fullmatch(r'round-[0-9]+(?:-writer)?\.json', name):
            raise ValueError('invalid stress report')
        report = c.work / 'attacks' / name
        if not report.is_file(): raise ValueError('missing stress report')
    return runner._feedback('diagnosis', problems, report)


# A step whose last attempts all stopped on this many identical infra reasons is a factory bug.
REPEATED_INFRA_STOPS = 3
_NOT_FAULTS = ('infra:paused', 'infra:deadline')   # policy.PAUSE_REASONS and DEADLINE_REASON
# Infra stops the case itself can cause: a flagged public hit no reviewer settles, or search rows with
# real defects (an expired or unretrieved row stops infra:freshness_refresh_stalled instead). The agent
# judges these.
_CASE_CAUSED = ('infra:freshness_review_unavailable', 'infra:freshness_evidence_unavailable',
                'infra:freshness_unresolved')


def repeated_infra_stop(history):
    """The engine history's diagnosed step (its last row) when its last REPEATED_INFRA_STOPS infra
    attempts all stopped on one reason and none of its attempts reached a gate verdict: the step cannot
    run, whatever the case is like. None otherwise, and for a reason the case can cause (_CASE_CAUSED).
    f46dac-5-1 (11-14 November) stopped every writer round on expired freshness rows with its gates
    passing; the diagnosis agent called it close_to_passing and policy retired it, as an extension
    needs progress."""
    rows = [h for h in history if isinstance(h, dict)] if isinstance(history, list) else []
    if not rows: return None
    last = rows[-1]
    mine = [h for h in rows if h.get('seq') == last.get('seq') and h.get('step') == last.get('step')]
    if any(h.get('outcome') in (Outcome.GATE_FAILED.value, Outcome.OK.value) for h in mine): return None
    infra = [h.get('reason') for h in mine
             if h.get('outcome') == Outcome.INFRA_ERROR.value and h.get('reason') not in _NOT_FAULTS]
    tail = infra[-REPEATED_INFRA_STOPS:]
    if (last.get('outcome') == Outcome.INFRA_ERROR.value and len(tail) == REPEATED_INFRA_STOPS
            and len(set(tail)) == 1 and isinstance(tail[0], str) and tail[0] and tail[0] not in _CASE_CAUSED):
        return last.get('step'), tail[0]
    return None


def _history(evidence):
    """The engine's stop history: the last evidence item that is a JSON list (engine.diagnose)."""
    for ref, raw in reversed(evidence):
        if ref.kind is ArtifactKind.DIAGNOSTIC:
            try: value = json.loads(raw)
            except ValueError: continue
            if isinstance(value, list): return value
    return None


def run(worker, step_input, keys):
    """Return a contract result and encrypted blobs without scheduling more work."""
    outputs, c, before = {}, None, None
    usage = Usage()
    sealer = runner = None

    def seal(kind, raw):
        scope = scope_for(kind, step_input.case_id, step_input.batch_id)
        ref, encrypted = sealer.seal(keys[scope], kind, raw)
        outputs[worker_step.blob_name(ref)] = encrypted
        return ref

    def opened(ref):
        scope = scope_for(ref.kind, step_input.case_id, step_input.batch_id)
        return worker.open_blob(sealer, keys[scope], ref)

    def account():
        if before is not None:
            return worker_step.usage_since(before, c.ledger, step_input.money_ceiling_usd_micros)
        return Usage()

    try:
        if step_input.step.kind is not StepKind.DIAGNOSIS:
            return StepResult(Outcome.INFRA_ERROR, 'diagnosis:wrong_step'), {}
        reason = worker.version_check(step_input)
        if reason: return StepResult(Outcome.INFRA_ERROR, reason), {}
        sealer = worker.sealer()
        snapshot = opened(step_input.snapshot)
        evidence = [(ref, opened(ref)) for ref in step_input.evidence]
        work = worker.home / 'work' / step_input.case_id
        worker_step.restore(snapshot, work)
        runner = worker.runner()
        c = runner.context_for_step(step_input, work)
        before = worker_step.ledger_totals(c.ledger)
        worker._save_baseline(step_input, c.ledger, before)
        if before["total"] is None:
            return StepResult(Outcome.INFRA_ERROR, "infra:usage_unknown"), {}
        worker.bind_checkpoint(step_input, c, sealer, keys[step_input.case_id], runner)
        from durable.checkpoints import directory, checkpoint
        saved_result = directory(c) / "diagnosis-result.json"
        invoke = getattr(runner, 'invoke_diagnosis', None)
        repeated = repeated_infra_stop(_history(evidence))
        if saved_result.is_file():
            result = json.loads(saved_result.read_text())
        elif repeated is not None:
            # Decided in code, not by the agent: no model call, the same report shape.
            step, reason = repeated
            result = {'schema_version': 1, 'case_id': c.case_id, 'checkpoint_sha256': step_input.snapshot.digest,
                      'outcome': Verdict.FACTORY_BUG.value, 'evidence': [],
                      'reason': f'the last {REPEATED_INFRA_STOPS} attempts of {step} all stopped {reason}',
                      'factory_bug': {'component': reason, 'reproducer': f'rerun {step} on this snapshot',
                                      'fix_required': f'make {step} finish or stop for a case reason'}}
            saved_result.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(saved_result, result)
            checkpoint(c)
        else:
            if invoke is None:
                return StepResult(Outcome.INFRA_ERROR, 'engine:diagnosis_unavailable'), {}
            model, _ = diagnosis_dispatch.reviewer(c)
            # A fresh immutable view of the authenticated snapshot, outside retained
            # work. No queued_inputs(), diagnosis_state, JobAuthority or legacy journal.
            with tempfile.TemporaryDirectory(prefix='diagnosis-', dir=worker.paths(step_input.idempotency_key)['attempt']) as tmp:
                root = Path(tmp) / 'inputs'
                scientific._input_inventory(work)  # reject links before copying
                shutil.copytree(work, root / 'work')
                shutil.copytree(c.case, root / 'case')
                (root / 'card.json').write_bytes((work / 'scorecard.json').read_bytes())
                ledger = Path(c.ledger)
                (root / 'ledger.json').write_bytes(ledger.read_bytes() if ledger.exists() else b'{}')
                source = Path(diagnosis_dispatch.__file__).parent
                for path in [*source.glob('*.py'), *source.glob('prompts/*.md')]:
                    target = root / 'source/factory' / path.relative_to(source)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(scientific._input_bytes(path, source))
                for ref, raw in evidence:
                    target = root / 'evidence' / worker_step.blob_name(ref)
                    target.parent.mkdir(exist_ok=True)
                    target.write_bytes(raw)
                inventory = scientific._input_inventory(root)
                generation = step_input.snapshot.digest
                output = Path(tmp) / 'output'
                output.mkdir()
                # The inventory itself stays out of the prompt: the prompt is one command-line
                # argument, and a round-3 case's inventory passed Linux's 128 KiB limit for one
                # (f46dac-2r and 22e434-3r, 9 November: OSError E2BIG before launch). The
                # reviewer lists and hashes the read-only inputs itself.
                context = dict(case_id=c.case_id, checkpoint_sha256=generation,
                               inputs=str(root), output=str(output / 'result.json'),
                               schema=scientific.RESULT_SCHEMA, file_count=len(inventory),
                               files_sha256=extensions.digest(inventory))
                templates, _ = diagnosis_dispatch.contract(root)
                text = templates[0]
                raw = invoke(c, model=model, prompt=text + '\nRun context (data):\n' +
                             json.dumps(context, sort_keys=True), inputs=root, output=output)
                usage = account()
                if not isinstance(raw, bytes) or len(raw) > diagnosis_dispatch.task.MAX_RESULT:
                    raise BudgetError('diagnosis_result_invalid')
                if extensions.digest(scientific._input_inventory(root)) != extensions.digest(inventory):
                    raise BudgetError('diagnosis_input_invalid')
                result = diagnosis_dispatch.validate(c, {'generation': generation}, root, raw)
            saved_result.parent.mkdir(parents=True, exist_ok=True)
            atomic_json(saved_result, result)
            checkpoint(c)
        usage = account()
        verdict = Verdict(result['outcome'])
        feedback = seal(ArtifactKind.WRITER_FEEDBACK, _feedback(c, runner)) if verdict is Verdict.CLOSE_TO_PASSING else None
        report = seal(ArtifactKind.DIAGNOSIS_REPORT, json.dumps(result, sort_keys=True).encode())
        # Retain only evidence in the snapshot; no scheduler state or gate mutation.
        c.card['engine_diagnosis'] = {'verdict': verdict.value}
        runner.update_case_budget(c)
        atomic_json(c.work / 'scorecard.json', c.card)
        updated = seal(ArtifactKind.CASE_SNAPSHOT, worker_step.snapshot_bytes(c, runner))
        answer = StepResult(Outcome.OK, 'diagnosis:completed', usage=usage,
                            snapshot=updated, verdict=verdict, report=report, feedback=feedback)
        check_result_for(step_input.step, answer)
        return answer, outputs
    except Exception as error:
        # Processing/sealing can fail after paid work. Re-read the ledger on every
        # failure, and leave the supervisor's baseline available for cancellation.
        usage = account()
        # An exception that is not a runner stop names its class, content-free, like any unknown
        # stop (classify.py RAW_STOP_PREFIX): on 10 November f46dac-5 and 18681d-f2 each paid for
        # diagnoses that ended "diagnosis:processing_failed" with the cause only in a sealed blob.
        from durable.classify import RAW_STOP_PREFIX, labelled, stop_label
        fields = dict(outcome=Outcome.INFRA_ERROR,
                      reason=labelled(RAW_STOP_PREFIX, stop_label(type(error).__name__)) or 'diagnosis:processing_failed')
        if isinstance(error, BudgetError):
            from model_router import ProviderWait
            translated = (runner.engine_provider_wait(c, error, now=worker.clock())
                          if c is not None and isinstance(error, ProviderWait)
                          else runner.engine_stop(c, str(error)) if c is not None else None)
            if translated is not None:
                fields = translated
            else:
                classified = worker.classifier()(str(error), step=StepKind.DIAGNOSIS, now=worker.clock())
                fields = dict(outcome=classified.outcome, reason=classified.reason, retry_at=classified.retry_at)
        if getattr(error, 'diagnosis_cleanup_failed', False) is True and fields['outcome'] is Outcome.INFRA_ERROR:
            # The pilot cleanup failed after this error. The record names the first error, so
            # the cleanup failure no longer hides it: "diagnosis:cf_<label>" (classify.py). A
            # provider wait or case limit keeps its own outcome; its pilot is rebuilt next time.
            from durable.classify import CLEANUP_PREFIX, labelled, stop_label
            label = stop_label(str(error) if isinstance(error, BudgetError) else type(error).__name__)
            fields = dict(outcome=Outcome.INFRA_ERROR,
                          reason=labelled(CLEANUP_PREFIX, label) or 'infra:diagnosis_cleanup_failed')
        if c is not None:
            # Every failure once the case is open seals the writer steps' diagnostic, not only a
            # provider wait: 43 of 49 failed diagnoses up to 11 November left none.
            try:
                fields['diagnostic'] = seal(ArtifactKind.DIAGNOSTIC, worker_step.diagnostic(
                    c, {**fields, 'stop': str(error), 'traceback': traceback.format_exc()}))
            except Exception:
                pass   # the failure result itself still stands
        return StepResult(**fields, usage=usage), outputs
