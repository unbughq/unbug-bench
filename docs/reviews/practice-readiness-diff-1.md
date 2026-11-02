**Verdict: PASS.** No blockers. There is one major finding, and I recommend fixing it before merge because the fix is one line. I reviewed range 070a332..563fd54 read-only. I made no edits, network calls, worker launches or secret reads.

## Blockers
None.

## Major
**M1. A failed practice check can crash the key holder's loop.** `factory/key_holder.py:443` calls `batch_holder.active(policy, ROOT)` without catching errors. For the practice id with the environment variable set, `practice.active` loads `money.manifest`. If release or manifest checking fails at runtime, it raises `MoneyWait`, or `ValueError('request_refused')` when the manifest doesn't match. That exception escapes `batch_tick` into the `serve` loop at line 578.
- Every other scan in `batch_tick` is wrapped in `except Exception`, and its docstring says a refusal "never stops the holder".
- A holder crash loses the identity held in RAM, which means an unplanned unlock stop by the operator.
- This only affects the practice id; legacy behaviour is unchanged.
- **Fix:** wrap the `active` call in `batch_tick`, log the label and return. Add one test where the manifest fails under the practice environment.

## Nits
1. The watchdog reports `uncertain` before creation, when there is no `monitor.sh` and no IDs. The design (`practice-readiness.md`) says a missing monitor before creation is expected, and the status vocabulary has `waiting` for this case. The label is wrong, but the behaviour is safe.
2. `guard_new` writes `<id>.started` only after `boat new` returns, which can be up to 300 s, plus naming, after the provider created the worker. The real provider-TTL margin is therefore 900 s minus that lag, not 900 s. It is still positive, but neither doc states it.
3. If the controller dies between creation and writing `.started`, or if `new_status != 0`, the watchdog never computes a deadline and the provider TTL becomes the backstop. The design accepts this, but `practice-run.md` step 6 should say so.
4. `practice-run.md` step 6: `tools/practice-fault.py` refuses unless the operator's shell exports `UNBUG_PRACTICE_BATCH=b-plumbing-practice`. This fails safe, but the step doesn't say it.
5. `tools/pin-practice.py` doesn't check for "the reviewed readiness files" that the design lists. It only checks for a clean head equal to factory-simplify.
6. The preflight `activation`, `cleanup` and `fault` checks only test that things exist (`callable(practice.fault)`, file present), so they can't tell good code from bad. The behaviour is proven by `test_practice_readiness.py`, not by the preflight.
7. The exclusive lock in the deletion helper has no test with two processes competing; the existing tests cover only completed-receipt replay and the case where an attempt was recorded but no request was saved.

## Checked and correct
- **Activation:** it requires the matching id, the environment variable, `money.manifest` authentication (release, manifest SHA, `source-manifest`, recipient) and an exact `matches`. Other ids fall through unchanged.
  - When inactive, the practice id is refused in `batch_request` and in legacy `authorize`, through `practice_admission`.
  - The three call sites in `bind`, the three in `key_holder` and every `enabled(policy, root)` entry are converted, and `main` loads the policy first.
  - The variable is in `control_resume.ENVIRONMENT` and in dispatch's environment.
- **Dispatch:** `armed()` runs before `boat-call list` and again inside the second `money.locked`, before `dispatch_started=True`.
  - It checks the unit file hash, bounded `systemctl show` output (active, running, PID equal to the ready file's PID) and the ready file's operation, launch, timing and `policy_digest` of the whole policy. It also checks that at least one TTL remains before the batch deadline.
  - `MoneyWait` becomes TEMPFAIL, with no creation.
- **Deletion helper:**
  - It takes LOCK_EX on `<worker>.deletion.lock` (O_NOFOLLOW, regular file) for the whole transaction.
  - An existing completed receipt is validated and returned without a POST.
  - An attempt marker without a saved request is refused.
  - Not-found or a failed status query becomes uncertain, never completion.
  - The fsyncs are stronger than the extracted shell version.
  - The shell guards are thin wrappers that keep their diagnostic labels.
- **Timing:** the deadline is derived from the durable `.started` file (start + 1800 + 900, below start + 3600), and `monitor.sh` must show `ttl_seconds=3600` and `retire_at=1800`. A restart recomputes the same deadline, and no reservation time is used. `complete` requires validated receipts, a full inventory with `hasMore=false`, and no pending creation markers.
- **Fault:** it fires after the outbox write and before transport, is consumed atomically, and refuses re-arming. The test shows no objects, no ACK and no current pointer after the fault, `failures=1` with no incident, then a replay of the same generation that resets `failures=0`.
- **Pins and preflight:** the output key sets match the design. Pinning refuses a dirty or stale head and an existing output path, and leaves an `INCOMPLETE` marker on failure. Live ceilings sum to $24.99, plus $0.01 unused.
- **Worker archive:** ownership is unchanged. `control/` and `tools/` enter only the host `TRUSTED_FILES` fingerprint, and the pin bundle carries them separately.
- **Honest scope:** no Murphy rows are touched or closed. Queued-child creation stays OFFLINE item8 work, outside this run. No live qualification is claimed, and `practice-run.md` keeps the likely $0 abort.

## Does the evidence prove what it claims?
Yes, for the suite. The record at 6e67efa has tree f0bc30a…, which matches `git rev-parse 6e67efa^{tree}`. The compressed and uncompressed log hashes match the files, and the log ends "172 test scripts run; 0 failed." Commits 6e67efa..563fd54 change only the suite JSON, the log and the report.

The new tests catch real faults: deadline boundaries at 102699 and 102700, deletion keyed to worker start rather than reservation, `hasMore`, a pending creation marker, a wrong launch, a missing start, wrong ready PID, hash or launch, and refusal to re-arm. The systemd, provider and `monitor.sh` inputs are authored test doubles, as the report says.

The three presence-only preflight checks (nit 6) are the one piece of evidence that doesn't discriminate.

## Writer disposition

Review PASS accepted, with no blockers. Parent instructed handback as soon as the
review passes, so no second diff round or further implementation is started.
M1 remains an open non-blocking major: a failed practice activation check can
escape batch_tick and stop the holder. It is not rejected or claimed fixed, and
is explicitly handed back for the parent before merge. Nits 1–7 remain open;
none is represented as live qualification or a closed Murphy row.
No source or test changed after the passing suite at 6e67efa. This commit records
review evidence and the handback only.


## Parent follow-up (M1)

Parent required M1 fixed before merge and one scoped Claude re-check (round 2).
The activation check now logs a fixed label and returns on refusal, with a real
manifest-mismatch regression and successful following scan. Nit 1 uses five
runtime lines to label an authenticated pre-creation wait; creation evidence
still means uncertainty. Step 6 documents nits 3 and 4. Nits 2, 5, 6 and 7 remain
open. These changes await the full suite and independent scoped re-check.
