# $25 plumbing practice — stop before live action

Prove one fresh worker can publish and be deleted without the Mac. Success needs
publication records and verified deletion; account-2 attribution remains unproven. An abort is not
a pass. Two serial workers, concurrency one; diagnosis, replacement and helper comparison
off. Empty-input authentication establishes prior spend $0; case authorities $0.01 smoke and $19.98 practice.
Item 8, queued-child creation and multi-worker carry remain separate work and pins.

**Timing: parent-approved after round 2.** Normal collection starts at worker
start + 30 minutes. Watchdog deletion is start + 30-minute run cap + 15-minute
collection grace, strictly before the 60-minute provider TTL. Never use reservation
time or extend the deadline on restart. Refuse incompatible timings at admission.

| Step | Action and required evidence | Incremental ceiling |
|---|---|---|
| 0. Pin offline | After this reviewed change merges, run `python3 -B tools/pin-practice.py --output /ABS/NEW`. Clean HEAD must equal available factory-simplify. Verify generated hashes; do not wait for lane 2. | $0 |
| 1. Live entry | **Founder decisions (2026-11-02):** "Provider bound ACCEPTED: Boat's prepaid credit balance (below $5, no auto top-up) together with the 60-minute TTL auto-delete is the accepted $5 infrastructure cap. A hard provider-side cap is not required." "Legacy launch b275ffccd6134a33833853ad1d31ed16 is WRITTEN OFF as having created nothing, based on the empty Boat inventory plus no unexplained billing. Any later charge traced to it goes on the infra-waste line." **Launch disposition: disposed (founder write-off).** Run `python3 -B tools/practice-preflight.py --bundle /ABS/NEW --live` (`docs/designs/preflight.md`, phase A) and continue only on exit 0. It reports every check at once: `founder_decisions` (`factory/batches/b-plumbing-practice-3.decisions.json`; auto top-up off is the `topup_off` attestation, because no API reads it; a new decision means repinning at step 0), `deploy_access` (root SSH), `boat_cli` (exact pinned version and full list), `boat_wallet` (balance at most $5), `credentials` and `login_lifetimes` against the VM's bundle. Exit 3 means a founder answer is missing; exit 1 means a check failed. Retain all legacy files; fabricate no completion markers. | $0 |
| 2. Accounts/deploy | **Superseding founder decision (2026-11-02): "Use existing token."** Use both `claude-token` and the existing `claude-factory-token-2` unchanged, as the pinned policy expects. Record `distinct_accounts: "unverified (founder accepted)"`; account-2 attribution and natural 2→1→2 handoff are unproven. Invalid, expired or refused token-2 is an ordinary stop under this plan. Install pinned code/policy, host tools and cleanup unit (also its source copy under control/), plus the generated holder drop-in. Every install runs as root over `bin/control-vm`'s root SSH, never through user sudo; `control/setup.sh` installs the exact pinned Boat CLI and checks its SHA-256. Drain old paid clients; install router before clients. No hand-run verification: `batch_holder.dispatch` checks credentials, Codex login (only with a Codex role), router delivery with a settled paid ledger, OpenRouter credit and R2 before `dispatch_started`, and holds the operation pending on any failure (phase B); hashes stay covered by the code fingerprint and release verification. **Founder acknowledgement (2026-11-02):** the OpenRouter API key may be in control-VM router RAM only, for read-only credit checks and capped calls; never write it to disk, print it or persist it. | $0 |
| 3. Smoke admit/arm | Batch `b-plumbing-practice-3` (`docs/designs/startup-smoke.md`). Run `tools/qualify-batch-inputs.py --policy POLICY --home CONTROL_HOME --job smoke`. Enable only the hash-authenticated practice policy. Reserve `smoke` once through the existing key-holder interface. Start `unbug-practice-cleanup@SMOKE_OP.service`; record active PID, readiness binding and operation/launch/reservation IDs before dispatch. | $0 |
| 3a. Smoke run | Dispatch `smoke` (the practice job with `--dry-run`: no model calls). Wait for collection, publication and verified deletion. No disconnect window and no fault arm. **Pass:** card collected and published; `terminal_stop` neither starts with `runner_error` nor is `money_wait`; startup and prepare completed and G1 passed; worker deletion verified. Record G3's status; it is not required. **If the smoke fails, stop here.** No model money was spent; diagnose from the collected card. | $0.01 allocation, never spent; Boat shares the $5 |
| 3b. Practice admit/arm | Only after the smoke passes: run `tools/qualify-batch-inputs.py --policy POLICY --home CONTROL_HOME --job practice`, reserve `practice` once, start `unbug-practice-cleanup@OP.service`, and record PID, readiness binding and IDs as in step 3. Steps 4–6 apply to this practice operation only. | $0 |
| 4. Worker | Record creation ID, worker-start timestamp and 60-minute TTL. Disconnect the Mac; restart the holder once. Require the same operation and worker. No relaunch or second worker. | $5, shared with deletion |
| 5. Model work | Use all five explicit roles in the pinned manifest: MiniMax writer/easy calibrator, DeepSeek stress, MiMo reviewer, Claude Opus4.5 compact strong calibrator. Every route has a pinned maximum; no unbounded Codex route. **Superseding founder decision (2026-11-02): "Use existing token."** Keep pinned initial account 2 and allowed accounts [2,1], using both existing labels. Account distinctness is "unverified (founder accepted)"; account-2 attribution and natural 2→1→2 handoff remain unproven. Invalid, expired or refused token-2 is an ordinary stop. Builders share account 1; a Claude rate limit is an ordinary cap/refusal stop. OpenRouter stays within the existing shared min($11.63, observed credit), with no top-up. | $19.98 total list-equivalent, including waste and unknown holds |
| 6. Publish/delete | In the operator shell, first run `export UNBUG_PRACTICE_BATCH=b-plumbing-practice-3`. Once before collection of the practice operation (never the smoke), arm `python3 -B tools/practice-fault.py --policy POLICY --operation OP`. First publication fails before transport/ACK; ordinary replay must publish the same generation. Normal collection precedes deletion; the independent watchdog still deletes positively owned disposable workers at its deadline if collection fails. If the controller dies before writing `.started`, no watchdog deadline can be computed: the provider TTL is the backstop and uncertainty remains. Require deletion request ID, exact target, kind=sandbox, completed status/stage, timezone-aware completion time, and full hasMore=false inventory proving absence. Run holder reconcile; retain generation, ACK/pointer and money records, or explicit failure. | Included in $5 |
| 7. Close | Disable practice admission. Stop cleanup only after verified completion or terminal non-dispatch. Retain settlement or unknown holds; never reset the infrastructure ledger. | $0 |

