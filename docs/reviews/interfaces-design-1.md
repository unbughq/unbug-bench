# Goldfish review 1: docs/designs/interfaces.md

Reviewer: fresh Claude subagent, personas design_critic + implementation_readiness, Mode: REVIEW, read-only. Verbatim.

**Verdict: FAIL.** Seven of the eight findings below are BLOCKING. The design was reviewed against the design_critic and implementation_readiness personas, in REVIEW mode, without editing anything.

**Answers to your five questions**
- **Can each stream build to it without guessing?** No. A has to guess what the 60-second rule means (finding 7). D has no way to tell when the router has admitted a call (finding 6). B doesn't know where to read the record or how to avoid launching a case twice (findings 2 and 7).
- **Are ownership boundaries clear and non-overlapping?** No. `key_holder.py`, `restart.py` and `coordinator.py` each need changes from streams that don't own them, and several files have no owner at all (finding 4).
- **Is the provider-wait record enough to relaunch safely without double-counting?** No. The checkpoint field can't hold the value it describes (finding 1). The record has no ID, no marker that it has been handled, and nothing to show whether its usage was already charged (findings 2 and 3). There is also no limit on how many times a case can wait (finding 5).
- **Is the merge order sound?** The dependency order is fine. But it leaves a stretch where waits are written and nothing relaunches them (finding 8).
- **Is any Murphy row left without an owner?** No. Every row has a stream letter in the register. But rows 20 and 7 are assigned to different streams in the two documents (finding 4).

**Findings**

1. **BLOCKING, line 34 (with lines 25–26 and 63–65).** `checkpoint_sha256` can't hold the value it describes. The worker writes the record before it takes the checkpoint that contains the record, so the record can't contain that checkpoint's hash. Meanwhile `bind()` (`factory/batch.py:136-142`) only accepts the generation in the latest collected card (`sealed/<case>.scorecard.json`), which is that later checkpoint. So "that exact generation" on line 65 means a different checkpoint from the one in the record. **Fix:** define the field as the parent generation, and have B relaunch from the collected card's generation. Or delete the field.

2. **BLOCKING, lines 31–43 and 60–65.** B has no way to avoid relaunching the same case twice.
   - The record has no `wait_id` and no "handled" marker. A control-VM restart (row 51) or collecting the same stop twice would launch the same generation twice.
   - Nothing says who deletes or renames `provider_wait.json` after a resume. If the file is still there, every later checkpoint carries it and B starts another relaunch.
   - `key_holder.py:560` refuses a launch when concurrency is full. The contract doesn't say whether B queues it or drops it.
   - **Fix:** add `wait_id`. Key relaunches on (case, generation). Have the resumed worker move the file to `provider_waits/<wait_id>.json` before its first model call.

3. **BLOCKING, lines 39–52.** Usage from an interrupted call can be charged twice. `usage_known: true` gives no amount and no receipt or ledger reference. If the worker already booked the usage into the case budget before its checkpoint, D charging it again from receipts counts it twice. If it didn't book it, nothing says who does. **Fix:** add `call_id` (the receipt path) and `settled: bool`, and name the one place where settlement happens.

4. **BLOCKING, lines 11–15 and 17–18.** Ownership overlaps, gaps, and two conflicts with the Murphy register.
   - **`key_holder.py`** belongs to B. E's row 28 needs changes there (`:455`, `:541`, `:260`), and so does D's limit on holder recovery attempts (row 11 evidence, `:185`). Both E and D merge before B.
   - **`restart.py`** belongs to A, but D must exclude waits from restart counts there (row 11, `:57` and `:83`).
   - **`coordinator.py`:** A deletes its account scheduling. D must enforce the launch-action limit at `:225`. Nobody owns the rest of the file.
   - **No owner:** the model-call wrapper and the `provider_wait` stop reason in `run.py` (row 48 evidence, `run.py:237`), the checkpoint code (`durable_checkpoint.py`, `run_artifacts.py`), and `codex_login.py`.
   - **Register conflicts:** row 20 is A's in `murphy-register.md` but B's here (line 12). Row 7 is F's in the register but folded into B here.
   - Lines 17–18 allow a stream to edit another's file; they don't settle who owns it.

5. **BLOCKING, lines 61 and 70–77.** Nothing limits how often a case can wait. Waits use up none of the limits on lines 72–77, so the only stop is `batch_deadline`.
   - A condition that won't clear (402 with zero credit, a revoked Codex login, the router down for hours) loops through provision, checkpoint, retire and relaunch until the deadline.
   - Each loop costs a real VM, and that cost is charged nowhere.
   - What happens to the case at the deadline is not defined. Section 3 of `docs/ENGINEERING.md` forbids scoring it as a fail.
   - **Fix:** set a limit on waits per reason, put relaunch VM cost on the infra-waste line, and define an unscored stop such as `provider_wait_deadline`.

6. **BLOCKING, lines 79–83.** There is no defined way for the router to tell D's code that a call has been admitted. Today `run.py:1093` writes `repair_pending` just before `opencode()`, and admission happens inside that call.
   - D can't move the reservation "after admission" without an agreed function, return value or callback from A's `model_router.py`.
   - On resume, `run.py:972-973` stops with `interrupted_repair` whenever `repair_pending` is set. The contract doesn't say how resume tells a provider wait apart from a crash, or which receipt "the retained receipt" means.

7. **BLOCKING, lines 22, 36–38 and 60.** Wording A and B would have to guess at.
   - "Cannot … finish within 60 seconds", read literally, kills every writer round, which runs for hours. It should say the provider condition has lasted 60 seconds.
   - No default `retry_after` is given for `outage` or `router_unavailable`, which come with no retry header.
   - B "reads collected provider_wait stops", but the record sits inside the encrypted checkpoint and the public card carries only `terminal_stop`. The contract should say which fields appear in the public card, or that B decrypts the checkpoint with the restore key.
   - `key_holder.py:566` currently refuses checkpoint restores under the control identity. Changing that is a precondition for section 3 and should be named.

8. **NIT, lines 85–100.** The order is right as a dependency order: E first, and A before D. But between step 4 (A writes wait records) and step 6 (B relaunches them), any batch run on `factory-simplify` stops those cases with nothing to resume them. A will also have deleted the coordinator's account scheduling by then. Either keep A's record writer turned off until B merges, or state that no batches run between steps 4 and 6. This becomes BLOCKING if any batch does run in that window.

**FAIL**
