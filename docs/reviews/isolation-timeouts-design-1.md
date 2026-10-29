# Goldfish design review: `docs/designs/isolation-timeouts.md`

**Mode:** REVIEW. I read the three personas first (`design_critic.md` came back partly truncated, so its criteria are applied from its role description). I also read `docs/ENGINEERING.md`, `docs/murphy-register.md`, `tools/egm/document_standards/zoom-out-standard.md` and the code the design cites. I ran no cloud commands and decrypted nothing.

**Verdict: FAIL.** There are 5 blocking findings, 5 major findings and some nits. The row accounting is mostly honest about what stays open. The blockers are about closing 31, 44 and 46, and about two new pit stops the design would introduce.

---

## Blocking findings

### B1. The design edits `bin/` bench files, which changes the bench fingerprint. It doesn't say so.
**Scope:** Changes 2 and 5, "Route bench.command, strategy checkpoints…".

- `bin/bench.py:89` (`command`) and `bin/strategy:121` are not under `factory/`.
- `run.bench_manifest()` (`factory/run.py:177`) hashes every file except `factory/`, `results/`, `sealed/` and a few others. `bin/` is included.
- Editing those files changes `bench_sha`. That value is checked by:
  - `--resume-bench-sha` (`run.py:2476`);
  - the reused-worker fingerprint check (`launch.sh`, "reused bench fingerprint changed");
  - G11/carry-over `review_bench_sha256` (`g11_review.py:139`, `carry_over.py`);
  - the run identity at `run.py:1397`.
- So for the restored October 29 cases, this change would refuse resume or invalidate cached evidence. That contradicts the target "plumbing rolls onto running cases" and "re-run only changed gates" (ENGINEERING §3), and the rule that plumbing and bench logic are separate (§4).
- There is also a layering problem. `bin/` is the library that `factory/` imports. Having `bin/bench.py` or `bin/strategy` import `factory/processes.py` points the dependency the wrong way. The worker may not have `factory/` on `sys.path` when `bin/strategy` runs.

**Guidance:** Choose one of these and write it into the design.
- (a) Leave `bin/` untouched. Have `run.py` run `bin/strategy`, `bin/checkpoint` and the like through `processes.run` with a deadline and group kill. The inner calls then die with the outer group.
- (b) If `bin/` edits are unavoidable, state that `bench_sha` changes. State the migration for in-flight and restored cases. Add a test on a real restored card that shows resume and the gate cache still behave.

Option (a) is preferred.

### B2. The Boat pin doesn't cover the production control VM, so row 31 cannot close.
**Scope:** Change 5, Row 31.

- Production control services set `BOAT_CMD=/usr/local/bin/boat` and `BOAT_NO_UPDATE=1` (`control/unbug-key-holder.service:11`, `unbug-resume-launches.service:12`).
- The design says `BOAT_CMD` stays "an explicit transport override for Hetzner and offline tests" and only "also gets BOAT_NO_UPDATE=1".
- Read as written, the `--version` pin applies only to the `~/.ascii/bin/boat` or PATH branch, which is the Mac. The control VM, whose job is to own the batch (§4 "No Mac dependency"), would run unpinned.
- 1.0.85 was observed only on the Mac. The design says nothing about what `/usr/local/bin/boat` reports on the VM. If it differs, every call fails at the pin check.
- Row 31's fix text also says "retain bounded schema-compatible parsing". The design doesn't address that.

**Guidance:**
- Apply the version check to any resolved executable that is real Boat, including a `BOAT_CMD` set to a `boat` binary. Skip it only for `hcloud-boat` and test fakes. Name the discriminator.
- State the VM's expected version and who verifies it.
- Either add a schema-compat test for the parsed fields (`creditBalanceSeconds`, `sandboxes` / `pageInfo.hasMore`) or mark 31 partial.
- Zsh-function removal itself is fine. I read the function in `~/.zshrc`. It only exports `BOAT_CURRENT_ID*` state and doesn't affect launcher calls that pass an id explicitly.

### B3. The reservation ledger can leak forever, which creates a new pit stop.
**Scope:** Change 6, Row 17.

- "Never silently expires a reservation… release only on verified completion" has no recovery path. If a launcher dies without running `--finish` (kill -9, host loss, the Mac failures that row 19 documents), its reservation lives forever. Every later admission on that host then shrinks, and the founder has to hand-edit JSON. That is exactly what the target properties forbid.
- A natural release bound exists. Each record carries `ttl_seconds`, and Boat TTL erases the VMs. After `started_at + ttl + margin`, a reservation can be released by an explicit, logged reconcile step that is not silent.
- Other gaps:
  - **No ledger format.** The path (`$UNBUG_CONTROL_HOME/…`) and schema are not named.
  - **Refused checks.** The current `--check` writes a record even when `allowed=false`. The design must say a refused check reserves nothing.
  - **Hetzner.** `HETZNER` mode has no balance, so the ledger is moot there.
  - **Separate ledgers.** The ledger is per host. Mac and control-VM launchers draw on the same Boat wallet but would hold separate ledgers. Say so, and don't claim the race is closed across hosts.
  - **Unclear on closing 17.** "17 can close with concurrent real-shape receipts" is conditional. Decide it: closed, or partial with the per-host limit stated.
  - **Test input.** "Real billing response shape" needs a saved real `boat billing --json` receipt committed as a public fixture. Name it. A shape generated by the test proves nothing (§4 "Real artifacts").

