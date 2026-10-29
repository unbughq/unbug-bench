I'm returning **BLOCKED**. The design can't meet the brief as written: waiting for a reset gets the worker killed, and two of the six rows (4 and 20) are deferred.

# Goldfish review: `docs/designs/router.md` (design review 1)

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. I read the design, `docs/ENGINEERING.md`, `docs/murphy-register.md` (rows 2, 3, 4, 20, 47, 48), `docs/factory-single-path.md`, and the referenced code in `factory/`, `bin/boat-launch-guards.sh` and `factory/README.md`.

## Findings

### 1. Blocker: waiting inside a call conflicts with the worker watchdog, worker lifetime and recovery counters
- **Scope:** design lines 51–53 and 61–62; rows 2, 47, 48.
- **Finding:** the design waits inside `ModelRuntime.call`, on the worker, for up to the full Claude reset, which can be more than 6 hours. Three existing mechanisms break this:
  - **Stall watchdog.** The launcher collects and deletes a worker after 20–45 minutes with no change to `~/work` or the ledger (`bin/boat-launch-guards.sh:21`, `factory/README.md:258-260`). A worker that is waiting changes neither, so it gets reaped.
  - **Worker lifetime.** The worker's TTL is about 8 hours (`launch.sh:4`). It expires during a long wait. Meanwhile an idle VM is paid for and holds a parallel slot.
  - **Enclosing deadline.** Line 52 says the wait never extends an explicit enclosing deadline. So the call fails with `BudgetError('timeout')`. `recovery.RETRY` matches `timeout`, and `restart.plan` then uses one of its 3 retries (`restart.py:57`).
- **Effect:** the brief's "no recovery or round consumption while waiting" and "real reset waiting" are not met for any wait longer than the watchdog or the deadline. `factory-single-path.md:61` already chose a different model: checkpoint, release the worker, and re-queue for the reset.
- **Action:** pick one model and specify it.
  - (a) Waiting writes a progress heartbeat the watchdog accepts, and the worker TTL is extended or the wait is capped. Say what happens at the deadline: a provider-wait stop that does not count as a retry.
  - (b) A wait longer than N minutes checkpoints and stops with `provider_limit`. `restart`/`recovery` then skip the retry increment for that stop and re-launch at the router's reset time.
  - Either way, add a test that a wait longer than the stall threshold neither kills the worker nor uses a retry.

### 2. Major: the brief is not fully met (scope deferral)
- **Scope:** lines 97–103 and 119–122.
- **Row 20** stays open explicitly. The reasoning is sound under the closure rule, but the brief asks for row 20.
- **Row 4:** the register's fix includes "Schedule ticks". `coordinator_inventory.py:8` says "No command installs a recurring job", so the "existing control VM supervisor" the design hands tick scheduling to does not exist for coordinator ticks. Row 4 cannot close under this design.
- **Integration:** "Parent integrates this module into the control-VM batch startup" (line 93) means this change does not itself make every factory call go through the router in a real batch.
- **Action:** say plainly that rows 2, 3, 47 and 48 are in scope, and rows 4 and 20 are partial or open. Either bring tick scheduling and the startup integration (the systemd unit plus launcher wiring) into scope, or get the founder to accept the deferral.

### 3. Major: two account-switching mechanisms remain
- **Scope:** lines 75–85.
- **Finding:** the router switches Claude accounts inside one call, using both tokens on the worker. `account_handoff.choose/apply/prepare/parked` still swaps accounts after a `provider_limit` stop through push-secrets. The design edits the handoff's blacklist logic instead of deleting the handoff path. If limits are absorbed inside the call, the handoff path becomes dead or a competing path. This breaks ENGINEERING §4 ("Delete before adding", "One launch path").
- **Action:** delete the handoff logic for provider-limit stops (`choose`, `apply`, the pending/applying markers, the limit branch of `parked`, and the `*_account_handoff` flags in `restart.plan`). Keep only the label and credential transport (`ACCOUNTS`, `worker_resume`, `exports`). List the deletions.

### 4. Major: the router duplicates the coordinator's account-capacity state
- **Scope:** lines 38–46 and 68–70; `coordinator.py:85-108`.
- **Finding:** the coordinator already validates per-account `capacity`, `used`, `available` and `blocked_until`. `factory-single-path.md:33` says "A single coordinator queues work and leases account capacity". The router adds a second source of truth for the same fields. The design says only that the coordinator "accepts router observations".
- **Action:** state which one owns capacity and cooldown. Recommended: the router owns them, and the coordinator reads router status in place of its own account rows. Delete the coordinator's operator-quota fields and the 3600-second check rather than adding an alternative source next to them.

### 5. Major: sending both Claude tokens to every worker changes a security property, and the founder isn't asked
- **Scope:** lines 78–81; `launch.sh:241-244`; `key_holder.py:34`.
- **Finding:** today only one factory Claude token goes to each VM. Sending both widens what a compromised worker exposes. ENGINEERING §1 requires founder sign-off when a design changes a security property. The design does not flag this.
- The design also says "account 1 then account 2", but `ACCOUNTS` and `CLAUDE_ACCOUNTS` define three factory labels (`claude-token`, `claude-factory-token-2`, `claude-factory-token-3`). The single-path evidence (line 107/116) says accounts 2 and 3 are not yet proven to be distinct capacity.
- **Action:** name the two exact labels and drop label 3 from the allowed set, or say it is kept. Ask the founder to sign off on two tokens per worker. Add a test that the exam token (`claude-token-2`) can never reach a lane.

