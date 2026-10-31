# Goldfish design review 3: `docs/designs/stream-b-creation-intent.md`

**Reviewer:** fresh goldfish. Read-only, no parent context. **Mode:** REVIEW. **Personas:** `zoom_out`, `design_critic`, `implementation_readiness`. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, and `zoom-out-standard.md` (which `zoom_out.md` requires).

**Tree:** worktree `t3-ded79ec5` at `6f30f8d`. Untracked: the design, reviews 1 and 2, and `docs/reports/stream-b-cost-contract-20261031/`. Nothing is implemented yet.

**Read:**
- the design, reviews 1 and 2, and `docs/ENGINEERING.md`
- `bin/boat-launch-guards.sh` (all), `bin/boat-call`, `bin/processes.py` (`run`), `bin/boat-spend` (`balance`, `--check`/`--finish`) and `bin/exam-launch` (guard use)
- `tools/run-gate-smoke.sh` (guard use)
- `factory/control_resume.py`, `factory/launch.sh` (lines 12–16, 122–126, 420–428, 630–660, 775–790)
- `factory/batch_holder.py` (`record_child`, `_created`, `_retirement`, `_reconcile_one`, `reconcile`)
- `tests/factory/test_control_resume.py` (harness and tests), `tests/factory/test_isolation_timeouts.py` (330–450) and the `fixtures/isolation-timeouts/` files
- `tests/factory/test_batch_holder.py` (`started`, the ambiguous-creation test) and `tests/bench/test-guard-bounds.py`

**Evidence check:** I recomputed the SHA256 of every page in `sources.json`, and all of them match. The `BOAT_TYPE` rates, the USD 0.07 start price and the no-egress line all match `pricing.md` and `limits.md`.

## Verdict: **PASS** (0 blockers, 0 majors, 8 nits)

## Verification of review-2 fixes

**Blocker 1 (resolve markers in every guard_exit, including after SIGTERM): fixed.**
- **Rule (lines 43–45).** Every `guard_exit`, live or resumed, now uses the same rule for each `new.N.pending`: a valid created ID leads to durable response and ID files, then the marker is unlinked. If the identity is missing or malformed, the marker stays.
- **Quiescence (lines 45–51).** The design gives the argument for each case:
  - Live: the trap runs only after the foreground create returns, and `guard_exit` already kills and waits for jobs (`boat-launch-guards.sh:231-234`).
  - Resumed: the lock is taken again through `control_resume.py:51-53,71`.
- **The regression review 2 named is closed.** Take the exact case: `kill <pid>` reaches the controller alone, and the create later succeeds. The live `guard_exit` now reads `new.N`, persists the ID, unlinks the marker, retires the VM and finishes.
- **Callers with no saved state.** Lines 70–72 retain the temporary state when the run is unfinished or cleanup failed, so `rm -rf "$state"` (line 280) no longer throws the evidence away. I checked `exam-launch`: its only `$state/` payload is the bundle, which `guard_exit` already removes. The retained directory therefore holds no secret or case material.
- **Test 3** covers the SIGTERM case without saved state, for both outcomes (an ID arrives, or none does).

**Major 1 (merge must fail closed): fixed.**
- **Computation (lines 63–70).** The merged list is computed before anything is written, and it must be a superset of the existing IDs. Read or parse failures neither replace `ids` nor allow finish.
- **File matching.** Only files matching `new.[0-9]+` are read. This is the same regex as `batch_holder._created:295`, so `*.pending` files can no longer raise `IsADirectoryError` inside the merge.
- **Pending check.** It now uses `-e` or `-L` instead of `-f`, and a marker that is not a regular file is never resolved.
- **Failure handling.** If the merge fails, `guard_exit` keeps the existing `ids`, marks cleanup failed and blocks finish. The `launch.sh` resume branch passes the failure on.
- **Test 4** runs `guard_exit` after the directory-at-`new.2.pending` injection. It asserts that serial 1 survives in `ids` and that nothing finishes or completes. It also injects an unreadable response.