### B4. The runner-supervisor retry rules contradict how Python and the resume path actually behave, and the controller side is unspecified.
**Scope:** Change 4, Row 46.

- "Syntax, usage status 2 … prevents blind retry" is wrong. A Python `SyntaxError`, `ImportError` or missing dependency exits with status 1, which the design defines as retryable. Row 32 records two real launches that failed on missing host dependencies, so this is a real case. Retrying it is bounded and wasteful, not unsafe, but the design's stated classification is false. Either gate retry on the supervisor's own phase marker (before or after interpreter import), or accept the retry and say so.
- "Only while no case work/ledger exists" can never be true for an in-place restart. The in-place path requires `test -d ~/work/$resume_case/case` and `~/sealed/$resume_case.continuation-budget.json`, and it deletes `DONE`. The design says to wrap the in-place runner but gives it no retry. State that explicitly, along with what a failed in-place startup then does.
- These items are left to the implementer:
  - "bounded delay" has no value;
  - how "work/ledger exists" is detected;
  - the `reason` field, which must be a closed enum. Free text can carry secrets from the discarded stderr.
- The controller side is missing. Nothing says where `STARTUP_FAILED` is read (the `guard_wait` probe in `bin/boat-launch-guards.sh` around lines 275–337), how it avoids a fake case `DONE`, or how `collect.sh`'s probe/startup exception (row 25) handles it. Nor does it say what happens to the case afterwards. Target property 2 says infrastructure failures are retried and never scored, and replacement belongs to stream B. Say that this increment retires the worker and records the case as unstarted.
- Runner-already-running guards match the process command line: `launch.sh:346` uses `^python3 [^ ]*/factory/run.py( |$)`, and `launch.sh:545` and `resume-in-place.sh:35` use `^python3 .*factory/run.py`. A supervisor command line (`runner_supervisor.py -- python3 …/run.py`) fails the stricter regex during the retry delay, leaving a window with no guard. List and update these guards.

### B5. The closure claim for row 44 isn't scoped or tied to the real call sites, and the "every child in a new session" rule conflicts with existing code.
**Scope:** Changes 1–2, Rows 43/44.

- Row 44 is the same bug class as row 43. The design closes 44 and leaves 43 open "until all direct subprocess callsites use remaining-time bounds". Close 44 only for named sites, which are `bin/strategy:121` and `run.py:165`. State that scope. The closure test must drive those actual code paths, `bin/strategy`'s `Environment.exec` / `silent_checkpoint` and `run.sh()`'s serial branch, with a hung shell and a surviving descendant. A unit test of `processes.py` alone proves the helper, not the row. The listed "descendant death" tests don't say which entry points they exercise.
- `bin/strategy` currently honours `UNBUG_DIAGNOSTIC_PROCESS_GROUP=1`. When it is set, the silent-window watcher is deliberately not given its own session. The design says "every child starts in a new session". Say how this opt-out is preserved, or why it can go, and test it.
- "Kill remaining descendants on successful parent exit too" is a behavior change for every routed call site. The design should list the routed sites and confirm none intentionally leaves a background process in the group. Examples are the watcher, `docker compose up -d` clients and `iptables` helpers.

---

## Major findings

**M1. The deadline model has three channels and contradicts itself.**
- The effective deadline is the minimum of the `timeout=` argument, a ContextVar and the inherited `UNBUG_PROCESS_DEADLINE`. Seal and wipe are said to get "independent" 600/120 s deadlines. But `deadline()` nests with the earlier one and the env var is inherited, so a seal run inside or under a spent gate context cannot be independent unless there is a root or reset form of the context. Define it.
- State that `run.py` never writes the variable into its own `os.environ`. If it did, seal could never escape a spent deadline.
- ContextVars do not propagate into `ThreadPoolExecutor` threads (`gate_pipeline.py:156+`). "Independent thread contexts" is tested, but propagation into helper threads started inside a gate is not. Gates 13–15 would then silently lose their deadline.
- Simplification (zoom-out): the explicit `deadline=` argument plus the env var for child processes is enough, and the ContextVar is the part to question. If it stays, justify it.

