I'm returning **FAIL**: 0 blockers, 3 majors and 4 nits. The design-2 blocker is fixed, and so are all five design-2 majors and all six nits. What's left are three places where the implementer would still have to make a decision. All three sit in the areas you asked me to focus on: the root helper's lifecycle, how far the single gate reaches, and the settlement branch. Under the zero-decision rule in the implementation-readiness standard, those gaps fail the review even with no blocker. I wrote, committed and ran nothing, and I did no tests, suite runs, launches, cloud work or decryption. The text below is ready to save verbatim as `docs/reviews/stream-d-worker-dispatch-design-3.md`.

---

# Review: stream-d worker dispatch design 3 (diagnosis-only sub-increment). FAIL (0 blockers, 3 majors, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Scope:** `docs/designs/stream-d-worker-dispatch.md` at `ddbe031ec05c76641a04865c32e907775e6efeed`, branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. The diff since `d439a25` touches only the design and the design-2 review. I left out the untracked `.stream-d-next/`.

**Read verbatim, with elephant responses:** `stream-d-worker-dispatch-design-1.md` (including its round-2 revision note) and `stream-d-worker-dispatch-design-2.md`.

**Code checked for feasibility only:**
- `diagnosis.py`: `_trigger`, `_state`, `exhaustion`, `pending_projection`, `record_exhaustion`, `_finding_path`, `queued_inputs`
- `recovery.py`: `infrastructure_exhausted`, `RETRY`, `HOLDER_STOPS`
- `run.py`: main stop handlers ~3052–3080, finalization call at 2793, `resume_provider_wait`, `make_pilots`, `pilot_wall`, `c.work`/`case_id` derivation
- `gate_pipeline.stop_infrastructure`
- `batch_service`: `DIAGNOSIS_ENABLED`, `_enqueue` tail, `plan`, and its stdlib-only import chain
- `budget.py`: `require_case_budget`, `run_budgeted`, `shared_stop`, `resume_ledger`
- `model_runtime.case_budget_boundary`
- `launch_manifest.WORKER_GLOBS`
- `tests/factory/test_stream_d_runtime.py:235–255`, `test_stream_d_held.py`

**Out of scope, as briefed:** design-1 B1, B2 and the extension parts of M5/M6 stay **accepted, open and explicitly unqualified**. The design keeps them in "Extension implementation obligations (not ready for wiring)". I do not score them as resolved and raise no finding against those sketches.

## Design-2 findings: disposition

- **B1 (completed-state re-mint): resolved.**
  - `record_exhaustion` may replace a completed state only when `new_exhaustion` is true *and* `_trigger(card, terminal_stop, history)` passes on the literal current stop. The new state uses that literal stop.
  - This matches the producer. A real new infrastructure exhaustion always writes the literal `terminal_stop='infrastructure_exhausted'`, in both `gate_pipeline.stop_infrastructure` and the `InfrastructureExhausted` handler at `run.py:3069`. So a retained marker is never needed to recognise a genuine new event.
  - Dispatcher stops such as `extension_comparison_pending`, `money_wait`, `diagnosis_pending`, `provider_wait` and `runner_error:*` fail `_trigger`, so the ID is preserved even though `run.py:3059` sets `exhaustion_occurred` for every `BudgetError`.
  - The existing control at `test_stream_d_runtime.py:~251` (literal `extension_incomplete` mints a new ID) stays valid.
  - The test asked for (two real finalization resumes per stop, plus one distinct literal exhaustion) is enough.
- **M1: resolved.**
  - The pending row (with `invocations: []`) is written before `opencode`.
  - `c.model_operation_id` is scoped to the row and restored in `finally`.
  - Output is reset at every real `before_attempt`, and the stale tree is rebuilt on entry.
  - The completed call's route is the last journaled invocation's route.
  - The repair is pinned by excluding every other route (any pool on the same route is allowed), and both exclusions are restored.
- **M2: mostly resolved.**
  - The helper is named `factory/diagnosis_task.py`. It is covered by `WORKER_GLOBS`, so it is authenticated with the release.
  - The command is fixed, with case and UUID patterns and no path arguments. Roots are derived and fixed.
  - Reads are no-follow and nonblocking.
  - Output is capped at 64 KiB, and the response at 96 KiB. Base64 of 64 KiB is about 85.3 KiB, so it fits.
  - Missing, unsafe and oversized outputs count as malformed.
  - **Remaining:** the lifecycle (Major 1 below).
- **M3: resolved.**
  - The two prompt files are named.
  - `schema_sha256` and `input_sha256` are defined exactly.
  - Validation uses the original frozen root, and the exposed copy must hash identically.
  - Repair mode exposes no case.
- **M4: resolved.**
  - There is an exact carry-forward allowlist.
  - All pilot identities are killed, joined, unwalled, archived and removed before reconciliation and the new role.