**Major 2 (clause after unlink; `$id` when persistence fails): fixed as requested.**
- **After-unlink clause.** The clause that couldn't be implemented is gone. Lines 55–57 give the safety argument: `ids` is durable before the unlink, and a marker restored by a crash only leads to the same resolution again.
- **`$id`.** Lines 32–34 set `id` as soon as a valid ID is parsed, before persistence, and keep it if persistence fails. See nit 1 for a consequence on the Boat path that the design leaves out.

**Major 3 (real control_resume harness and deletion-receipt source): fixed.**
- **Harness.** Lines 123–127 name `test_control_resume.py`'s real exec path through `launch.sh`, which runs `control_resume.py` and then execs `sh`. The fake provider runs under the real `boat-call` and `processes.run`, so the claims about lock inheritance and process sessions are tested against the code itself, not against a self-made `flock`.
- **Kill targets.** Tests 1 and 2 kill different things: the controller group together with the provider group, and the controller PID alone.
- **Deletion evidence.** The clarification on lines 128–131 is accurate. I checked the harness: `op-owned` and its deletion responses are dicts written inside the fake (`test_control_resume.py:94-98`), not retained live receipts. Using them with the real `guard_delete_receipt` verifier, and claiming no live deletion qualification, is correct.

**Review-2 nits 1–4: applied.**
- **Nit 1.** Line 126 now describes the process layout correctly.
- **Nit 2.** All three in-place `cp` rewrites are replaced, including `launch.sh:638-639`.
- **Nit 3.** Test 4 checks the real `$id` after `guard_new`, not a copied loop.
- **Nit 4.** The holder outcome is deterministic: `pending`/`creation_unknown`, with exactly one failure counted.

**Review-2 nit 5:** the elephant kept the cost section here, with a reason. It is optional, and I accept that.

## Zoom-out

- **Scope is minimal.** The design reuses the existing marker name, finish guard and holder `new.*` ownership test, and it removes the late `touch`.
- **What it does not add.** There is no journal, supervisor, adapter, manual clearing switch or replay.
- **Nothing duplicated.** I looked for an existing durable-replace helper. `guard_delete_receipt`'s `save()` and `boat-spend`'s `write()` are not reusable from shell, and neither fsyncs the directory. An inline helper is justified.
- **Root cause.** The design fixes the root cause, which is the marker being written after submission, not a symptom.
- **Rules.** It changes no section 4 rule and no security property.

## Heilmeier

All of these are present and plain: the objective (line 19), the state of the art (lines 12–17), the new approach, the impact, the risks, the cost (line 169), the timeline (line 20) and the exams (tests 1–5). No Murphy rows close, which is correct, and the rows left open are listed.

## Nits

1. **On the Boat path, a persistence failure does not lead to retirement as lines 33–34 and 58 claim.**
   - `guard_delete_receipt` refuses any worker that is not in `$state/ids` (`boat-launch-guards.sh:105`).
   - Suppose the `new.N` fsync or the merged-ID write fails. Then `$id` is not in `ids`, and the `launch.sh:654` failure branch fails its ownership check. The VM keeps running until its TTL, or until a later merge succeeds.
   - That is fail-closed: the marker is kept and finish is blocked, so it is safe. But "can retire that worker" is true only for the direct-delete (Hetzner) path.
   - Also, `guard_exit` retires the workers listed in `ids`, not `$id`, so the phrase "id remains available for retirement" on line 58 misleads.
   - **Fix:** say this in one sentence. Add one test: pre-create a directory at, say, `new.9`, then replay a valid created event for serial 1. Assert that `guard_new` fails, `id` equals the saved ID, the marker is kept and nothing finishes.
