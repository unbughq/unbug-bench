My verdict is **FAIL**: 0 blockers, 2 majors, 4 nits. The ordering of settlement, replay and the gate is right, and so are the design-5 refinements. The two majors are in how the enabled path labels failures and in how strong its tests are.

I made no changes in the worktree; its only untracked item is the excluded `.stream-d-next/`. I ran only offline focused tests and throwaway mutations in a scratch copy, and did not touch the full suite. The text below is ready to save as `docs/reviews/stream-d-diff-25.md`.

---

# Review: stream-d diff 25 (diagnosis-only worker dispatch). FAIL (0 blockers, 2 majors, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first, then the personas `zoom_out` and `implementation_readiness` and the standards `zoom-out-standard.md` and `implementation-readiness-standard.md`.

**Scope:**
- **Diff:** `449005ccc0c3a04d85ccf558cd381408fb73463b..dc7935f92cd589f5417edb25f9cb8df193a59e32`, branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
- **Reviewed against:** `docs/designs/stream-d-worker-dispatch.md` and the queued-input sections of `docs/designs/stream-d.md` (§"Queued diagnosis inputs", §"Queued input implementation boundary", and the new 6-line pointer).
- **Prior reviews read, with responses:** `stream-d-worker-dispatch-design-{1..5}.md`, `stream-d-diff-23.md` and `stream-d-diff-24.md`.
- **Excluded:** `.stream-d-next/`.

## What I ran

- **The 20 focused dispatch tests:** `tests.factory.test_stream_d_dispatch` on a `git archive` copy of `dc7935f`. All 20 passed in 15.7 s.
- **Mutation and probe runs:** in a scratch copy only, over `test_stream_d_dispatch`, `test_stream_d_inputs` and `test_stream_d_runtime` (70 tests). The results are cited below.
- **Not run:** the full suite (the parent is running it), and nothing live.

## Confirmed correct

**Entry and carry-forward**
- **Runner entry:** `run.py` runs `carry_context`, then `archive_pilot_state`, then `dispatch` straight after `job_config.install`. This is before `raised_limits`, `restore_gate_crash`, Compose, `pick_models` and `build`. The main-entry subprocess control forbids `sh`, `pick_models`, `build`, `validate_and_repair` and `make_pilots`, and reaches a published `diagnosis_pending`.
- **Carry-forward:** `CARRY` matches the design allowlist exactly. Archived roles and gates are copied before cleanup can fail.

**Settlement and the single B gate**
- **Order:** `job_authority.for_case`, then `resume_provider_wait`, then `reconcile_reservations`, then a check that no ledger row is active or pending.
- **Unknown total:** if the checkpoint total is unknown and the state is pending, the run stops at `diagnosis_pending` before `queued_inputs`. The mutation removing this stop was killed.
- **Gate position:** the gate is read as `batch_service.DIAGNOSIS_ENABLED is True`, live and once. The read comes after replay, outcome application and the model-free check for all-malformed routes. It comes before `verify_selected_drivers`, `make_pilots`, helper calls and leases. Mutations removing the gate or the pre-gate retirement check were both killed.

**Producer re-mint guard (design-2 B1)**
- `record_exhaustion` no longer turns a retained infrastructure marker into a new exhaustion when a state already exists.
- Reverting the producer to the old `infrastructure_exhausted(card)` line fails 3 of the 70 tests, so this is pinned. (`test_stream_d_runtime` carries the marker.)

**Immutable replay**
- The journal binds `input_sha256 = digest(manifest)` and `schema_sha256`.
- Each invocation must match a retained reservation's lease, operation, call name and family.
- Referenced `raw-bytes-*` files are re-hashed. A valid row with no decision completes model-free before the gate (tested).
- If a referenced raw answer is missing, the result is `diagnosis_input_invalid` (tested).

**Design-5 nits**
- **Canonical in-place prepare:** confirmed.
- **Per-case root `flock` on `<case>/.lock`:** cleanup skips only `.lock`, and a cross-process test exists.
- **Cleanup failure, then outcome replay:** the test exists.
- **Unsupported schema digest:** stops at `diagnosis_schema_wait` with the state unchanged. Templates are read from the frozen source as data and never executed. The mutation was killed.
- **Prior-ID audit:** writes `audit-<sha>.json` under that ID's directory.
- **Missing-manifest binding:** includes `attempts.json`, `decision.json`, `raw-bytes-*`, `audit-bytes-*` and `audit-*.json`. The mutation was killed.
- **Rebuild only after the gate:** confirmed.

**Lifecycle**
- Reset runs inside `before_attempt` (the mutation was killed).
- Remove runs in `finally` per row (the mutation was killed).
- The operation ID and `router_excluded` are scoped to each row and restored afterwards.

