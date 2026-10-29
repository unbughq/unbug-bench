**BLOCKED.** Mode: REVIEW. Fresh, read-only review of the revised design, prior review, ENGINEERING, target Murphy rows, and referenced implementation. No files changed or code executed.

The revision fixes several prior design objections, but the long-wait continuation, credential delivery, and failure-classification contracts remain incomplete.

1. **Blocker — Long-wait continuation depends on an unresolved stream-B interface.**

   Scope: `docs/designs/router.md:68–79,106–113,140–143`; rows 2, 4, 47, 48.

   The design promises to implement the coordinator/restart/launcher bridge “without editing stream-B files,” while leaving batch startup and cross-TTL continuation to stream B. The referenced coordinator does not yet provide the promised behavior:

   - `factory/coordinator.py:225` independently stops after three launch actions.
   - Lines 241–278 independently select accounts and check capacity and quota.
   - `factory/coordinator_inventory.py:110–165` derives account occupancy from whole workers.
   - `factory/key_holder.py:516–518` refuses fresh-worker checkpoint restores using the control identity.
   - Inventory dispatch requires an explicit fixed job; adding a timer does not create fresh-case ownership or enumerate pending router requests.

   Removing the launcher/restart retry increment and changing inventory’s data source does not remove these barriers.

   **Required:** identify the concrete stream-B prerequisite and merge order, the files each stream owns, and the interface binding a pending request to its authenticated checkpoint, job, retirement proof, original batch deadline, and retry time. Specify removal of coordinator account scheduling and exclusion of provider waits from its launch allowance. Prove the combined timer → retirement → fresh-worker continuation path before claiming these rows closed. Do not describe that dependency as already implemented.

2. **Blocker — Moving the writer receipt after admission does not cover limits discovered during execution, and other recovery reservations still precede admission.**

   Scope: design lines 63–97,178–180; rows 2 and 48.

   A healthy lane can admit a writer and then discover a provider limit. At that point `before_attempt` has already created `repair_pending`. If subsequent admission requires a long wait, the design checkpoints that receipt; `factory/run.py:972–973` then rejects its resume as `interrupted_repair`.

   Separately, stress recovery appends `release_review_attempts` and increments `rereviews` before calling the runtime (`factory/run.py:1119–1134`). A pre-admission wait can therefore still consume a recovery allowance.

   **Required:** define checkpoint behavior for both pre-admission waits and limits discovered after admission. Defer recovery reservations until execution admission where appropriate. Distinguish an evidenced denial before useful work from an interrupted invocation with possible mutations or unknown usage; preserve the latter’s accounting and reconciliation requirements. Test both writer and stress recovery through checkpoint and resume, rather than testing only that `before_attempt` was not called.

3. **Blocker — Router unavailability still permits the original long worker wait.**

   Scope: design lines 59–60 versus 63–70; rows 2 and 48.

   The missing/unreachable-server path waits until the caller’s deadline or cancellation. That contradicts the rule that waits longer than 60 seconds checkpoint immediately. It also leaves timeout-only calls without an explicit caller deadline unclear.

   **Required:** apply the same bounded wait, heartbeat, and checkpoint policy to connection failures, RPC timeouts, and uncertain acquisition/finish. Specify how uncertain ownership is retained and reconciled without invoking another model or keeping a sleeping worker indefinitely. Include an outage exceeding the watchdog threshold in the lifecycle test.

4. **Blocker — Codex renewal does not yet connect refreshed credentials to the actual consumer.**

   Scope: design lines 146–158; row 20.

   Reusing `Relay.credential` is reasonable, but the referenced pieces have incompatible timing and delivery behavior:

   - `Relay.credential` ordinarily refreshes only within 60 seconds of expiry (`harbor/keyswap/keyswap.py:130`).
   - `worker_auth` rejects credentials with approximately six minutes remaining (`factory/codex_login.py:40,46–53`).
   - Launcher validation requires credentials covering the worker TTL plus margins.
   - `push-secrets` updates `/dev/shm/secrets/codex-auth.json`; runtime reads the separate `~/.codex/auth.json` copy installed by `factory/launch.sh:265`.
   - Existing `account_handoff.apply` handles Claude/OpenCode account changes, not Codex renewal.
   - Translating `codex_login_expired` to a public `provider_limit` stop also needs an explicit authenticated ledger-compatibility rule; current `recovery.ledger_agrees` does not accept that translation generally.

   **Required:** specify renewal lead time and forced-refresh behavior, the source used by launcher validation, atomic installation into the runtime’s credential source, active-invocation behavior, failed-delivery retries, and stop/ledger reconciliation. Add boundary tests across launch, renewal, redistribution, and the next actual runtime credential load.

   Keeping row 20 open without real expiry/renewal evidence is correct. That honest closure boundary does not resolve these implementation gaps.

