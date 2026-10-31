I couldn't save the review because this session is read-only, so it's below in full for the elephant to store.

---

# Goldfish design review: `docs/designs/stream-b-creation-intent.md`

**Reviewer:** fresh goldfish, read-only, no parent context. **Mode:** REVIEW. **Personas:** `zoom_out`, `design_critic`, `implementation_readiness`. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, plus `zoom-out-standard.md` as `zoom_out.md` requires.
**Tree:** worktree `t3-ded79ec5` at `6f30f8d`. The design and `docs/reports/stream-b-cost-contract-20261031/` are untracked.
**Read:** the design; `bin/boat-launch-guards.sh`; `factory/launch.sh` (around 365, 426–427, 637–660); `factory/control_resume.py`; `factory/batch_holder.py` (264–380); `bin/boat-spend` (holds); `tests/factory/test_isolation_timeouts.py` (330–420) and its fixtures; `tests/factory/test_batch_holder.py` (pending tests); the cost-contract pages and `sources.json`; Murphy rows 6, 17, 27, 28, 29, 35 and 51.

## Verdict: **FAIL** (1 blocker, 3 majors, 7 nits)

## Scope (zoom_out)

The scope is right for the next delayed-cleanup step. It closes the gap between `boat new` being sent and `new.N.pending` being written. Today `guard_new` only touches the marker after a create returns with no ID (`bin/boat-launch-guards.sh:88-89`). A SIGKILL inside the `( … boat new … ) > new.N` call (line 75) leaves no marker. A resumed `guard_exit` (lines 261–278) then sees `unfinished=0`, runs `boat-spend --finish` and writes `complete`. The problem statement is accurate.

The change reuses the existing marker name, `guard_exit` check and holder check. It removes the late `touch`. It adds no journal, supervisor or adapter. It also keeps the cost qualification out of the code. That is the minimal design, and I found nothing existing that it duplicates.

## Crash ordering (design_critic)

The live path's ordering is right:
1. Exclusively create the marker, fsync it, fsync the directory.
2. Invoke `boat new`.
3. On a valid ID: fsync `new.N`, rebuild `ids`, fsync `ids`, fsync the directory.
4. Unlink the marker, then fsync the directory again.

If the process crashes mid-`cp` and leaves `ids` truncated, recovery still works, because `guard_ids` rebuilds `ids` from `ids ∪ new.*` while the marker survives.

The gap is in what a resumed process does next. That is the blocker below.

### BLOCKER 1: the common crash case now leaves a hold that never clears, and that is a regression

- **Affected scope:** "Change and what it deletes", ¶2 (lines 28–36) and ¶3 (lines 38–45). Test 1 (lines 90–94).
- **Finding:** `factory/control_resume.py:72` calls `os.set_inheritable(lock.fileno(), True)` and then execs `launch.sh`. So the `boat new` subshell and the `boat-call` Python process both inherit `controller.lock`. When only the controller shell is SIGKILLed (OOM kill or a single-PID kill), the creator keeps running. It writes its `created` event to `new.N`, exits, and only then frees the lock for a resume.
  - **Today:** the resumed controller's `guard_exit` gets the ID through `guard_ids`, retires the worker, finishes and writes `complete`. That is correct.
  - **Under this design:** the marker is never removed, because only the dead live path unlinks it. Every later `guard_exit` retires the worker but sets `unfinished=1`. So `boat-spend` never finishes, the ledger hold stays `reserved` for good, and `complete` is never written.
  - **Knock-on effect:** `batch_holder.record_child` counts each resume as failed. After `RETRY_LIMIT = 5` (`factory/batch_holder.py:28`) it records a terminal `resume_failed` incident. That is a human pit stop, which goes against the target property in `docs/ENGINEERING.md` §3.
- **Why the design's wording is not enough:** the design calls this "a crash before marker removal may leave an unnecessary hold". That suggests a tiny window. In fact it is the expected outcome whenever the creator survives the controller and the create succeeds. That is the very scenario the change exists for.
- **It is also inconsistent:** the live path clears the marker on "a valid created ID, persisted", whatever the exit status and despite the open question about how many workers the CLI creates. A resumed controller holding the reacquired lock, with a fully written `created` event, has the same evidence.
- **Required:** the design must choose one of these and test it:
  - **(a)** On resume, `guard_exit` applies the live clearing rule: valid `created` ID in `new.N`, then persist `ids`, then unlink and fsync. The design must state what proves the creator has exited. The reacquired `controller.lock` covers anything that inherited the fd. It must also state whether a provider binary that outlives a SIGKILLed `boat-call` stays a known residual. `boat-call` uses `subprocess` with its default `close_fds`, so the provider binary does not hold the lock.
  - **(b)** Keep the permanent hold deliberately. Then name the `resume_failed` pit stop and how often it is expected. Add a test that asserts this outcome. Justify why it is acceptable against §3.
- **Test 1 as written cannot tell (a) from (b):** its transport never returns an ID. It needs a second case where the fake transport survives the controller kill and then emits the saved `created.json` event.

### MAJOR 2: a stale `$id` can retire a healthy worker on the new early returns