2. **Lines 54–57 are ambiguous about directory-fsync failure after the unlink.** Does it block finish on that exit, or not at all? Line 39 makes `guard_new` return failure, which leads `launch.sh` to retire a VM that was created correctly. State the `guard_exit` behaviour in one phrase, for example "reported as a cleanup error; does not block finish". Accept the wasted VM in `guard_new` explicitly.
3. **Some markers are false positives, and that is accepted but not stated.** SIGTERM or SIGKILL can arrive after the marker helper returns and before the create subshell starts. Then the marker exists with no `new.N`, and the hold stays reserved for good, even though nothing was submitted. Fail-closed is the right choice. Name it next to the other residuals so it is not later reported as a new bug.
4. **Lines 63–65 make a valid JSON line that is not an object fail the merge, and that failure is permanent.** A line like `42` or `"text"` can never carry an ID. `batch_holder` also fails on such lines (`AttributeError`), so the two agree. But one harmless progress line would block finish for good. Consider skipping these lines, like malformed ones. Optional.
5. **The saved `created.json` is pretty-printed over 5 lines.** Line-based parsing never finds an ID in it. Tests must emit `json.dumps(LOAD('created.json'))` as a single line, as `test_batch_holder.py:72-73` already does. Say this, so "replay the saved event" isn't read as a byte-for-byte copy.
6. **The fake counts every `billing` call as a finish.** In `test_control_resume.py:84-87`, the fake appends `finish` to `effects` on each `billing` call. A fresh launch's `boat-spend --check` also calls `billing` (`boat-spend:56`). For tests 1 and 2, assert "no finish" from the spend record (`finished_at`) and the ledger status, not from that counter.
7. **Test 3 harness gaps.**
   - A bare shell has no `collect_vm`. Either define a trivial one, or pre-touch `.collected` and say which.
   - The `test_isolation_timeouts` fake exits 9 on `delete`, `deletion` and `list`. It must answer with the authored operation responses from `test_control_resume`, bound to `bx_d6dzvjbc`.
8. **`$id.started` is missing for an ID that only the resume path learns about.** This is not a regression. On resume, `guard_wait` runs `cat "$state/$wait_id.started"` (lines 337 and 346). The file never existed for a worker whose controller died before `guard_new` finished, so the arithmetic expansion fails and the shell aborts into `guard_exit`. Test 2's route to finish may pass for that accidental reason. Consider writing `$id.started` when resolving an ID, if it is absent, matching `launch.sh:652`. At minimum, make test 2 assert which route it took.

## What passes

- **Ordering.** The live order is correct: exclusive marker, fsync of the file and the directory, invocation, fsync of `new.N`, durable merged `ids`, unlink, fsync of the directory.
- **Same rule everywhere.** The resolution rule is identical in `guard_new`, live `guard_exit` and resumed `guard_exit`, and each case has its own quiescence argument.
- **Merge.** It fails closed, keeps a superset of the existing IDs, and treats any pending path as unfinished.
- **Lock claims.** The lock-inheritance claims match `control_resume.py:71-74` and `processes.py` (`start_new_session`, default `close_fds`).
- **Residuals.** The provider-only orphan and CLI multiplicity residuals are stated honestly and keep activation closed.
- **Tests.**
  - The tests use real `control_resume`, `boat-call` and `processes.run`, plus saved provider artifacts.
  - Authored timing and the authored deletion responses are correctly labelled as fault injection.
  - The holder consumer is checked with exact outcomes.
- **Cost section.** It is accurate against the hashed sources, hedged, and enables nothing.

**No blocking findings are open.** The nits are optional, but nits 1, 5 and 6 save the implementer guesswork.

## Elephant response

Pass accepted. Nits 1, 3, 5–7 incorporated in implementation/tests and design clarifications. Keep non-object JSON fail-closed to match the reviewed rule. All persistence failures block finish on the current exit; post-unlink failure does not permanently prevent later finish because identity is durable. Resume recovery test will assert the existing missing-start route explicitly, rather than invent a fresh TTL start. No blockers rejected.

