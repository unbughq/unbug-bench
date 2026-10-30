**FAIL**: 0 blockers, 2 majors, 4 nits. The fixes for all three design-3 majors and all four nits hold, and the earlier resolutions are still in place. Each major below is a crash-recovery point that this revision's cleanup and replay rules opened up and do not pin. Both are short text fixes, each with one test. I wrote, committed and ran nothing. The review text below is ready to save verbatim as `docs/reviews/stream-d-worker-dispatch-design-4.md`.

---

# Review: stream-d worker dispatch design 4 (diagnosis-only sub-increment). FAIL (0 blockers, 2 majors, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Scope:**
- `docs/designs/stream-d-worker-dispatch.md` at `1b1bfc52f494c1716126232012cbe5f203f48fe2` ("Define diagnosis cleanup and completed settlement transitions"), branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
- The queued-input addendum in `docs/designs/stream-d.md` (around lines 1430–1440). The diff since `ddbe031` adds `audit-bytes-*` to the orphan binding there.
- I left out the untracked `.stream-d-next/`.

**Read verbatim, with elephant responses:** `stream-d-worker-dispatch-design-1.md` (including its round-2 note), `-design-2.md` and `-design-3.md` (including the elephant's resolution and the stale-tree exception paragraph).

**Code checked for feasibility only:**
- `diagnosis.py`: `_trigger`, `_state`, `exhaustion`, `pending_projection`, `record_exhaustion`, `_finding_path`, `persist_factory_bug`, `restore_factory_bug`, `_input_inventory`, `queued_inputs`.
- `run.py`: `make_pilots`, and `model_operation_id` scoping at lines 334–363.
- `model_runtime.py:318`.

**Out of scope, as briefed:** design-1 B1, B2 and the extension parts of M5/M6 stay **accepted, open and explicitly unqualified**. The design still says so (lines 22–25 and 371–407). I do not score them as resolved and raise no finding against those sketches.

## Design-3 findings: disposition

- **M1 (helper lifecycle): resolved, with one new seam (Major 2).**
  - Mode comes from the last pending row's `kind`. A missing, nonpending or contradictory row returns `input_invalid` (lines 279–281).
  - `prepare` always removes and then rebuilds the tree. It runs once per logical row before `opencode`, never for A's internal retries (lines 280–283).
  - Collection and removal for one row finish before the next row is appended (lines 284–287).
  - `audit-bytes-*` is a distinct name and is in the orphan binding. Only a `raw-bytes-*` file referenced by a row's `raw_sha256` counts as an answer (lines 153–158, 308–312; stream-d.md 1435–1436).
  - `remove` runs in `finally` per call and at every exit. A failure stops as `runner_error:DiagnosisTaskCleanupError`, and no model call happens before cleanup succeeds (lines 315–319).
  - Reset is split from collect so the audit bytes are kept.
- **M2 (gate reach): resolved.**
  - The gate is read after settlement, `queued_inputs` and model-free replay. It is read before driver qualification, pilot creation, helper `prepare`, router exclusions, leases and reservations (lines 478–484).
  - It is read once per dispatch and not re-read inside A's retry loop (lines 494–495).
  - The false-gate tests patch `make_pilots`, `verify_selected_drivers` and the helper (lines 498–501).
- **The elephant's stale-tree exception keeps the boundary.**
  - A fresh false-gate entry makes no helper call.
  - With a stale tree, only collect and remove are allowed, as part of old-role cleanup. That cleanup is privileged work this slice already requires.
  - It creates no user, task, lease or reservation, and makes no inference (lines 319–323, 496–501).
  - It does not reopen design-3 M2. It enables no money and no role work. It closes a real plaintext-leftover risk.
- **M3 (completed settlement): resolved.**
  - The pending branch makes no `queued_inputs` call before the ACK (lines 85–88).
  - The completed branch loads only an existing manifest.
  - I confirmed in code that `queued_inputs` refuses to mint for a non-pending state: `state['status'] != 'pending'` leads to `'bound diagnosis lacks manifest'` (`diagnosis.py:565–567`). So "missing manifest refuses" and "no new snapshot" are enforced by existing code, not just asserted.
  - It replays model-free and re-emits the verified outcome stop. Each completed outcome is tested across two finalizations (lines 90–98, 543–545).
- **N1–N4: incorporated.**
  - Malformed-route retirement leaves the state pending, and re-entry re-detects it without a call (lines 223–225).
  - The exact map digest is defined (lines 300–302).
  - The gate is pinned to `batch_service` imported from `job_config.FACTORY` and read as a module attribute (lines 481–484).
  - The first paragraph names the new worker consumer (lines 15–16).
- **Earlier resolutions are intact:**
  - The re-mint fix is at the producer (lines 66–76). It is consistent with `record_exhaustion` (`diagnosis.py:117–124`).
  - `model_operation_id` is scoped per row. The existing `pending_call` pattern at `run.py:334–363` confirms the mechanism.
  - Repair-route pinning, the carry-forward allowlist, archival of all pilot identities, the env allowlists, the loopback permit, prompts and digests, the 64 KiB/96 KiB bounds and the relaunch-path statement are all unchanged.

The queued-input addendum in stream-d.md agrees with the dispatch text. I found no contradiction between the scope boundary, the stops table, the gate paragraph and the test list.

## Blockers

None.

## Majors

### Major 1. The transition from a completed journal row to `decision.json` is unpinned, so crash replay is left to the implementer

- **Where:** lines 160–186 (journal), 227–232 and 241–246 (decision write order), and 494–497 (with the gate false, "only retained model-free outcomes may be applied").
- **What is pinned:**
  - raw bytes are written before validation (line 150);
  - the order is decision, then finding, then public state (line 241);
  - unreferenced `raw-bytes-*` files are interrupted, never answers (line 157).
- **What is not pinned:** the order between setting a row's status to `valid`/`malformed` and writing `decision.json`, and what replay does in the state between them.
- **Crash between them:** the journal holds a `valid` row whose referenced `raw-bytes-*` is retained, there is no `decision.json`, and `diagnosis_state` is still pending. The implementer has to choose one of three things:
  - re-validate the referenced bytes against the frozen inputs and write `decision.json` model-free;
  - treat the row as interrupted and pay for another call;
  - refuse as input-invalid.
- **It also changes behaviour under the gate.** If deriving a decision from a valid row counts as "retained model-free replay", it runs while the gate is false. If it does not, the same card stops `diagnosis_pending`. The equivalent case for a `malformed` row with no repair row yet is a model call, so it needs the gate. That one is unambiguous, but it should be stated next to the valid-row case.
- **Required:**
  - Fix the order: retain the raw bytes, then mark the row `valid` or `malformed` with its digest, then write `decision.json` (valid only), then the finding, then public state.
  - State that a `valid` row with retained referenced bytes and no `decision.json` is completed model-free during replay, before the gate. It re-validates against the original frozen inputs root and writes the decision, and makes no lease or reservation.
  - A `valid` row whose referenced bytes are missing or fail validation is `diagnosis_input_invalid` (a mutated journal).
  - Test both outcomes, with the gate false, using the patched-helper/`make_pilots` harness that already exists.

### Major 2. An audit-only collect of a stale tree can turn a crash mid-`prepare` into a sticky `diagnosis_input_invalid`

- **Where:** lines 189–193 and 319–323 (fresh-entry orphan collect), 289–296 (the collect protocol, "Input-copy damage remains input-invalid"), 299–302 (`input_invalid` status and the `inputs_sha256` comparison), and the stops table row `diagnosis_input_invalid` ("no automatic reset").
- **The failure path:**
  1. The process dies while `prepare` is copying a judgment-mode `inputs/` (`prepare` always removes the old tree and rebuilds it, so this is a normal window).
  2. The next fresh entry runs the specified stale-tree cleanup: it kills the old UID, calls `collect`, and then calls `remove`.
  3. `collect` hashes the partial exposed copy, which does not match the manifest, and returns `status: input_invalid`.
  4. The design says only that this cleanup collect is "for audit only". It does not say whether that status is ignored. Line 296 suggests it becomes the terminal `diagnosis_input_invalid`.
- **Why it matters:** with that reading, a crash during plumbing permanently retires a case's diagnosis. That breaks target property 2 (an infrastructure failure is retried, never scored) and contradicts the slice's own rule that the exposed copy is disposable and validation uses the runner's frozen root (lines 127–128).
- **The same ambiguity applies to:**
  - the predecessor collect before `reset` (line 308);
  - a false-gate stale cleanup, where the outcome would differ again: `diagnosis_pending` versus `diagnosis_input_invalid`.
- **Required:**
  - State that orphan, stale-tree and predecessor collects are audit-only: their `status` and `inputs_sha256` are recorded with the audit bytes and never change diagnosis state or the stop.
  - Only the post-role collect, in the same process that received a successful `prepare` for that row, may produce `diagnosis_input_invalid` from an `inputs_sha256` mismatch.
  - Test: crash mid-`prepare` (a partial `inputs/` left on disk), then fresh entry. Expect audit collect, then remove, then the same exhaustion ID. With the gate false, the stop is `diagnosis_pending`. With the gate patched true, the same row is re-prepared.

## Nits

- **N1. Where malformed-route re-detection sits relative to the gate (lines 223–225 vs 494–497).**
  - Re-detection uses the verified journal plus `routes(model)` and makes no call, so it should sit in the model-free replay phase before the gate. Say so.
  - Otherwise a `retired_diagnosis_malformed` card re-entered while the gate is false (for example through a raised-budget resume) gets relabelled `diagnosis_pending`. That makes `exhaustion()` true again, and the projection turns from None to pending.
- **N2. Empty predecessor collect (line 308).**
  - On the first `before_attempt` of a freshly prepared row, the predecessor collect returns `missing` with an empty prefix.
  - Say that `missing` with zero bytes writes no `audit-bytes-*` file, so each row does not leave a stray `audit-bytes-e3b0…` file.
- **N3. Stale trees outside the current ID or dispatcher path.**
  - Stale cleanup is defined only for a dispatcher fresh entry, for `<case>/<current exhaustion_id>`.
  - Process death after a held or retired outcome is published but before the `finally` remove leaves a root:pilot 0440 copy that no later dispatcher entry cleans.
  - Either state that worker VMs are not reused across cases or batches, so the residue dies with the VM, or have the factored archival step remove every `/var/lib/unbug-diagnosis/<case>/*` tree. The runner can list them under the 0755 ancestors.
- **N4. Environment allowlist test.** Lines 331–345 define per-driver environment policy, but the test list (lines 526–547) has no direct assertion for it. Add one control per driver:
  - no cloud, restore, job-authority or judge key;
  - OpenCode carries exactly one provider key;
  - `OPENCODE_ENABLE_EXA` is absent;
  - Codex preserves only `CODEX_HOME,PATH`.

## Answers to the brief's focus areas

- **Contradictions.** None. The scope boundary, extension obligations, stops table, gate paragraph, cleanup paragraph and test list agree. The stream-d.md addendum matches.
- **Unsafe gaps.** Both majors are crash-recovery transitions:
  - one could cost a duplicate paid call or flip the outcome depending on gate state (Major 1);
  - one could wrongly make a plumbing crash a terminal case outcome (Major 2).

  Neither makes money reachable while the gate is false, and neither reaches a writer.
- **Activation boundary.**
  - `close_to_passing` and active extensions stop `extension_comparison_pending` with no writer.
  - `DIAGNOSIS_ENABLED` stays false, with no second flag.
  - The existing relaunch paths are acknowledged.
  - Fail-closed holds.
- **Readiness.** One focused revision away. Both majors are text pins plus one test each. A fresh goldfish should confirm before code is wired.

## Validation boundary

This is a design-readiness review only. No files were written, and no commits, merges, pushes, launches, cloud work, model calls, decryption, tests or suite runs were done. I make no claim about the 210eb39, 150-script or diff-24 results beyond what the review records state, and I saw no production change after those inputs. No Murphy row closes. `DIAGNOSIS_ENABLED` stays false, and A/B/E activation stays gated. Design-1 B1, B2 and the extension parts of M5/M6 stay accepted and open.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

All two majors and four nits accepted; none rejected. The publication order will explicitly put referenced raw bytes and valid/malformed journal status before the decision; valid-row replay validates and completes a missing decision before activation, while missing/invalid referenced bytes refuse. Audit-only stale/predecessor collections cannot classify the original inputs or change a stop, including a crash during prepare. Only a post-role collection following successful prepare in that process can enforce exposed-copy integrity. Malformed-route exhaustion is checked model-free before activation. Empty missing predecessor output creates no audit file. Old-role cleanup covers every task UUID for the current case, including terminal/non-dispatch resume paths. Direct per-driver environment controls are added. No implementation or runtime enablement is claimed; extension blockers remain open.

