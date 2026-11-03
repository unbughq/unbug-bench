# Goldfish design review: `docs/designs/escaped-session-containment.md` (O7), round 1

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard, implementation-readiness-standard. Read-only. I made no edits, started no subagents and took no live actions.

## Verdict: **BLOCKING** (2 Blockers, 6 Majors, 3 Nits)

The core mechanism holds up. The pieces are: a fresh cgroup for each call; an exec shim that is held on a pipe until it is admitted; writing to `cgroup.kill`, then waiting for `populated 0`, then removing the cgroup; and refusing when there is no delegation. This is the right primitive for the setsid/double-fork escape in `new-isolation-settlement-1`. It needs no ancestry scan. The admission ordering in lines 22–26 is sound:
- `exec` keeps the PID, so `process.pid`, `tool_cpu_ticks` and the wait/reap logic stay valid.
- The shim cannot be reaped before it is enrolled, so its PID cannot be reused.
- EOF on the pipe stops execution if the parent dies before admission.

The design fails in two places. Containment ends when the runner process ends. And the refusal after a cleanup failure is not durable, even though the doc says it is.

---

### B1 — Blocker: escapees outlive a runner crash, and resume does not find them
**Scope:** lines 25, 34–36, 40–44. Also `factory/budget.py:771-785` (`resume_ledger`), §4 "One launch path" (a resume is a launch from a checkpoint).

The design covers parent death *before* admission only. Suppose the runner dies *after* admission, from SIGKILL, OOM, a VM restart or a supervisor kill. Nobody writes `cgroup.kill`. The escaped descendant keeps running in its orphaned cgroup below `UNBUG_MODEL_CGROUP_ROOT`. The factory then resumes the case from its checkpoint into the same work directory, and this is the standard launch path. That is exactly the contamination the row describes, and nothing in the design detects it. The cgroup is the *only* durable record of ownership. Doing nothing with it at startup gives up the property the design exists to provide.

**Required:** state the startup rule. Before the first non-isolated dispatch, any non-empty (or any leftover) cgroup under this runner's namespace must be killed and drained, or must make dispatch refuse. That forces a decision the doc currently skips: how cgroups are named per runner or case. 24 cases run in parallel and may share one delegated root. A sweep of the whole root would kill sibling runners' live calls. Something like `<root>/<case-or-runner-id>/<random>` is needed, and the doc must say who may sweep what. Add a real-kernel test: kill the owner process after admission, start a fresh owner, and assert that the escapee is killed, or dispatch refused, before the sentinel runs.

### B2 — Blocker: the "durable" refusal after cleanup failure is neither durable nor on the path ModelRuntime checks
**Scope:** lines 33–35. Also `factory/budget.py:1338-1342`, `factory/budget.py:771-785`, `factory/model_runtime.py:394,472,529`.

The doc says a failure "durably records cleanup_errors" and that "later model dispatch in that process must refuse." Current code shows three problems:
1. `_run_budgeted` writes `cleanup_errors` to the **ledger**. ModelRuntime's `final_usage_known` and `router_deferred` count **`c.card['cleanup_errors']`**. Nothing reads the ledger's `cleanup_errors`. On an error path, for example `cancelled`, `stalled` or `process_error`, a containment failure is appended to the ledger and the original error is re-raised. The router's retry logic never sees it.
2. `resume_ledger` archives `terminal_stop='cancellation_failed'` into `previous_stops` and clears it. A resumed run then dispatches with nothing stopping it.
3. A latch kept only in memory ("in that process") disappears on restart. Meanwhile the retained non-empty cgroup, which the doc deliberately keeps "for diagnosis", may still hold a live escapee.

**Required:**
- Say where the refusal latch lives, for example a module flag in `processes.py` that the containment entry point checks before `Popen`.
- Say what durable state makes a *later process* refuse. B1's startup check finding a retained non-empty cgroup is the natural answer.
- Say whether the failure must also be recorded on `c.card['cleanup_errors']`, so that `router_deferred` stops retrying.
- Change the test on line 68 to cover a new process too, not just the next call in the same process.

### M1 — Major: refusal before admission has no error label or accounting outcome
**Scope:** lines 14–15, 24–25. Also `factory/budget.py:1175-1177,1217-1218`, `factory/model_runtime.py:419-426,433-439`.

If enrollment fails and the shim exits without running the CLI, current `run_budgeted` reports `returncode != 0`, which becomes `process_error`. ModelRuntime maps that to `failure={'reason':'outage','per_call':True}`, which excludes the route and **retries another route**. That is a refusal loop dressed up as an outage. The doc must specify:
- a distinct `BudgetError` label, for example `containment_unavailable`, raised by the owner rather than taken from the shim's exit code;
- that `on_started` fires only after the admission byte is sent, so `model_process_state['started']` stays False, the outcome is `denied`, and the reservation is released rather than settled as invoked;
- that the label is not in ModelRuntime's outage, quota or credential mapping, so it propagates as a hard stop.

### M2 — Major: the order of kill and ledger settlement inside `_run_budgeted` is not specified, and today it is the wrong way round
**Scope:** lines 28–31. Also `factory/budget.py:1220-1225,1305-1320,1328-1344`.

The doc says to kill and drain "before … allowing invocation cleanup/settlement to finish." In current code, the success path writes `terminal_stop='complete'` and removes the invocation from `active` *before* the `finally:` calls `stop_process()`. Every error path other than the codex/claude limit errors also writes `terminal_stop` and the `active` removal in the `except` block before the `finally`. Other concurrent invocations, and readers of the ledger, can therefore see the call as settled while its cgroup is still populated.

