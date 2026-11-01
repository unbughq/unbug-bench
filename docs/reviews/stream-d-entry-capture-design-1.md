**Verdict: BLOCK.** There are 2 blockers, 6 major findings and 4 nits. Nothing was edited. The worktree t3-4ac6b632 @6afceac contains only the untracked draft.

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md and implementation-readiness-standard.md. Target: `docs/designs/stream-d-entry-capture.md`.

## What holds up (no change needed)
- **The split can stand alone.** First entry only, refusing on any history (draft lines 84–88), is safe and fits lane 1's hold. Lane 1 calls `entry` only when there is no row, or for a completed row with a resolved pair; both stop as `extension_comparison_pending`. `diagnosis_dispatch.py` is untouched.
- **Entry never re-runs a gate or model.** `extension_compare.snapshot` with `previous=None` only calls the evaluator adapter (`extension_compare.py:185-194`). Using `records.evidence` as that adapter loads saved records and runs nothing. The version hashing calls `run.prompt`, which reads prompt text and makes no model call.
- **Writing the pointer first is crash-safe.** `registry.atomic_json` fsyncs both the file and its directory (`registry.py:18-30`). A pending stage inside snapshot stops it and leaves later stages unreached (`extension_compare.py:209-218`).
- **Requiring a stress pass matches `propose`,** which checks `stages[0] == pass` (`extensions.py:394`).
- **Generalising `Records` is the minimal choice.** It avoids a second evidence collector. Ordinary roots (`entry-records/<uuid>`) and package roots (`extension-package/<id>`) can't be confused, because `load` checks support paths against its own root (`extension_package.py:80`). A null `writer_operation_id` is fine: ordinary records never reach `writer_receipt`, `admit` or `run`.
- **No reroll from stale state.** Entry rebinds the G3 effective worker count before checking versions, as the package does (`extension_package.py:83-88`). This is needed because `dependency_files` includes `bin/factory_pool.py` only when workers ≠ 1 (`gate_state.py:113`).

## Blockers

**B1. Ordinary capture changes the ordinary retry and stop rules, and causes paid rerolls.**
Lines 39–41 and 78–80 install the package's `Records.capture` around ordinary gates and claim the existing stop labels are kept. The code does not keep them:
- `Records.save` raises `InvalidInfra` on any pending-shaped result (`extension_package.py:163`). G16 and G17 return `verdict_valid: False, review_inconclusive: True` when a review is inconclusive (`fairness.py:169-170, 194-195`). That shape is pending under `_pending` (`extension_compare.py:89-93`).
- `InvalidInfra` is a `RuntimeError` (`bin/run_validity.py:9`), not the pipeline's interruption type. So `gate_attempt.execute` retries it with `attempts=2` (`gate_pipeline.py:144-148`). The retry re-runs the paid fairness review. A second inconclusive result crashes and goes to `stop_infrastructure` (`infrastructure_exhausted`, `gate_pipeline.py:155-163`).
- Today, `validate_and_repair` handles `review_inconclusive` and `"error"` results by returning (`run.py:3028-3031`). Capture would turn them into rerolls and an infrastructure stop. Any result containing `error` would do the same.
- The package's `refuse()` raises `BudgetError`, which is the pipeline's interruption type (`gate_pipeline.py:147`). So these package refusals now stop ordinary cases with `extension_snapshot_changed`:
  - cache evidence vanished (`:136`)
  - a symlink in the sources (`:177`)
  - the target directory already exists (`:192`)
  - the case hash changed during the gate (`:207`)
  - a tampered record on load (`:91`)

Required fix: specify an ordinary capture mode.
- Call `invoke()` outside any new error handling, so money, provider and cancel errors propagate exactly as today.
- If the result is pending-shaped, or saving fails with any capture-side error (`BudgetError` from `refuse`, `InvalidInfra`, `OSError`, `ValueError`, `KeyError`, `TypeError`), write no record. Leave that stage pending and return the gate's `(ok, info)` unchanged.
- Add a test with a real G16 inconclusive result: it is evaluated once, ordinary `validate_and_repair` returns, and entry is pending.

**B2. Every live factory traversal is changed while activation stays false, and the condition for that is undefined.**
- Lines 45–48 run `observe` on every authenticated factory job. Lines 57–59 force serial G10 (`run.py:3008`; overlap logic at `gate_pipeline.py:176-187`).
- `batch_service.DIAGNOSIS_ENABLED` is `False` (`batch_service.py:21`), so nothing can consume an entry.
- Meanwhile every live case would lose the G10 overlap and pay a full inventory digest plus a case-tree copy per gate (`extension_package.py:139-140, 204`). It would also pick up the new failure modes from B1. That is a live scheduling and throughput change shipped under "activation stays false" (line 16).
- The trigger is not defined. "Authenticated factory job" could mean `model_runtime.factory_job` (`model_runtime.py:41-42`) or `job_authority.for_case`. There is also no rule for detecting rehearsal or audit runs; `sealed_audit.py:212` calls `run_gates`.