**Isolation**
- `make_pilots(diagnosis=True)` makes no config or auth copy, creates a 0700 home and a `.cache` directory, and opens no bench port.
- `diagnosis_environment` is an allowlist. Removing it was killed.
- OpenCode runs with Exa off and `webfetch`/`websearch` denied, and the base URL is dropped.
- The loopback rules are inserted at position 1 of the chain and removed on every exit.

**Scope**
- No new launcher or authority.
- `DIAGNOSIS_ENABLED` is still `False`.
- `close_to_passing` stops at `extension_comparison_pending`, and no writer path is reachable.

## Blockers

None.

## Majors

### M1. On the enabled path, any infrastructure exception becomes sticky `diagnosis_input_invalid`

- **Where:** `factory/diagnosis_dispatch.py` `dispatch()` lines 316–325. This is a catch-all for `ValueError`, `KeyError`, `TypeError`, `AttributeError` and `OSError` → `invalid(c)`. It wraps all of `_dispatch()`, including `verify_selected_drivers`, `invoke()`, the helper subprocess and `retain()`.
- **Why this breaks the design:**
  - `diagnosis_input_invalid` is in `INVALID`. Every later resume stops at entry (line 274), and the state is terminal with a None projection and "no automatic reset" (stops table, design line ~518).
  - The design keeps that label for input or history corruption. Only a post-role collect may raise `input_invalid`.
  - Cleanup and infrastructure failures are meant to be retryable `runner_error:*`.
  - ENGINEERING §3 says infrastructure failures are retried and never become case outcomes.
- **Evidence (scratch probes, gate patched true):**
  - `verify_selected_drivers` raising `ValueError('worker tool version mismatch: opencode')` (a wrong CLI in the image) gives `diagnosis_input_invalid`. The next resume also stops at `diagnosis_input_invalid`, with 0 calls, so it is permanent.
  - A nonzero exit from the helper `prepare` (`ValueError('task helper failed')`) gives `diagnosis_input_invalid`.
  - A helper failure at `reset` inside `before_attempt` gives `diagnosis_input_invalid`.
  - `OSError(ENOSPC)` while retaining `raw-bytes-*` gives `diagnosis_input_invalid`.
  - Before the gate, the same catch-all turns an `OSError` from `atomic_json` in `decision()` or `apply()` into the same terminal state.
- **Also masks tests:** with the explicit post-role integrity check removed (`if response['status'] == 'input_invalid' or response['inputs_sha256'] != expected: invalid(c)`), `test_helper_output_bounds_symlink_fifo_and_input_damage` still passes. It reaches the same label through a different exception.
- **Impact:** production cannot reach this while the gate is false, and it spends no money and reaches no writer. But the slice claims to implement and test the enabled path, and the first live image or disk problem would retire diagnoses as input corruption.
- **Required:**
  - Narrow the conversion to input or history verification: `queued_inputs`, `journal`, `replay`, `raw_answer`, and the explicit post-role collect check.
  - Let driver qualification, helper transport, `retain`/`atomic_json` I/O and runtime exceptions propagate to the existing `runner_error:<type>` handling with the same exhaustion ID.
  - Add one control per case above that asserts a retryable stop and an unchanged ID on the next resume.

### M2. Several design-required guards survive deletion

Each mutation below left all 70 focused tests passing.

| Guard deleted | Design obligation it was meant to prove |
| --- | --- |
| `replay`: `if result != retained: raise ValueError('decision differs from retained answer')` | "Retained decisions require their valid journal row and exact raw answer." No test tampers `decision.json` against the raw bytes. |
| `invoke`: repair-route pinning via `router_excluded` (` or (pinned is not None and route['route'] != pinned)`) | Design-2 M1 repair pinning. `test_schema_only_repair...` passes because the stub always picks the first route anyway. Exclude the first route for the judgment, or rotate the stub, so pinning is visible. |
| Post-role collect integrity check | See M1: the catch-all masks it. |
| `reviewer()`: `if len(set(families)) != len(families): raise ValueError('dependent reviewer')` | The test list names "family mismatch". No control has a reviewer in the same family as the writer, stress tester or strong calibrator. |
| `cleanup_tasks`: unknown task name → error (changed to `continue`) | Cleanup should refuse unknown names. Only `.lock` is exempt. |
| `model_runtime._invoke`: `diagnosis_loopback(...)` wiring (replaced by a null context) | The context manager is unit-tested in isolation, but nothing proves `_invoke` installs it around the gated Claude transport. |

**Required:** one small control per row that fails when its guard is deleted. Narrowing the OpenCode `--preserve-env` list also survives, but the environment is already filtered, so I treat that as defence in depth, not a finding.

## Nits