- **M5: direction resolved; reach not pinned** (Major 2 below).
  - Reading the single existing `batch_service.DIAGNOSIS_ENABLED` is a sound fail-closed seam.
  - It adds no second flag, config field or authority.
  - Its import chain is stdlib-only and it ships in the same verified release.
  - Patching the module attribute in offline tests works, provided the code reads it live, as required ("do not cache").
  - It explicitly supersedes design-1 M7's "no worker consumer" claim, so there is no contradiction.
  - None of `diagnosis_pending`, `extension_comparison_pending` or `money_wait` is in `RETRY` or `HOLDER_STOPS`, so gate-false entries cannot loop on restart.
- **N1–N6: incorporated.**
  - The stress tester is in the family check.
  - Inserted loopback rules plus cancel/crash cleanup are specified.
  - Cost is stated: one bounded slot in eight, and twice the GATED_CLAUDE `max_usd`.
  - Paths and orphan tests are listed.
  - The `money_wait` row now covers pending work only.
  - The refactor is limited to pilot archival.

## Blockers

None.

## Majors

### Major 1. The root helper's lifecycle has unpinned transitions

- **Where:** "Role isolation", the helper and collect paragraphs, and "Diagnosis result and retry lifecycle" (reset/orphan text).

**a. Mode selection and the judgment→repair transition.**
- `prepare` takes only `<case> <exhaustion_id>`, and "judgment mode copies inputs, repair mode exposes no case/evidence copy".
- The design does not say how the helper picks the mode. The obvious source is the `kind` of the last pending journal row it reads as root, but that is not stated.
- It also does not say that a repair-mode `prepare` must first remove the judgment's existing `inputs/` subtree.
- As written, the judgment's inputs tree is still on disk when the repair runs, which contradicts "no case/evidence tree is exposed in repair mode".
- **Required:**
  - The mode comes from the last row's `kind`. Any mismatch is `input_invalid`.
  - `prepare` always runs `remove` and then rebuilds, so every logical call gets a freshly built tree.
  - Name exactly when `prepare` is called: once per logical journal row, before `opencode`.

**b. Where partial and orphan bytes go.**
- `reset` "collects the bounded partial output for private audit", and entry "collect[s] any bounded orphan output for audit only".
- Neither has a file name.
- If they are written as `raw-bytes-<sha>`, they become files the journal does not reference. The journal checks ("exact ... digest and ledger binding checks reject mutated journals") and the orphan-check extension then have to decide whether an unreferenced `raw-bytes-*` is legal or corruption (`diagnosis_input_invalid`).
- **Required:**
  - A distinct name for audit-only bytes, for example `audit-bytes-<sha>` under the same parent, listed in the orphan check.
  - A rule that only `raw-bytes-*` files referenced by a journal row's `raw_sha256` count as answers.

**c. When `remove` runs.**
- The design says bytes are persisted before deletion, and that the home is disposed of before any checkpoint.
- It does not say when the `/var/lib/unbug-diagnosis/<case>/<id>` tree is removed:
  - after each logical call?
  - at every dispatcher exit, including provider-wait, money-wait and gate-false stops?
  - and what happens if `remove` fails?
- **Required:**
  - `remove` runs in `finally` on every dispatcher exit, after the bytes are persisted.
  - A `remove` failure is an infrastructure stop.
  - Fresh entry still removes any leftover tree (already stated).

### Major 2. The single gate's reach before and after the check is not pinned

- **Where:** "Stops and current B boundary", the `DIAGNOSIS_ENABLED` paragraph.
- **What is pinned:** the gate is read "before any new diagnosis invocation or reservation".
- **What is not pinned:** where the check sits relative to the side-effecting steps between replay and the first reservation:
  - archived-role qualification (`verify_selected_drivers`);
  - `make_pilots(diagnosis=True)`;
  - the root helper's `prepare`;
  - the loopback permit.
- **Why it matters:** with the gate false, an implementer who checks late will:
  - create users;
  - run sudo prepare;
  - possibly fail driver qualification with an infrastructure stop instead of the specified `diagnosis_pending`.

  The same card then gets different stop labels depending on the worker image. Fail-closed should mean no role work at all.
- **Required:** the gate is read immediately after settlement, `queued_inputs` and model-free replay or outcome application, and before:
  - driver qualification;
  - pilot creation;
  - helper `prepare`;
  - any lease, router exclusion or reservation.

  With the gate false, the dispatcher may only do one of two things:
  - apply a model-free retained outcome;
  - stop `diagnosis_pending`, with no pilot or task tree created and no sudo beyond the already-required archival of the old pilots.

  Test that ordering: patch `make_pilots`, `verify_selected_drivers` and the helper to assert they are not called when the gate is false.
- **Also state:** the gate is not re-read inside A's internal retry loop. It is a release constant and cannot change mid-process. This avoids a pointless per-reservation hook.

### Major 3. The unknown-total settlement branch hard-codes `diagnosis_pending`, even for completed states

- **Where:** "Runner entry and settlement": "If unknown, settle and checkpoint `diagnosis_pending` without a model."
- **The failure path:**
  1. The diagnosis run itself can leave the total unknown. For example, a Claude invocation with no usage lands in `unpriced_invocations` (`budget.py:~1232`).
  2. It then completes `close_to_passing` and stops `extension_comparison_pending`, with the archived `infrastructure_gate.exhausted` marker carried forward under the allowlist.
  3. `exhaustion(card)` is then true, through `infrastructure_exhausted`.
  4. With the total unknown, `batch_service._enqueue` queues a `resume/.../settlement` request (`facts['exhaustion'] and unknown`), and an explicit same-owner resume reaches the same branch.
  5. That run settles and stops `diagnosis_pending` on a *completed* state.