- **Affected scope:** ¶1 (lines 21–25, "refuse the create…", "Persisting this marker must succeed before any provider invocation").
- **Finding:** in `factory/launch.sh:643-657` the loop calls `if ! guard_new; then … if [ -n "$id" ]; then … guard_retire "$id"`. Nothing resets `id` between iterations; the only other assignment is line 426. Today `guard_new` always reassigns `id` after the call (line 78).
  - The design adds two returns before the provider call: refusal because the file exists, and failure to persist the marker.
  - If either fires on serial ≥ 2, `id` still holds the previous serial's healthy worker. The loop then collects and deletes it in the middle of its run.
- **Required:** the design must say that `guard_new` clears `id` (and `new_status`) on entry, before any return. Add a test: serial 2 hits marker-persistence failure after serial 1 got a valid ID, and serial 1's worker must not be retired.

### MAJOR 3: test 1's kill semantics are unspecified, and the holder is not listed as a consumer

- **Affected scope:** Tests 1 and 3 (lines 90–99), and the list of marker consumers.
- **Finding:**
  - Test 1 says "kill the controller" but does not say whether that means the controller PID alone (creator survives) or its process group (creator dies). These give different outcomes; see Blocker 1. The implementer would have to decide.
  - The design names only `guard_exit` and `boat-spend --finish` as consumers of the marker. `factory/batch_holder.py:_reconcile_one` reads it too, through `if list(path.glob('new.*')): return` (line 350). It is the real batch path that decides between `pending` and `failed`/`preflight_refused`.
- **Required:** specify the kill target in each test, and add a holder assertion to test 1. After the resume, `holder.reconcile` with free locks must keep the operation `pending` and must not mark it `failed`. Use the real `launch.json` fixture shape that `tests/factory/test_batch_holder.py` already uses.

## Cost claims (design_critic)

I checked the six pages against `sources.json`, and all SHA256 values match:
- **USD 0.036/h default:** `pricing.md:20,78`.
- **Per-second billing:** `pricing.md:11`.
- **No egress charge:** `pricing.md:48`.
- **Automatic snapshots included, saved snapshots paid separately:** `pricing.md:46-47,79,84`.
- **Extra starts at most USD 0.07, "Above 6 times: Fails", "never queues a start":** `limits.md:30-42`.

The design doesn't overclaim anything. It explicitly declines a USD 5 bound, declines to enable admission, and lists the remaining unknowns (exceptional billable lifetime, CLI multiplicity, proof of no proxy or snapshot use at runtime). The cost section passes.

## Nits

1. **Murphy row 29** ("Uncertain starts … require reconciliation", which cites `bin/boat-launch-guards.sh`) is the row this design touches most directly, but the list of rows staying open does not name it. Add it.
2. **Pricing rate:** the cost section pins the `default` rate. `guard_new` takes `BOAT_TYPE` (small/default/large/xlarge at $0.018/0.036/0.072/0.200, `pricing.md:78`). The bound must use the selected type. Also say that the default cloud is Hetzner (`boat-launch-guards.sh:4`): the crash fix applies there too, but this cost evidence does not.
3. **fsync mechanism:** POSIX `sh` has no fsync. Name the mechanism, for example inline `python3` with `os.open(O_CREAT|O_EXCL|O_WRONLY)` plus `os.fsync` on the file and the directory, as the rest of the file already does. Say how its exit status reaches the `guard_new` return.
4. **`ids` rewrite:** it is rewritten in place with `cp`. That is safe for `guard_new`-derived IDs while the marker exists. But `launch.sh:427` writes a reuse-worker ID that `new.*` cannot rebuild. Prefer tmp, fsync, rename, the same pattern `monitor.sh` uses (lines 50–51).
5. **Test 3's fault injection is unspecified.** Name a concrete mechanism, for example a directory pre-created at the `new.N.pending` path, or a read-only launch directory with a restore in `addCleanup`.
6. **Heilmeier:** the objective uses internal jargon (`guard_exit`, `boat-spend --finish`, "hold") and gives no plain-language Impact or Timeline line. Add one sentence each: for example, "a crash during VM creation must never mark a launch's money as settled," and "one offline cycle".
7. **Existing test assertion:** `test_unknown_creation_stays_pending_and_does_not_finish_reservation` asserts the marker exists after the call. Strengthen it so the transport itself checks the marker already exists during the call, as test 1 proposes, so the late-touch deletion is regression-locked.

## What passes

- The problem is real and verified in code.
- The scope is minimal; it reuses the existing marker and deletes the late touch.
- There is no YAGNI machinery.
- The live-path persistence order is correct.
- Exclusive creation with no truncate and no replay is right.
- The cost claims are accurately sourced and properly hedged.
- No section 4 or security change.
- It correctly declares that no Murphy rows close.

**To pass:** resolve Blocker 1 by choosing (a) or (b) explicitly, with a surviving-creator test. Specify the `id` reset (Major 2). Specify kill targets and add the holder assertion (Major 3).

## Elephant response

Accepted B1 (option a), majors 2/3 and all seven nits. Revised design adds resume resolution under controller ownership, explicit residual detached-provider risk, early id reset, atomic IDs persistence and both kill targets plus holder assertions. No blocker rejected. Fresh design review required before implementation.