**Required:** state either:
- that contained cleanup runs before those ledger transactions on every path, which means moving the kill ahead of the success transaction and the `except` settlement block; or
- that the existing ordering is accepted, with a reason why a ledger saying `complete` while the cgroup is still populated is harmless. Note that the case is overwritten to `cancellation_failed` only when `original is None`.

Also say plainly that `stop_process()` is replaced by the containment kill for contained calls, and that the `sudo kill` fallback for EPERM is unreachable for `user=None`.

### M3 — Major: removing nested cgroups is unspecified, and a plain `rmdir` fails
**Scope:** lines 29, 37.

The doc correctly says the kill reaches nested cgroups. But a descendant may `mkdir` child cgroups, and `rmdir` on the per-call directory returns EBUSY while any child directory exists, even an empty one. Under the doc's own rule, that turns an ordinary run into a "cleanup failure" and a permanent refusal. Specify: after `populated 0`, remove the directories bottom-up, all inside the same 5-second limit. Add a test where the descendant creates a nested cgroup.

### M4 — Major: the threat-model wording mislabels the main residual risk
**Scope:** lines 41–43.

The actor that can migrate tasks through a writable cgroupfs is not a "hostile administrator". It is the model CLI's own descendants: writer and attacker agents running a shell under the runner's UID. Delegation makes `UNBUG_MODEL_CGROUP_ROOT` writable by that UID. So `echo $$ > <root>/<other-leaf>/cgroup.procs`, or a write into the runner's own leaf, escapes `cgroup.kill` in one command. The model can see `/proc/self/cgroup`.

This does not block closing the setsid/double-fork row. But the doc and the Murphy `Closed by` text must state the residual exactly: same-UID deliberate cgroup migration is out of scope, and it is left to isolated-UID calls. Optionally, name the cheap mitigation that also exists, such as running the model in a cgroup namespace or with a read-only cgroupfs view. A diff reviewer must not let the closure claim cover deliberate escape.

### M5 — Major: the cleanup-failure test and the negative control have no stated mechanism
**Scope:** lines 59, 67–68, 70.

Line 59 forbids mocking membership, kill or population. Line 68 requires a test of cleanup failure. On a real kernel, `cgroup.kill` almost never fails, and inside Docker the test runs as root, so a `chmod` does not stop the write. The doc must name the real failure it will induce, for example an unwritable `cgroup.kill` as a non-root delegated user, or a nested cgroup left behind (see M3), or a limit too short against a real process stuck in D state. Otherwise the implementer chooses the failure, and may choose a mock.

The negative control on line 70 ("removing cgroup.kill") also needs a mechanism: a temporary local code patch, recorded in the evidence. It must not be a flag or environment switch, because the doc rules out an opt-out.

### M6 — Major: the opt-in flag with a default-off value keeps the deleted path reachable from production
**Scope:** lines 16–18, 50.

The only production caller of `run_budgeted` is `factory/model_runtime.py:663`. Every other caller is a test. If containment is a parameter that defaults to off, the `killpg` path survives as the default for any future production caller. That conflicts with "delete before adding" and "one launch path". Prefer one of:
- default **on**, with the synthetic budget tests passing an explicit, test-named off value; or
- a required keyword with no default.

Either way, "no process-group fallback" then holds by construction rather than by every caller remembering to opt in.

### N1 — Nit: delegation preconditions for migration
**Scope:** lines 13, 40, 44.

Under cgroup v2 delegation, the writer needs write access to `cgroup.procs` in the common ancestor of the source and destination cgroups. In practice the runner itself must live inside the delegated subtree, in a leaf that is not the root, because of the no-internal-processes rule. A Docker container running as root with a private cgroupns does not exercise this. The behaviour is fail-closed, which is good, but name this prerequisite so the pilot's provisioning step is unambiguous.

### N2 — Nit: macOS refusal
**Scope:** line 45.

Confirm that no current local Mac flow, such as a smoke run, dispatches non-isolated CLIs. If one does, list it as an expected break. Section 4 already rules out depending on the Mac, so this is about telling people what breaks.

### N3 — Nit: Heilmeier coverage
Objectives, current practice, approach, risks, cost ("one offline increment") and exams (real-kernel tests plus the negative control) are present. A timeline is missing. A one-line estimate would satisfy the standard.

---

### Checked and fine
- **Admission race:** the shim is blocked before `exec`. A non-inheritable `os.pipe()` passed via `pass_fds` (not `preexec_fn`) avoids leaks into other threads' children. The PID is written before the admission byte. EOF on the pipe means exit. All sound.
- **Separation between concurrent calls:** a random directory per call is enough within one runner. Across runners, see B1 on namespacing.
- **Scope:** `run.py`, diagnosis, holder, isolated-UID cleanup (`sudo pkill`, lines 689–691), gates and budgets are untouched. This matches O7, which explicitly excludes live UID and real-CLI acceptance.
- **No logging of argv or environment** by the helper; `processes.py` is already in the launch manifest (`factory/launch_manifest.py:28,81,180`).
- **Murphy discipline:** the doc closes only `new-isolation-settlement-1`, and only after real kernel tests and a fresh diff review. The row stays open if the kernel tests cannot run.

To clear the block: fix B1 and B2 (containment and refusal that survive a runner restart, with per-runner cgroup namespacing), and specify M1–M5 in the doc. M6 is strongly recommended.

## Implementer response

All findings accepted; no blockers rejected. The design's Round-1 resolution specifies stable per-ledger scopes, lifetime ownership locks, restart refusal, durable leftover directories, error/card propagation, pre-settlement cleanup, nested removal, the precise migration exclusion, real permission fault injection and source-edit negative control. Fresh round-2 review requested.

