# Goldfish design review: `docs/designs/escaped-session-containment.md` (O7), round 2 of 2

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard, implementation-readiness-standard, docs/ENGINEERING.md. This was a read-only review: no edits, no delegation, no live actions and no paid calls.

## Verdict: **BLOCKING** (1 Blocker, 3 Majors, 2 Nits)

The round-1 findings are resolved as written: B1, B2 and M1–M6, plus N1–N3. One new blocker remains. Under the design's rule that each process owns one ledger, an existing child process that makes model calls would be refused. That child is the forked extension-comparison child in `factory/extension_evaluator.py`. Under the rules, implementation stops and returns to the parent. The fix is one design decision, stated below.

---

### B3 — Blocker: the forked extension-comparison child is refused on the parent's ledger
**Scope:** Round-1 resolution lines 102–110 ("exclusive nonblocking flock … for the lifetime of the owning Python process", "A second process for the same ledger refuses while the owner lives", "forked children must not reuse the parent's in-memory owner"). Code involved:
- `factory/extension_evaluator.py:397-415` (`start_child` uses `multiprocessing.get_context('fork')`)
- `:164-183` (`phase_context` copies `c`, so the child keeps `c.ledger`)
- `:224-274` (the child replaces `r._opencode` and makes model calls, including non-isolated ones (`not kwargs.get('user')`))

**What happens:** By the time the comparison child is forked, the parent `run.py` process has usually already made contained writer calls. So it holds `<ledger>.containment.lock`. A child created with `fork` shares the parent's open file description; `O_CLOEXEC`/non-inheritable only matters on `exec`. The design requires the child not to reuse the parent's owner. So the child must acquire the lock itself, and `LOCK_NB` fails because the parent holds it. Every non-isolated call in the child then raises `containment_unavailable`, which is a hard stop. The result is that every case that reaches extension comparison stops. The design does not mention this caller, so the implementer would have to make an architectural choice under the zero-decision rule.

**Required:** state the ownership rule that covers a second process on the same ledger. There are two options.
- **(a) Preferred, and simpler.** Drop the lock that lives as long as the process. Give each call directory its own lock instead: hold a flock on `<call-dir>.lock` (or an fd on the directory) for the whole call, and remove it only after the directory is removed. A "leftover" is any call directory whose lock can be acquired. A poisoned directory also carries a durable marker, and any process refuses dispatch when that marker exists. This works for several processes per ledger (the fork child, a G11 audit run, future helpers). It needs no handoff, and B1 and B2 still hold. One condition: forks must happen only while no call is live. `start_child` already guarantees this; it waits for `active_count()==1` and no `active_model_calls`. State that condition.
- **(b)** Keep the lock that lives as long as the process, and specify a handoff around `start_child`/`close_child`. The parent must be quiescent and not poisoned. It releases ownership before the fork, the child acquires it, and the parent re-acquires and re-checks for leftovers after `close_child`. This also touches `extension_evaluator.py`. That file is outside the design's stated scope, so the design must add it to scope and to the tests.

Either way, add a test with a real kernel. A forked child, on the same ledger, makes a contained call after the parent has made one. Assert that it succeeds, and that a leftover the child creates is found by the parent afterwards.

---

### M7 — Major: leftovers are only checked lazily, at the first non-isolated dispatch
**Scope:** lines 106–107 ("On first acquisition … refuses dispatch").

Here is the sequence. A crash happens after admission and leaves an escaped process. On resume, the first steps may be gate work or isolated-UID calls. Those calls disable containment and never take ownership. The escaped process keeps writing the work directory throughout. If the case finishes without another non-isolated call, nothing ever refuses. Round-1 B1 literally asked only that dispatch be refused. But the Murphy row is about contaminating "the next invocation's work".

**Required:** pick one, and record it:
- (i) every `run_budgeted` entry (isolated-UID calls included) and `resume_ledger` run the leftover check whenever `UNBUG_MODEL_CGROUP_ROOT` is set. This is cheap and needs no change to `run.py`.
- (ii) state this window explicitly in the residual text of the Murphy closure.

(i) is recommended.

### M8 — Major: how the shim is launched is left to the implementer
**Scope:** lines 22–26.

Before enrollment, the shim runs code that is not contained. Its `cwd` is the work directory, which the model writes to, and its `env` is the CLI env filtered by the gate. If it is launched with `-m` or `-c`, `cwd` goes onto `sys.path`. Separately, any `PYTHON*` variable or `site` hook in that env would run before admission. In both cases code runs before enrollment, which is exactly the "admission before enrollment" risk the design names.