Total reserved: **$19.99 model ($0.01 smoke + $19.98 practice) + $0.01 unused + $5 infrastructure = $25**.
There is no separate probe, subscription purchase or additional allowance.

Abort before creation for stale pins, missing required Claude labels, Boat credit above $5 or auto top-up on (or unverified), failed cleanup arming, stale or
depleted paid ledger, failed empty-input proof or missing deployment acknowledgement.
After creation, stop model admission on cap/refusal, unknown settlement, duplicate
creation, lost ownership, late output after cancellation, failed publication,
identity mismatch or deadline. Keep cleanup until verified deletion; unknown
creation/deletion permits reconciliation only, never another worker or fake proof.
The provider-bound and legacy-debt prerequisites are resolved by the founder decisions.
Live credit/top-up, deployment, account and lifecycle checks still govern this run.

The account-1-only routing hold is superseded by the decision to use both existing
labels. Parent-approved fresh admission (2026-11-02) uses `b-plumbing-practice-2`;
the previous batch is no longer admitted. Its failed operation and every ledger
remain retained. Recorded prior model/infrastructure spend is $0/$0, so this
attempt still has only the original cumulative $19.99/$5 ceilings, not a new
allowance. Merge and repin before deployment; earlier release pins are obsolete.

Startup smoke (2026-11-03): the batch is now `b-plumbing-practice-3`, with a no-model
`smoke` job run first (steps 3–3b). It splits the same $19.99 between the jobs and adds no
money. Repin and redeploy the policy, release pins, cleanup unit and holder drop-in
for -3; any of them left at -2 makes cleanup refuse and dispatch wait for ever.

## Repaired-release smoke continuation (prepared November 4; inactive)

The -3 smoke was collected/published/deleted, but fresh stopped metering failed.
The -4 successor imports that exact smoke checkpoint through existing
`batch_transfer` and preserves its original case, commitment, model totals and
history. It does not restart science from scratch or reset either budget.
See `practice4-checkpoint-carry.md` and its retained public source fixture.

These steps supersede new-admission steps 3–3a only after separately authorized
installation/unlock and exactly one smoke-continuation worker. Prepare the -4
pins; revalidate the pinned -3 snapshot; preserve its release, operations,
collection and both $0.036 conservative debits. Do not replace the release pin in
its existing journal. Existing transfer freezes -3 on admission, then the
ordinary checkpoint launch runs the imported `smoke` generation under -4.
Use `UNBUG_PRACTICE_BATCH=b-plumbing-practice-4` consistently in the installed
cleanup unit and holder drop-in. Qualify/reserve smoke with checkpoint
`b615c37c3ff2c3103576a74d1175cad299dc3eaf1f3f28f7a3b56b06eab2d6d9`,
arm independent cleanup and record readiness before dispatch. Collection is
still +30 minutes, deletion grace +15 minutes, provider TTL 60 minutes.

This is a no-model lifecycle qualification only: require fresh same-stop
completion, stopped usage/recheck, exact collection/ciphertext/publication,
completed exact-worker deletion and settlement. `paused` during a mechanical
gate is compatible with smoke science criteria but cannot excuse missing
lifecycle proof. No automatic retry, practice worker or fleet is authorized.
Do not reserve or dispatch the dormant practice job without a later go-ahead;
once -4 is opted in, nothing in code enforces this ordering.
Factory Claude routes remain unchanged; implementation cloud credits do not
fund local model calls from a Boat worker. The prior top-up/account/RAM-only
credential decisions remain attributed to their original dates and grant no
additional launch authority.