5. **Blocker — Existing sanitized labels cannot prove the promised failure distinctions.**

   Scope: design lines 83–90,101–104,178–180; rows 3 and 48.

   `factory/budget.py:321–346` collapses insufficient credit, HTTP 402, subscription quota, and rate limits into `provider_limit:<model>`. The router cannot distinguish wallet-wide exhaustion from a model-specific limit using that label alone.

   Refusal detection currently covers a narrow Codex cybersecurity pattern. Ordinary Claude/OpenCode refusals do not necessarily produce `refusal:*`. Successful CLI output with a refusal can therefore be treated as readiness or surface later as a missing artifact. Mapping existing labels does not add the missing detection.

   **Required:** define a sanitized structured observation produced at the existing provider-parsing boundary, including failure scope and reset information. Coordinate ownership of that small change if `budget.py` belongs to another stream. Test real provider events through parsing and routing; injecting already-classified exceptions proves only the router’s response to those labels. Otherwise explicitly leave the unsupported portions of rows 3 and 48 open.

6. **Major — Reused handoff transport does not enforce the stated one-token worker contract.**

   Scope: design lines 121–128; prior finding 5.

   `factory/account_handoff.py:138–141` uses `push-secrets --merge`. That preserves the displaced Claude token in `/dev/shm/secrets`. Using non-merge delivery instead removes unrelated worker secrets.

   **Required:** specify replacement of only the selected provider credential, removal of the displaced token, and reconciliation after uncertain transport. Verify worker RAM contains only the selected Claude token after repeated switches. The claim that existing transport already supplies this property is unsupported.

7. **Major — Admission identity and lease semantics need one consistent contract.**

   Scope: design lines 50–58,66–79,91–93.

   Acquire is idempotent by request ID, but a call can finish one failed attempt and re-enter admission for another route. The design does not distinguish logical-call identity from execution-attempt identity. It also provides two lease-expiry rules: call deadline plus grace, and admission plus invocation timeout/grace capped by batch deadline. Existing caller deadlines use `time.monotonic()`, which cannot be transmitted unchanged between hosts.

   Selection of an account whose credential is absent also needs a non-executed admission outcome; it must not leave capacity reserved until invocation timeout or record a false provider failure.

   **Required:** specify call/attempt identities, cross-host deadline representation, one lease-expiry calculation, and release/revalidation across credential handoff and worker retirement.

Disposition of the prior review:

- **#1, waiting:** substantially improved, but remains blocked by findings 1–3.
- **#2, scope/deployment:** service and timer delivery are now in scope. Stream-B integration remains a prerequisite; row 20 remains explicitly partial.
- **#3, duplicate handoff:** making `choose` a router query is acceptable reuse of transport. Coordinator account selection must also be removed.
- **#4, duplicate capacity:** ownership is stated correctly, but the coordinator deletion boundary remains unresolved.
- **#5, security/accounts:** exact Claude labels and exam-account exclusion are addressed; token replacement remains incomplete.
- **#6, connectivity:** TLS, bind address, token creation, delivery, and rotation are sufficiently chosen for design review.
- **#7, bypass:** addressed by mandatory RPC and no production direct-store adapter.
- **#8, classification/retries:** refusal bounds and finite leases improve the design; findings 4, 5, and 7 remain.
- **#9, capacity:** conservative initial capacity and configuration source are adequately grounded.
- **#10, recovery counts:** launcher/restart exclusions are explicit; coordinator and stress-recovery allowances remain.
- **#11, DeepSeek:** treating native availability as a probe resolves the unsupported availability assumption. Family, billing, and real-ledger assertions remain required.
- **#12, altitude:** no objection; the small stdlib service and reuse direction remain proportionate.
- **#13, records:** retain verbatim reviews and merge-commit `Reviewed-by:` trailers as ENGINEERING requires.

No target row is closed by this design review. Rows 2 and 47 depend on the complete continuation path; row 4 requires actual timer/inventory integration; row 3 needs wallet-scope evidence; row 48 needs provider classification and recovery-reservation proof; row 20 requires both the completed renewal path and real expiry/renewal evidence.


## Elephant response

Parent supplied and authorized docs/designs/interfaces.md: A merges a unit-tested router slice; D owns reservation/usage/counter changes; B owns lifecycle, row20 renewal, and combined closure test. Revised design names exact ownership and merge order and explicitly leaves rows2/4/47/48 open until B. Parser-only budget seam is now assigned to A. Unavailable-router waits are bounded like provider waits; call vs attempt IDs, wire wall-clock deadlines and nonexecuted credential handoff leases are explicit. No blocking finding rejected. Fresh review requested.