Decide one of these and test it:
- **(a)** Turn capture on with the same activation as diagnosis (preferred; YAGNI while off).
- **(b)** Don't serialise ordinary capture. The race the draft cites is the card/context projection being restored. Ordinary records are never replayed, and entry uses only `ok`, `info` and `support`. Under (b), ordinary capture must also skip the `restore` call on an in-process retry (`:200-203`).

Either way, give the exact predicate for the factory, dry-run, rehearsal and audit exclusions.

## Major

**M1. Old traversal roots grow every checkpoint without limit.**
- Every `run_gates` call (once per repair loop, `run.py:3022`) gets a new UUID root. Nothing deletes the old ones.
- Each stage copies the whole case tree plus its evidence.
- The seal tars the whole work directory, and `after_gate` checkpoints after every gate.

Fix: delete the superseded `entry-records/<uuid>` roots after the new pointer is durably published. This is safe because they are never reused, and it deletes rather than guards.

**M2. Entry changes `c.args`.**
`Records.load('G3')` sets `c.args.bench_workers` (`extension_package.py:86`). Lines 107–108 say entry mutates nothing, but lane 1 goes on into the writer, stress and the package with the changed value.

Decide whether entry restores the original args after the snapshot, or keeps the change deliberately (and why). Also state how versions for G3 and later are fixed when the traversal stopped before G3 (no G3 record), since entry then uses the current args.

**M3. The split leaves cases held forever, and part of it contradicts lane 1. Name these as deferred obligations and test them as pending, not retired.**
- **(a) Budget runs out mid-traversal.** This is a main route into diagnosis. It leaves a partial record set, so the case is permanently `extension_comparison_pending`.
- **(b) Rounds run out during stress, so gates are never reached.** The draft never records a stress failure (lines 73–74). Lane 1 (`stream-d-outcome-routes.md`, its "Shared writer request" section) expects a failed stress snapshot to retire through `propose` as `retired_no_progress`. Under this draft it holds as pending instead. Reconcile this with lane 1 explicitly, and add it to stream-d.md's list of remaining item-7 obligations.

**M4. Stress evidence is not fully checked.**
- `gate_marker` takes `attack['report']` as a path from the state file without validating it (`late_recovery.py:20`), and it does not bind the round. Require `report == f"round-{attack['round']}.json"`, `attack['round'] ==` the pointer round `== builder_rounds`, and call `attack_diagnostic_unfinished(c, attack['round'])`.
- The draft's catch list (lines 71–72) is incomplete. `gate_marker` raises `Refused`, a `ValueError` subclass (`carry_over.py:43,56`). `cleared_stress` can raise `KeyError` or `TypeError` on a malformed clearance (`late_recovery.py:72-73`).
- `mark_gates` already runs before `run_gates` (`run.py:3019-3021`). So state that stress capture adds no new way to raise, and list the exact exceptions it swallows.

**M5. Decisions still left to the implementer (zero-decision rule).**
- Test 4 says "refuse or rebind … as appropriate". Pick rebind: records are not tied to a generation, and entry stamps the current `job_authority.for_case(c).source_generation`. That matches `extensions.py:401` and lane 1 line 35. Then test exactly that.
- Say what the pointer round must equal: `c.card['builder_rounds']`.
- Name the safe reader for the pointer: `extensions._writer_json`, whose refusal label is `extension_reservation_mismatch`. Then decide whether that label gets mapped to pending.
- Name the UUID validator: `diagnosis._uuid4`.

**M6. The test plan is not concrete enough for the real-artifacts rule.**
Test 1 says "Real ordinary pipeline with G1 and saved G4/G5". It doesn't say how G2 (model), G3 (setup) and G6–G17 are supplied: which evaluators are substituted, and which saved practice files or checkpoint are used. Name the fixtures, reusing those in `tests/factory/test_stream_d_execution.py`. Also name each substituted output and its label.

## Nits (optional)
- Gate results reused from the early check or the cache take their `before` inventory after the early check has already written its files (`gate_pipeline.py:135-137` vs `extension_package.py:204`). So the G3 proof is just the case files plus `inputs.json`. State that this is accepted.
- The comparison receipts include the slot environment variable (`extension_compare.py:70-73`). So entry is only repeatable on the same slot. Tell lane 1 explicitly, for its interrupted-admission replay.
- `extensions.read` rewrites `c.card['extension_history']` (`extensions.py:160`). It's harmless, but it means entry is not strictly read-only.
- Heilmeier: the objective in lines 5–9 is jargon-heavy. Cost and timeline are present but thin.

**To pass:** fix B1 and B2. Then resolve M1–M5 in the text, plus M6's fixture list. After that, first-entry capture can safely stand alone as this split increment.


## Implementation disposition

All blockers and majors accepted. Binding amendments specify observational ordinary capture, an explicit completed-capture marker, activation and mode exclusions, root cleanup, copied-context entry, held partial-work obligations, exact stress/pointer validation, and fixture/transport boundaries. No implementation yet; fresh design review must verify these fixes.