**Specify:** `argv = [sys.executable, '-I', <absolute path of bin/processes.py>, <read-fd>, '--', *cmd]`, with `pass_fds=(read_fd,)` and `close_fds=True`. Keep `start_new_session=True`, because `tool_cpu_ticks(process.pid)` (`budget.py:724`) and the progress logic depend on PID == SID. The shim does `execvpe` on `cmd` with the env it inherited. One line in the design closes this.

### M9 — Major: there is no named recovery procedure for a refused scope
**Scope:** lines 107–108, 116 ("retained processes require explicit recovery").

Every crash after admission, and every cleanup failure, now refuses that case permanently. With 24 cases running in parallel and a goal of about one day per case, operators will hit this. With no stated procedure, someone will improvise an `rm -r` or sweep the whole root, and the design forbids both.

**State:** the recovery procedure is manual and covers only this scope:
1. write 1 to `cgroup.kill` for each call directory;
2. wait for `populated 0`;
3. `rmdir` bottom-up;
4. record it in the case card.

Also state that no recovery tool is built in this increment.

### N4 — Nit: the body contradicts the resolution
Lines 16–18 say that synthetic emitters "retain their existing API default" and that ModelRuntime "explicitly asks" for containment. Lines 34–35 say the refusal applies only "in that process". Lines 119–124 and 102–117 override both. The resolution is authoritative, but the diff reviewer will be reading the body too. Delete or strike the stale sentences.

### N5 — Nit: the card stage name is unspecified
Line 114 says the runtime "records the containment error on the card". Name the stage, for example `{'stage': 'model_containment', 'error': <label>}` in `c.card['cleanup_errors']`, so that `final_usage_known` and `router_deferred` (`model_runtime.py:472,529`) behave predictably and the tests can assert on it.

---

### Round-1 findings: resolved
- **B1 (restart):** scopes keyed by the ledger hash, refusal when leftovers exist, no sweep of the whole root, and a SIGKILL test with a fresh owner. Resolved, subject to B3 and M7.
- **B2 (durable refusal):** the scope is poisoned in memory before throwing, the directory is retained even if empty, the error goes to the ledger's `cleanup_errors` and to the card, and it propagates as a hard stop. A fresh process finds the directory even after `resume_ledger` clears `terminal_stop`. Neither `containment_unavailable` nor `cancellation_failed` is in the outage, quota or credential mapping (`model_runtime.py:439`), and `model_call_gate.py:720` keeps `cancellation_failed`. Resolved.
- **M1:** distinct `containment_unavailable` label, `on_started` only after the admission write, `started=False` → `denied`. Resolved.
- **M2:** containment kill and drain happen before the success transaction and at the start of the exception handler, and there is no sudo fallback. One code change is required: the existing codex/claude limit branch, which today keeps the first stop and swallows the cleanup error (`budget.py:1252`), must change so that a cleanup failure becomes `cancellation_failed`, as line 134 says. Resolved as specified.
- **M3:** nested cgroups are removed bottom-up within 5 seconds, with a real nested test. Resolved.
- **M4:** the residual (same-UID deliberate migration and daemon-mediated processes) must be explicit in the Murphy closure text. Resolved.
- **M5:** failure is induced by revoking a non-root UID's write permission on `cgroup.kill`, with root used only for induction and recovery; the negative control is a source-copy edit that is recorded. Resolved.
- **M6:** default on; only isolated-UID calls and synthetic tests opt out explicitly; no config switch in the `user=None` path. Resolved.
- **N1:** the delegated leaf and common-ancestor prerequisite are stated. **N2:** the macOS breakage is stated. **N3:** a timeline of 1–2 days is given. Resolved.

### Checked and fine
- `exam_responder.owner_server` runs nested owner calls in the same process (HTTP threads), so the shared in-process mutex and owner cover it.
- Probe ledgers (`run.py:3237`) live in a fresh `mkdtemp`. They are separate scopes and are never resumed.
- The G11 audit reuses the source case's ledger path, so it falls in the same scope and correctly refuses on leftovers.
- Scope of the change, the launch manifest, no logging of argv or env, and Murphy discipline (close only `new-isolation-settlement-1`, only after real kernel tests and a fresh diff review): consistent with ENGINEERING.md.

**To clear:** resolve B3 by choosing (a) or (b) and adding the fork-child test. Write the M7–M9 decisions into the design.

## Implementer response

Round-2 blocker B3 accepted. Implementation stopped under the user's maximum-two-round rule; no third review requested. Parent must decide the per-call ownership-lock alternative or explicit fork handoff, with a real same-ledger fork regression. M7–M9 and N4–N5 remain design follow-ups. No production change, full suite, diff review, or Murphy closure is claimed.