**M2. `launch.sh` isolation has a `set -e` pitfall the design must pre-empt.**
- The loop is serial: `guard_new`, setup, detach, then `guard_wait once`. The design is right to keep `guard_new` in the parent.
- If the isolating subshell is called as `if ! ( … )` or `( … ) || …`, `set -e` is disabled inside it. A failed upload or pin would then fall through and the runner would still be started. Require the form `( set -e; … ); rc=$?` outside any condition, or an explicit `|| exit` per step.
- Also specify:
  - the per-worker state-file name and format;
  - that a failed worker is collected or wiped before deletion (it may already hold keys after `push-secrets`);
  - the pin and qualification retry steps. "Idempotent pin/qualification commands (maximum two attempts)" does not say which of lines 586–610 they are.
- The regression test must make the real shell reach a failing step with a healthy peer. A fake transport that fails after the runner start would not prove it.

**M3. The responder change names no file, and the contract hash isn't discussed.**
- `harbor/responder/responder.py` holds the request parsing, with `rfile.read(length)` and no size bound. It is shared with the Harbor task environment, and it already uses `ThreadingHTTPServer` in its own `main`.
- `exam_responder.py` holds the `HTTPServer` and the owner call.
- `contract()` hashes `exam_responder.py`, `responder.py` and `ask-human` into `code_sha256`, which binds certification. Editing them changes that hash. Say which certified cases are affected and what happens to them.
- The nonblocking owner lock returning 503 is a behavior change. The `ask-human` client's handling of 503, and whether a tester ever issues concurrent asks, are not stated.
- "Bound connections at 5 seconds" must say per-read idle timeout versus total request-read deadline. A trickling client defeats the former. It must also not apply to the up-to-120 s owner model call.

**M4. The tests depend on inputs the offline suite may not have.**
- The "real October 29 restore control-home `launch.json`, `monitor.sh`, `new.*` and worker-release receipts" and "public case scorecards" have no committed paths. `tests/run.py` is offline and runs on other checkouts.
- Name the committed public copies under `tests/factory/fixtures/`, or the exact read-only source paths and a skip rule. A test that silently skips would break the "closed by a test" rule. Also list the existing tests expected to change ("updated for direct pinned executable discovery") instead of leaving them open-ended.

**M5. The "first increment" is seven changes across about eight modules.**
- It spans `processes.py`, `runner_supervisor.py`, `run.py`, `launch.sh`, `boat-call`, `boat-spend`, the responder, `bin/` and the gate pipeline.
- It is reviewable only as a bundle, and the diff review will be large. I'd split it into four independently mergeable pieces:
  - (a) `processes.py` plus the `sh()` replacement;
  - (b) the supervisor plus `launch.sh` isolation;
  - (c) the Boat pin plus the spend ledger;
  - (d) the responder.
- Each would carry its own row closure. This is a recommendation, not a blocker.

---

## Nits
- Note whether `processes.py` is extracted from the existing group-kill code in `sh()` (`run.py:150–165`) and `model_runtime`. The design says duplicated cleanup is deleted but doesn't name the survivors.
- Enumerate the readers of `actual_spend_usd` before making it null.
- The Boat version observation can't be reproduced by a reviewer. Record the `--version` output as a receipt or test fixture.

---

## Murphy row accounting (explicit partial-row check)

| Row | Design says | Verdict |
|---|---|---|
| 18 (peer isolation) | Leave open; replacement belongs to stream B | **Correct.** Keep `open`. Say "partial" in the commit. |
| 42, 43 | Gate deadlines and named paths only; open | **Correct.** Keep `open`. |
| 49 | Honest observations; open | **Correct.** Keep `open`. |
| 28, 29, 30, 32, 37, 45, 50 | Explicitly left open, with reasons | **Correct.** The "do not invent a digest or pagination API" caveat is good. |
| 17 | "Can close" with concurrent real-shape receipts | **Premature.** Blocked by B3 (leak rule, per-host scope, real fixture). Decide partial or closed. |
| 31 | Targeted closure | **Cannot close** until B2 is fixed. Also missing schema parsing. |
| 44 | Targeted closure | **Cannot close** until the B5 call-site scope and test are fixed. |
| 46 | Targeted closure | **Cannot close** until the B4 controller side, retry classification and in-place semantics are fixed. |
| 52 | Targeted closure | Plausible once M3 names the files and the hash impact. |

None of the "remains open" claims overstates closure. The risk is that the four target closures (31, 44, 46, 52) and the conditional 17 are asserted more strongly than the design supports. At merge, the diff goldfish must check that each `Closed by` path drives the real code path, per ENGINEERING §2.

## What is solid
- The scope boundary is explicit: no stream A/C/B work, no key or trust changes, no cloud or decrypt needed to validate.
- It deletes interactive zsh Boat discovery and balance-delta-as-spend labeling, as "delete before adding" asks.
- It honestly refuses to claim the replacement portion of row 18.

## Re-review
Fix B1–B5 in the design, and resolve or reject M1–M4. Then send it back to a fresh goldfish. Per ENGINEERING §1, a rejected blocking finding goes to a second goldfish from a different model family.