- **What goes wrong:** `exhaustion()` then returns False, because a `diagnosis_pending` stop requires a pending state. The case loses its `extension_comparison_pending` label and carries a stop that contradicts its state.
  - The same applies to completed `factory_bug` and `not_converging` outcomes.
  - No money is spent, but the public lifecycle becomes inconsistent, and the extension controller would later have to guess.
- **Required:**
  - On unknown total, a pending state stops `diagnosis_pending`.
  - A completed state re-emits its outcome stop: `factory_bug_held`, `retired_not_converging` or `extension_comparison_pending`, applied model-free from the retained decision only after inputs are verified, or before verification if the label is derived from `diagnosis_state` alone (say which).
  - Add this case to the two-resume finalization test.

## Nits

- **N1. Diagnosis state on `retired_diagnosis_malformed`.**
  - `_state` allows completed outcomes only in `{factory_bug, close_to_passing, not_converging}`, so this stop must leave `diagnosis_state` pending.
  - Say so, and say that re-entry (for example a raised-budget explicit resume) re-detects route exhaustion from the journal without a model and stops again.
  - `exhaustion()` already excludes `retired*`, so the projection stays None.
- **N2. `inputs_sha256` definition.** "Canonical file-map digest of the exposed input copy" should name its exact relation to the manifest, for example `carry_over.digest(_input_inventory(exposed))`, which must equal `carry_over.digest(manifest['files'])`.
- **N3. The phrase "verified installed release" for the gate.** State that it means the `batch_service` module imported from `job_config.FACTORY` in the running worker, read as a module attribute (`batch_service.DIAGNOSIS_ENABLED is True`). It is not a file parse, and it is not a value copied into `c`.
- **N4. Wording.** The problem section still says "B's `DIAGNOSIS_ENABLED` stays false" without the new consumer. Add "and is now also read by the worker before diagnosis reservation (see Stops)", so a reader of the first paragraph does not think design-1 M7's "no worker consumer" claim still holds.

## Answers to the brief's focus areas

- **Contradictions.** None of substance.
  - The scope boundary, the extension obligations held open as unqualified, the stops table, the gate paragraph and the test list agree.
  - The only stale statement is the wording in N4.
  - The single-gate read explicitly supersedes the earlier claim that the worker had no consumer.
- **Root helper lifecycle.** The trust boundary is sound:
  - root ownership of the inputs;
  - fixed arguments with no paths;
  - derived roots and no-follow reads;
  - a bounded wire format;
  - no authority taken from result text.

  Note that the runner already has NOPASSWD sudo (`bin/hcloud-bake:32`), so the helper protects against the pilot, not against the runner. That is the right threat model. The gaps are the transitions: mode and inputs teardown, audit-byte naming against journal integrity, and when `remove` runs (Major 1).
- **Single-gate fail-closed behaviour.** The seam is correct, minimal and testable. It cannot loop on restart, because none of the gate-false stops is retryable. It needs its position pinned before any role or pilot side effect (Major 2).
- **Readiness of the constrained slice.** One focused revision away. All three majors are local text fixes with tests and no new mechanism. A fresh goldfish should confirm them before any code is wired.

## Validation boundary

This is a design-readiness review only. No files were written, and no commits, merges, pushes, launches, cloud work, model calls, decryption, tests or suite runs were done. I make no claim about the 210eb39 or 150-script full-suite results beyond what the review records state. No Murphy row closes. `DIAGNOSIS_ENABLED` stays false, and A/B/E activation stays gated. Design-1 B1, B2 and the extension parts of M5/M6 stay open.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

All three majors and four nits accepted; none rejected. The helper mode is derived from the last pending logical row, prepare removes/rebuilds on every logical call, audit-only bytes have their own names and orphan binding, and finally removal is explicit. The existing B gate is checked after model-free replay but before all role setup and read once per dispatch. Unknown-total pending state retains diagnosis_pending without a snapshot; completed state verifies its existing immutable inputs and decision/finding, reapplies the outcome model-free, and preserves its outcome stop through settlement. Malformed-route retirement leaves state pending and re-detects exhaustion without a call. Exact input-map digest/module-attribute definitions and tests are added. Extension design-1 blockers remain accepted and open.

The lifecycle and false-gate requirements intersect when a prior crash left a
task tree. Old-role cleanup may collect audit bytes and remove that existing tree
before the activation check, alongside old-pilot cleanup. It may not prepare or
reset a task, create a user, qualify a driver or infer. A fresh gate-false entry
calls no helper at all; the stale-tree test permits collect/remove only. This
explicit exception prevents leaving plaintext role copies behind on a disabled
resume while preserving the review's no-role-work intent. Reset collection is a
separate bounded collect operation so reset's empty response does not discard
the audit bytes. Each logical call removes its task before another row is
appended, avoiding a stale judgment/repair mode ambiguity.

