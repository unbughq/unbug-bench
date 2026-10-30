**FAIL: 1 Blocker, 2 Major, 3 Nits.** The narrow rule itself (one numeric UID, `127.0.0.1/32`, `-o lo`, TCP, one gate port) is right, and I don't object to its UID, destination or concurrency scope. What fails is cleanup: revocation as specified won't run on cancellation, and "keep the bound port out of reuse" doesn't say how. I made no edits, so the parent should save the text below as `docs/reviews/router-gate-wall-design-1.md`.

---

# router-gate-wall-design-1 — goldfish design review

**Scope:** `docs/designs/router.md` § "Invocation-local gate access through pilot_wall" (worktree t3-b7dfac7a, HEAD cb434e3 plus uncommitted design edits).
**Source read:** `factory/model_call_gate.py` (`Gate`, `enforce`), `factory/model_runtime.py` (`_invoke`, lines 575–630), `factory/run.py` (`pilot_wall`, `sh`, `make_pilots`, `early_probe`), `bin/processes.py` (`run`), `factory/exam_responder.py` (`owner_channel`, `docker_owner_server`).
**Personas and standards:** zoom_out, design_critic, implementation_readiness; Mode REVIEW.

**Verdict: FAIL**

The rule's scope is correct. It admits one numeric UID, `127.0.0.1/32`, `-o lo`, TCP, and the gate's single bound port. It is inserted into the UID's own `factory-<user>` chain and adds no range, no ESTABLISHED acceptance and no IPv6 change. `owner_channel` already uses the same per-port pattern, so this adds no new kind of mechanism. Concurrent invocations are separated by distinct bound ports, and deletion by full rulespec is exact. The failures are in cleanup.

## Blocker

**B1. Revocation through the runtime's `command` callback is skipped on exactly the path that needs it.**
- The design routes insert and delete through "a closure around self.command(c,...)". That callback is `run.sh`.
- `sh` passes `cancel=c.role_cancel` to `processes.run`. `processes.run` raises `Cancelled` before spawning anything if `cancel.is_set()` (`bin/processes.py:95`), and `sh` turns that into `BudgetError('cancelled')` (`run.py:156`).
- `_invoke` passes that same `role_cancel` to `enforce`.
- Failure scenario: a role is cancelled. `enforce`'s finally calls the closure to delete the rule, and `iptables -D` never executes. The error is `cancelled`, not `cancellation_failed`. Then `gate.close()` runs `server_close()` as it does today, which frees the port while the ACCEPT rule is still installed.
- That is the exact state the brief forbids: a free port behind a live exception. The unit test plan would miss it unless the fake `command` copies the cancel-gate behaviour.
- Smallest fix: drop the `command` keyword and the closure. Inside `model_call_gate`, run both argvs with `subprocess.run([...], check=True, capture_output=True, timeout=30)`, as `exam_responder.docker_owner_server` already does. `enforce` then gains only `user=`.
- State that revocation must not depend on any cancel event. Add a unit test: cancel is set, the delete argv still executes, and the rule is absent afterwards.

## Major

**M1. "Keep the bound port out of reuse while revocation is unresolved" is not concrete.**
- `Gate.close()` always calls `server_close()`, and the section names no change to it.
- Specify the split exactly:
  - The finally order is: revoke, then `gate.state.close()`, then `server.shutdown()`.
  - Only if revocation succeeded: `server_close()` and the thread join.
  - If revocation failed: append `gate.server` to a module-level `_RETAINED` list so garbage collection cannot close the socket.
  - In both cases, snapshot usage into `cap_used` and then raise `BudgetError('cancellation_failed')`. That error takes precedence over any in-flight exception and over `model_call_cap`. The existing `!= 'cancellation_failed'` guard already allows for this.