- **N1. Audit bytes are lost when an audit collect fails.** In `cleanup_tasks` and the interruption path of `invoke`, `remove_task` runs in `finally` even when `collect` or `audit` raised. A probe with `collect` failing on an orphan tree raised `DiagnosisTaskCleanupError` but the tree was already gone and no audit file existed. This contradicts "Persist bytes before task-tree deletion". The impact is audit-only and gives no authority. Consider skipping removal when audit fails, since the run stops as infrastructure anyway.
- **N2. Undesigned public-card field.** `c.card['diagnosis_driver_qualification']` (line 310) is a new public-card field the design does not mention. Confirm that publication sanitisation accepts it, or keep it private.
- **N3. Narrowed sudo environment is unasserted.** For OpenCode, `--preserve-env=<filtered keys>,OPENCODE_CONFIG,XDG_DATA_HOME` is built but never asserted. A one-line assert in `test_runtime_driver_commands...` would pin it.
- **N4. `RESULT_SCHEMA` has no agreement test.** The design says "contract tests keep its field set and schema in agreement" with `validate_result`. The only reference to it in tests is the schema-roll patch, so nothing checks that `RESULT_SCHEMA` and `validate_result` agree.

## Prior dispositions

**Design-1**
- **B1 and B2 (extension writer bypass and baseline reconstruction):** open, unqualified, not touched by this slice.
- **Extension M5 and M6:** open.
- **M1–M4, M7 and N1–N4:** remain resolved as recorded in design-2 to design-5.

**Design-2 B1 (re-mint):** fixed at the producer, and a test proves it (the revert was killed).

**Design-3 M1–M3 and design-4 M1–M2:** the implementation matches the design text. Mode comes from the last row's kind, audit-only collects never change state, and the pending branch makes no snapshot before the ACK. M2's integrity half is weakened by M1 above.

**Design-5 N1–N6:** all implemented as described in "Confirmed correct".

**Diff-24 N1 (bad-kind control):** the design now points at existing evidence. Removing the `kind` allow-list makes `test_stream_d_inputs` fail, so the control is real.

## Validation boundary

- **What this review covers:** an offline reading of the code against the design, the 20 focused dispatch tests, and scratch mutation probes over 70 focused tests.
- **What it does not cover:** the full suite. No suite result is claimed by this review. Root, UID, `sudo` and transport were substituted in the tests. The saved practice bytes, the 5813be ledger, reserve/reconcile/snapshot, file modes, `flock` and main-entry routing ran for real.
- **Not qualified:** real Unix isolation, the iptables loopback permit on a VM, a live bounded provider, and B runtime activation.
- **Unchanged:** no Murphy row closes, `DIAGNOSIS_ENABLED` stays `False`, and no launches, model calls or decryption were done.

## Elephant response

Both majors accepted. Narrow verification failures to the input-invalid boundary; preserve infrastructure exceptions for runner retry. Add observable controls for every listed surviving guard. All four nits are also accepted: retain the disposable tree if audit persistence fails, keep driver qualification private, assert the OpenCode sudo allowlist, and test the declared schema against validation. No Murphy row closes or runtime activation is claimed.

## Elephant resolution

M1: replaced the dispatcher-wide conversion with a verification-only exception
boundary. Qualification, helper setup/transport, retained-byte writes and atomic
publication propagate to the existing runner infrastructure handler. The input
and held-history helpers also let non-missing filesystem I/O failures propagate;
history initialization writes outside its validation handler. Controls cover
qualification, prepare, reset, raw output, input manifest, history creation,
decision and model-free scorecard publication failures, followed by successful
resume with the same exhaustion ID. A subprocess through real run.main also
publishes runner_error:ValueError for failed qualification and then resumes to
diagnosis_pending without a writer.

M2: all six named guards now have differentiating controls. Judgment selects the
last route while repair prefers the first unless pinned; a schema-valid changed
decision disagrees with its raw answer; post-role collection supplies valid raw
bytes with a wrong exposed digest; each forbidden reviewer family is checked;
an unknown task child refuses cleanup; and the runtime transport stub requires
both listener rules already installed. Six isolated in-memory single-guard
deletions each failed their matching test for the intended behavior, without
editing source files. Log: /tmp/stream-d-diff25-guard-probes.log.

N1–N4: failed audit persistence leaves its task tree for the next cleanup;
qualification is a private context attribute; the OpenCode preserved-key set is
asserted at the runtime boundary; the schema contract test checks exact required
and allowed fields (including nested objects), outcome alternatives and null
conditions against validate_result. All changes await a fresh diff goldfish.

Focused validation: 72 dispatch/input/held tests passed, then the added real-main
qualification retry control passed separately. Full-suite validation follows
on the complete revised source/test tree. No Murphy row closes.

## Revised full-suite result

At unchanged source/test commit 1bb3a93, the required command
`uv run --with numpy --with scipy python -B tests/run.py` passed:
**151 scripts, 0 failed**. Launch guards passed; no isolated rerun was needed.
Log: `/tmp/stream-d-dispatch-fixes-suite.log`, SHA-256
`221f2abc1694371c63173e0001413b501ed1d22c7bcdeaad94da655e2f3a487d`.
Fresh Claude diff27 remains pending. This suite result does not supersede the
failed diff25 verdict without that independent follow-up. No Murphy row closes.