### 6. Major: worker-to-router connectivity is left to the implementer
- **Scope:** lines 21–23.
- **Finding:** workers are separate VMs, so a loopback-by-default server is unreachable from every worker. The design leaves "VM private network or a TLS reverse proxy" open. It also doesn't say how the token is created, where it is stored on the control VM, how it reaches workers (which secrets entry, which `push-secrets` label), or how it rotates per batch.
- **Action:** fix the deployment: the bind address, the transport, the secret label and the delivery step in `launch.sh`, plus the unit or service name and how it is started and restarted.

### 7. Major: "router mode is configured" implies a second, non-router path
- **Scope:** lines 49 and 80–81, compared with 91–92.
- **Finding:** "when router mode is configured" and "a local SQLite adapter … control-VM callers only" leave room for a non-router path or a direct-store path. That contradicts "every factory call" and "missing configuration fails". It is also the kind of mode flag ENGINEERING §4 forbids.
- **Action:** have no mode. Every caller uses the HTTP client, including callers on the control VM. Tests run the real server on loopback. Delete the adapter, or restrict it to test injection only and say so.

### 8. Major: failure classification and retry bounds are not specified
- **Scope:** lines 54–58 and 123–125; row 48.
- **Finding:** "classified startup/outage, removal or refusal errors" has no classification table: which CLI exit, stderr or stream-JSON patterns per driver (claude, codex, opencode) map to limit, outage, removal, refusal or other. A content refusal re-entered "on the same family" repeats deterministically until the deadline, with nothing bounding it. The 60-second preflight conversion to `provider_preflight_failed` (`run.py:237`) is not addressed. Lease length is undefined when `deadline` is None, which is the timeout-only case (`model_runtime.call` accepts both).
- **Action:** add the table, a per-call retry cap for refusals, what preflight does on outage, and the lease rule when there is no deadline.

### 9. Major: lane capacity is not grounded in evidence
- **Scope:** line 28 ("capacity (initially one)").
- **Finding:** the target is 24 cases in parallel. With one lane per Claude account, two Claude calls can run batch-wide. `factory-single-path.md:116` says to test 2 per account. Nothing gives the source of capacity values (a config file? the batch record?) or how they change without a code edit.
- **Action:** name the config location and the starting values with their evidence, and say whether a change applies at the next checkpoint (ENGINEERING §3, plumbing roll-on).

### 10. Major: the change to `restart.plan` is under-specified
- **Scope:** lines 82–83; row 2's fix: "Wait for reset before consuming another attempt".
- **Finding:** the design replaces the delay calculation, but `retries < 3` still counts every restart, provider-limit restarts included. The brief requires that waiting never uses a recovery attempt.
- **Action:** state that `provider_limit:*` and router-wait stops do not count toward the 3-retry cap, or remove the cap for them, bounded by the batch deadline and spend. Test it with a real limit card.

### 11. Major: the native DeepSeek route is assumed to work
- **Scope:** line 30; row 3.
- **Finding:** `PROVIDER_ROUTES` was added on 2026-10-26 to send DeepSeek to OpenRouter (`I/2026-10-26-deepseek-openrouter/report.md`). The design does not show that the native `opencode/deepseek-v4.1-flash-free` route is available today. It also doesn't show that `family()` maps `opencode/…deepseek` and `openrouter/deepseek/…` to the same family, or that `token_prices` prices the paid route. Without that, "same family" and "spending remains intact" are asserted, not shown.
- **Action:** cite the evidence, or make OpenRouter the primary route with the native route as an optional first try. Add family and price assertions to the row 3 test.

### 12. Nit: altitude
- **Scope:** lines 44–46 and 63–64.
- **Finding:** "uncertain finish is retried before another call" and "deterministic small request jitter" are fine as they are. The design is otherwise at the right altitude and stdlib-only. `exam_responder.py` and `tools/factory_dashboard.py` already use stdlib HTTP or sqlite, so the pattern is consistent.
- **Action:** none.

### 13. Nit: the review-record path differs from ENGINEERING.md
- **Scope:** line 131.
- **Finding:** `router-{design,diff}-N.md` is the right form. Also list each review file in the merge commit's `Reviewed-by:` trailers.
- **Action:** none beyond that.

## Requirement coverage

| Requirement | Status |
|---|---|
| One small shared control-VM router for every factory call | Partial: deployment and integration are deferred (#2, #6, #7) |
| Approved same-family fallback | Covered; DeepSeek is unproven (#11) |
| Two Claude accounts, never the exam token | Partial: labels are ambiguous and the security sign-off is missing (#5) |
| Real reset waiting | Fails: watchdog, TTL and deadline (#1) |
| Role independence preserved | Covered (lines 33–34) |
| Shared health and credits | Covered in design; duplicates the coordinator (#4) |
| No recovery or round use while waiting | Fails (#1, #10) |
| Expired cooldowns clear | Covered (line 66) |
| Rows 2, 47 | Blocked by #1 and #10 |
| Rows 3, 48 | Achievable once #8 and #11 are fixed |
| Row 4 | Deferred: no tick scheduler exists |
| Row 20 | Deferred: stays open |

**Scope deferral:** yes, it prevents meeting the brief. Rows 4 and 20 cannot close, and production integration is handed to the parent.

## Verdict: BLOCKED

Blocker #1 is open. Majors #2–#11 should be fixed or put through the second-goldfish rejection process before implementation starts.


## Elephant response

Revised design: short heartbeat waits; long waits checkpoint as provider_limit without recovery-count consumption; writer receipt after admission; one shared router authority with existing single-token push transport; mandatory authenticated TLS client and service/timer wiring; explicit error labels, bounded refusal and leases. Native DeepSeek is an availability probe with real paid ledger evidence. Added host-only Codex renewal via the existing keyswap implementation. Row closure still requires real evidence. Fresh review requested; no findings rejected.