- State the backstop once the process is gone. When the process exits, the port is freed. The stale rule is then removed only by `pilot_wall(remove=True)`, whose `-D/-F/-X` steps are unchecked. The chain cannot be silently reused, though: if `-F` fails, `-X` fails, and the next `make_pilots` → `pilot_wall` `-N` (check=True) refuses. Write that argument into the design so it is a stated invariant. Add one unit test that a failed delete leaves the socket bound and a fresh `bind` to that port gets EADDRINUSE.
- Without this, an implementer has to invent the retention mechanism, which fails the implementation-readiness standard.

**M2. The live probe isn't specified concretely enough to build first time.**
- Name the probe's path (for example `tests/factory/live/gate_wall_probe.py`).
- Name the saved inventory fixture. `pilot_wall` needs a `c` with `c.case / "base"` loadable by `bench.load_scenario`, plus `sh`, `c.work/logs`, and `factory_slot` or `args` as used.
- Name the exact Boat create/delete command and flags (`bin/hcloud-boat`? `bin/boat-launch-guards.sh`?).
- Name how the per-worker cost evidence is obtained. `boat-spend` deltas are account observations (Murphy 49) and must not be used.
- Give the computed rate × TTL ceiling before creation, so "< $0.10" can be checked from the document.
- Say how the test identities are named, created and removed. They must not collide with `pilot`, `pilot-strong` or `pilot-easy`, or `make_pilots`'s `ValueError` guard has to be bypassed deliberately.

## Nits

1. **The process-kill claim is too strong.** "The existing monitor kills/joins the invocation process group … before returning" conflicts with `_invoke`'s own comment: the CLI can survive the group kill, and `pkill -u` runs after `enforce` exits. Security still holds, because revocation only removes access. Reword so cleanup never depends on the processes being dead.
2. **The bearer check is not a separation property.** The gate's bearer is the shared provider OAuth token (`enforce`: `CLAUDE_CODE_OAUTH_TOKEN`), not a per-invocation secret. Say that cross-invocation isolation rests entirely on UID + port + revoke-before-release, not on "the gate still checks its bearer credential".
3. **Murphy register.** A gated isolated invocation failing on every pilot/strong/easy call is a known batch stopper. Add a row `new-router-gate-wall-1` and close it with the committed unit test plus the recorded live-probe evidence. Alternatively, state why it is excluded.

## Checked and accepted

- **UID:** `pwd.getpwnam` is resolved after `make_pilots`, and the numeric match is in addition to the chain's owner jump.
- **Destination:** `127.0.0.1/32`, `-o lo`, TCP, `--dport` of the bound port, inserted at position 1 of the existing IPv4 chain. No ip6tables change is needed because the gate binds IPv4 only.
- **Concurrency:** bound ports are distinct and deletion uses the full rulespec plus comment, never a line number.
- **Setup failure:** it closes the gate before the subprocess starts. `user=None` makes no firewall calls.
- **Existing bench/service allows:** unchanged, and no new local destinations are added.

**Smallest path to PASS:**
1. Fix B1 by running the firewall argvs with direct, cancel-independent `subprocess.run`.
2. Fix M1 with the exact close split, `_RETAINED`, and the `pilot_wall`/`-N` backstop sentence.
3. Fix M2 by naming the probe path, fixture, Boat commands, cost source and ceiling.

---

The Blocker also applies outside this design: the existing `owner_channel` cleanup and `_invoke`'s `pkill` both go through the same cancel-gated `sh`. I didn't count either as a finding here because they're out of scope.


## Author response for round 2

B1 fixed: drop command callback; direct subprocess.run is cancellation-independent.
M1 fixed: specify close(release_socket), _RETAINED, snapshots/error precedence,
EADDRINUSE test and checked chain-creation backstop after process exit.
M2 fixed: name live probe path, public S13 inventory fixture, exact contexts,
noncolliding users, pinned Boat commands, per-worker usage and $0.082 envelope.
N1/N2 corrected process-death and bearer-isolation claims. N3 adds a Murphy row.
No finding rejected. No production change or worker launch yet.
