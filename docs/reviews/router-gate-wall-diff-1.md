# Goldfish diff review: router-gate-wall-diff-1

**Code verdict: PASS.** No Blocker or Major findings. There are four optional Nits.
**Suite verdict: none yet.** The full-suite record `/tmp/router-gate-wall-full-d15af56.json` still says `"status": "running"`, and the `.log` is partway through `tests/bench/`. I make no pass claim until it ends with exit 0 and 0 failed. ENGINEERING.md step 4 still blocks the merge until then.

Scope reviewed: `2c85e7a..d15af56` (HEAD `d15af56fbdcc07c825943425969fca325dbe3cb9`), in worktree `t3-b7dfac7a`, read-only. Persona: zoom_out + implementation_readiness, Mode: REVIEW.

## Root cause and minimality
- The root cause is correct. `run.pilot_wall` (`factory/run.py:88-115`) appends `addrtype LOCAL -j REJECT` after the fixed bench and service ACCEPT rules, so a pilot UID cannot reach the gate's ephemeral `127.0.0.1:<port>`.
- The fix is as small as it can be:
  - one `@contextmanager _wall_access` (`factory/model_call_gate.py:403-430`);
  - an optional keyword-only `user=` on `enforce` (`:434`);
  - one call-site change in the runtime (`factory/model_runtime.py:592`);
  - a matching signature change in the test seam (`tests/factory/router_test_support.py:20`).
- `run.py` is unchanged: identical sha256 `02eaa934…` at e95d025 and d15af56. There is no new abstraction, no port reservation, no range, no ESTABLISHED rule and no IPv6 change. This matches design §"Invocation-local gate access" (`docs/designs/router.md:1218-1300`).
- The rule matches the design exactly. It is inserted at position 1 of the existing `factory-<user>` chain, so it runs before the `LOCAL REJECT`. It matches the numeric UID from `pwd.getpwnam`, `-o lo -d 127.0.0.1/32 -p tcp --dport <bound port>`, and a `factory-gate:<lease_id>` comment.
- Commands use argument arrays with no shell and no token. Deletion is by exact rule spec, never by line number or by flushing the chain.

## Cancellation and uncertain-outcome safety
- Cleanup is owned before the insertion attempt: `attempted=True; revoked=False` at `:414` comes before `subprocess.run`, and `confirmed=True` at `:417` comes only after exit 0.
- Delete is attempted after any insertion attempt, through a direct `subprocess.run`. No run.sh or cancel callback is involved, so the R1 blocker is resolved. The test at `test_model_call_gate_wall.py:115` sets the real cancel event and confirms the delete still runs.
- The release decision is `release = not attempted or (confirmed and revoked)` (`:428`). So an insertion that times out or is rejected keeps the socket in `_RETAINED`, even when the delete succeeds. This is the R3 fix, pinned by `:175-193` for both TimeoutExpired-after-apply and CalledProcessError.
- Revocation happens before release. `gate.close(release_socket=…)` runs after the delete inside `_wall_access`. `close` (`:396-400`) always does `state.close()` + `shutdown()` + join, and calls `server_close()` only on release. The `-D`-time `assert_bound` check in the test command fake (`:49`) proves the port is still bound when the delete runs.
- Precedence:
  - `cancellation_failed` replaces the body error (via `from None`).
  - `enforce` catches it as `failure`, so `model_call_cap` is suppressed (`:456`).
  - `cap_used` is always snapshotted, after close (`:455`).
  - Pinned by `:158-173`, which covers an in-flight reservation, exhaustion set and a failed delete.
- When `user=None`, no firewall command runs (`:121-122`).
- Missing identity: the error is raised before `attempted`, the socket is released, there is no insert and no launch (`:138-145`). The runtime wraps it as `usage_monitor:KeyError`.
- A retained socket stays listening without being served, and its Allowance is closed. Even if a late rule survives, the pilot UID can reach only that dead backlog.

## Exact-lifetime isolation and runtime wiring
- The exception spans only the `yield` around `run_budgeted` (`:450`).
- The runtime's later `pkill -u` (`model_runtime.py:618`) runs after revocation, as the design states. Nothing in the code assumes the CLI is already dead.
- `_invoke` passes its actual `user`. The test at `:86-107` drives the real `ModelRuntime._invoke` → real `enforce` for `pilot`, `pilot-strong` and `pilot-easy`, and asserts that the chain is `factory-<user>`, the URL is a loopback base, and a `-D` follows.
- Concurrent rules stay distinct by port and comment, and each cleanup deletes only its own rule (`:127-136`).
- Chain names `factory-pilot-strong` and `factory-pilot-easy` match `pilot_wall`.

## Real Linux proof: limits and closure
I checked the evidence:
- The fixture's `source_sha` is `e95d025…`. The embedded `source_sha256` for model_call_gate.py, model_runtime.py, run.py and gate_wall_probe.py equals `git show` of both e95d025 and d15af56. So d15af56 changed only evidence and test files.
- Fixture sha256 `91867a20…` and controller sha256 `8716ff8c…` match `docs/reviews/router-gate-wall-live-evidence.json`.
- The controller archives `git archive HEAD` (e95d025 at run time) and runs the committed probe. The probe is not picked up by `tests/run.py`, which globs `test*.py`, so it cannot fail the suite on Darwin.

