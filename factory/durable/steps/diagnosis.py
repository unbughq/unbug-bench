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
    if name is not None:
        import re
        if not isinstance(name, str) or not re.fullmatch(r'round-[0-9]+(?:-writer)?\.json', name):
            raise ValueError('invalid stress report')
        report = c.work / 'attacks' / name
        if not report.is_file(): raise ValueError('missing stress report')
    return runner._feedback('diagnosis', problems, report)


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
        if saved_result.is_file():
            result = json.loads(saved_result.read_text())
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
                context = dict(case_id=c.case_id, checkpoint_sha256=generation,
                               inputs=str(root), output=str(output / 'result.json'),
                               schema=scientific.RESULT_SCHEMA, files=inventory)
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
        fields = dict(outcome=Outcome.INFRA_ERROR, reason='diagnosis:processing_failed')
        if isinstance(error, BudgetError):
            translated = runner.engine_stop(c, str(error)) if c is not None else None
            if translated is not None:
                fields = translated
            else:
                classified = worker.classifier()(str(error), step=StepKind.DIAGNOSIS, now=worker.clock())
                fields = dict(outcome=classified.outcome, reason=classified.reason, retry_at=classified.retry_at)
        return StepResult(**fields, usage=usage), outputs