The 21 checks and rule snapshots establish:
- denial before insertion;
- the exact UID/port reachable with a validated stub 200;
- another local port, another walled UID and an IPv6 loopback listener all denied;
- 9000 and 9010 still allowed;
- the active iptables rule set equals the baseline plus exactly one line;
- ip6tables unchanged;
- after both normal and exceptional cleanup, rules equal the baseline exactly, and a fresh listener rebound on the former gate port is denied;
- chains and users removed, with `cleanup_errors` empty.

The probe used the real `pilot_wall` against the public S13 inventory, a synthetic bearer, and HTTPSConnection patched to a local stub, so no model or provider credential was involved. Two receipts were recorded, each with `validated_requests=1` and `unknown_requests=0`. **This shows that no local access was broadened.**

Limits, stated plainly so nobody over-claims:
1. The live run drives `gate.enforce` directly. It does not exercise `ModelRuntime._invoke`, `run_budgeted`, `sudo -u` launch or the real Claude CLI. Runtime wiring is proven only by the mocked unit test.
2. The identities are `useradd --system` throwaways, not created through `make_pilots`. The wall itself is real.
3. The failure paths (timeout, failed delete, late insertion) are proven only with fakes, not on real iptables.
4. "Other UID denied" uses a second walled UID. Non-walled UIDs such as the runner and root can reach the gate, which was already true before this change and is out of scope.
5. Isolation is per UID. Two concurrent invocations under the same pilot UID could reach each other's gate. The design accepts UID granularity and correctly does not treat the shared Claude bearer as an isolation boundary.

**Murphy `new-router-gate-wall-1` closure qualifies.** `test_saved_real_linux_wall_proof` (`:60-84`) validates the saved real-Linux artifact, the unit tests cover the lifecycle, and the row text matches the evidence.

## Cost, cleanup and deletion
- From `since` 06:18:14.514Z to the confirmed deletion at 06:18:32.310Z is 17.796 s, rounded up to 18 s. At $0.036/h that is **$0.00018**. ✓
- Observed attributed cost was 14 s / $0.00014. The post-deletion usage query returned an error, recorded as `final_usage_error: RuntimeError`.
- Both the fixture and validation.md say explicitly that there is no final provider cost and that the figure is not a wallet delta. That framing is correct.
- Planned ceiling was 0.036×1200/3600 = $0.012. Reserved worst case was $0.082. Both are under $0.10. ✓
- Deletion `bdop_0fc7ef2ae61c4bceb9c22b057b8581dc` has a matching targetId and kind `sandbox`, status and stage `completed`, and the worker is absent from inventory. The controller ran for 20.63 s.
- The controller has a single creation attempt and guards against a pre-existing worker with the same name. Nothing suggests a second worker.

## Findings

**Blocker:** none.

**Major:** none.

**Nits** (all optional):
- **N1** `docs/reviews/router-gate-wall-validation.md:7` says "seven wall tests". The file has eight; the saved-fixture test was added in d15af56. Update the count.
- **N2** `factory/model_call_gate.py:425,430`: `except BaseException` followed by `raise BudgetError('cancellation_failed') from None` turns a KeyboardInterrupt or SystemExit during delete into `cancellation_failed`. It fails in the safe direction (the socket is retained), but it hides what interrupted the delete.
- **N3** `factory/model_call_gate.py:428-430`: a certain rejection of the insert (for example a missing chain, iptables exit ≠ 0) is treated as uncertain, as R3 mandates. Each such call permanently retains a socket. `from None` also drops the CalledProcessError and its stderr, so a diagnosis sees only `cancellation_failed`. Chaining the cause would help debugging without changing the safety behaviour.
- **N4** `docs/murphy-register.md:67`: the `Closed by` cell lists `tests/factory/live/gate_wall_probe.py`, which is a manual probe and not a suite test. Closure actually rests on `test_model_call_gate_wall.py` plus the saved fixture. Consider saying "manual probe; fixture validated by …".

## Set aside as out of scope
- the unrelated cheap-model design and the completed tariff fix;
- non-walled UIDs reaching the gate, which predates this change;
- access between concurrent invocations under the same UID (the design accepts UID granularity);
- the unchecked `pilot_wall(remove=True)` teardown, an existing backstop that the design leaves unchanged;
- the IPv6 gate listener (the gate is IPv4-only);
- downstream handling of `cancellation_failed` beyond the existing budget path;
- final Boat billing reconciliation (no provider record exists).

**Summary:** the code is PASS with nits N1–N4. The suite has no verdict yet. Merge needs the d15af56 suite to finish with exit 0 and 0 failed, recorded in its terminal result.

## Author response

Accepted; no findings rejected. N1/N4 wording is corrected to distinguish the
eight suite tests and manual probe from its validated saved fixture. N2/N3 are
deferred: conservative retention/error precedence remain as reviewed and no
production source changes during the full suite. The suite is a separate gate.

## Subsequent terminal suite record

The frozen reviewed SHA d15af56fbdcc07c825943425969fca325dbe3cb9 passed
145 scripts, 0 failed, exit 0, finishing 2026-10-30T06:38:33.389159Z.
See router-gate-wall-full-d15af56.json and its SHA-256-linked gzip log.
The original review-time pending statement remains historical. No production
source changed during the suite. The fresh diff review accepts the Murphy closure.
