# Practice run — 2026-11-02

- Founder authorization: steps 0–7; models $19.99; infrastructure $5; no top-ups.
- Status: ABORT at step 1, before deployment or admission.
- Source commit: 3a50896325a6054164b0ce0c9e001649cd22dc32.
- Step 0: clean HEAD equalled factory-simplify; release pins cut and file hashes verified.
- Batch ID: b-plumbing-practice.
- Release ID: d68dc4ba2cda11bb8b5a6bdd6454e591672a2a99f12d67705555b6f110d066e5.
- Live observation UTC: 2026-11-02T04:54:37.965578+00:00.
- Boat credit balance: $4.17157; verified.
- Auto top-up: unverified; entry abort condition fired.
- Practice model spend: $0.
- Practice infrastructure spend: $0; no practice worker created. Existing control-VM running costs are outside this incremental observation and are not claimed to be zero.
- Deployment: not started.
- Reservation/operation/worker IDs: none.
- Cleanup: no practice worker or pending creation; cleanup unit not armed, no deletion required or claimed verified.
- Claude account 2 usage: none; identity confirmation not reached.
- Legacy launch disposition: founder write-off retained; files unchanged; no completion markers fabricated.
- Next prerequisite: privately verify auto top-up is off; no automatic retry or continuation.
- Evidence recorded UTC: 2026-11-02T04:55:06.058436+00:00.

## Authorized restart — step 1

- Operator confirmation recorded UTC: 2026-11-02T05:38:48.121859+00:00.
- Founder confirmation: "Auto top up is off"; checked privately in Boat → Billing. Exact private-check time was not supplied; the UTC above is receipt recording time.
- Restart authorization: founder, 2026-11-02; same approved plan, ceilings and mandatory pauses.
- Live balance observation UTC: 2026-11-02T05:38:51.144216+00:00.
- Boat credit balance: $4.17157; verified, at or below $5.
- Step 1: PASS; live balance plus operator-confirmed auto top-up off.
- Current status: PAUSED at step 2 for mandatory operator account-distinctness confirmation.
- Account 1 label: claude-token.
- Account 2 label: claude-factory-token-2; not claude-token-2.
- distinct_accounts: unconfirmed; no assertion of true yet.
- Deployment, reservation and creation: not started.
- Practice spend across both entry attempts: models $0; infrastructure $0.
- Cleanup: no practice worker or pending creation; no deletion required; no cleanup unit armed.

## Automated identity check — step 2

- Operator identity confirmation: not sure; not accepted as proof.
- Identity check UTC: 2026-11-02T05:48:41.004239+00:00.
- Labels: claude-token; claude-factory-token-2.
- Automated identity evidence: unavailable; distinct_accounts remains unconfirmed.
- Status: handed back at step 2; no admission or deployment continuation.
- Practice spend: models $0; infrastructure $0.
- Worker IDs: none; cleanup not required.

## Founder account-1 decision and offline stop

- Founder decision (2026-11-02): "Use account 1 for the practice run for now."
- Decision recorded UTC: 2026-11-02T05:54:56.341529+00:00.
- Allowed Claude label: claude-token only; claude-factory-token-2 must not be deployed to the VM.
- Account-distinctness requirement: waived for this run.
- Account-2 attribution and natural 2→1→2 handoff: UNEXERCISED, deferred, not failures.
- Shared account-1 Claude rate limit: ordinary cap/refusal stop, including builder contention.
- Offline source checked: 3a50896325a6054164b0ce0c9e001649cd22dc32; routing, holder, handoff, launch and practice sources unchanged from that pin.
- Offline router account1-only capacity: 0 slots; account 1 remains gated on current account-2 rate/quota health even when account 2 is absent.
- Offline account1-only manifest match: false; exact practice validator requires initial account 2 and allowed accounts [2,1].
- Offline pinned handoff initial Claude selection with only account1 held: 2. Holder rejects missing selected account2; launcher alone can filter to account1 but cannot override these earlier checks.
- Status: STOP before deployment; code change required. No factory code or manifest edited mid-run; no account-health record fabricated.
- Smallest needed change: allow account1 eligibility when account2 is explicitly absent from router accounts; change the practice manifest and exact validator to initial account1/allowed [1], test, review, and cut new pins.
- Practice spend: models $0; infrastructure $0.
- Worker IDs: none; no pending creation; cleanup not required.

## Superseding founder decision and step-2 deployment check

- Founder decision (2026-11-02): "Use existing token."
- Decision recorded UTC: 2026-11-02T05:58:15.104440+00:00.
- Labels: claude-token and existing claude-factory-token-2, unchanged; pinned initial2/allowed[2,1]. No exam label used.
- distinct_accounts: "unverified (founder accepted)".
- Account-2 attribution and natural 2→1→2 handoff: unproven.
- Invalid, expired or refused token-2: ordinary stop under the plan.
- Account-1-only instruction and its routing hold: superseded. Source 3a50896 and original release pins retained; no code change or repin.
- VM observation UTC: 2026-11-02T05:57:11.267585+00:00.
- Encrypted credential labels verified: claude-token, claude-factory-token-2, opencode-go-key, openrouter-key, codex-auth.json.
- Holder, resume timer, model-router and batch services: inactive.
- Shared router runtime configuration: absent; deployment not begun.
- Step 2: ABORT, required founder acknowledgement of OpenRouter credential placement in router RAM not found in available records. Identity waiver does not claim that separate check passed.
- Practice spend: models $0; infrastructure $0.
- Worker IDs: none; no pending creation, no cleanup unit armed, no deletion required.
- Deployment mutation: none; no decrypted credentials persisted or emitted.

## Router acknowledgement and consolidated offline dependency scan

- Founder acknowledgement (2026-11-02): approved placing the OpenRouter API key in the control-VM router's RAM only, for read-only credit checks and capped calls. It must never be written to disk, printed or persisted.
- Acknowledgement recorded UTC: 2026-11-02T06:01:24.238439+00:00; receipt recording time, not an inferred time of the private decision.
- Previous missing-acknowledgement abort: resolved by this acknowledgement.
- Scope scanned offline: practice steps 2–7; activation/admission/cleanup validators; holder dispatch; account handoff; worker launcher; router transport/configuration; service units; pin and input qualifier.
- No additional account identity confirmation is required: distinct_accounts remains "unverified (founder accepted)"; account-2 attribution and natural handoff remain unproven.
- Known operator action: step-4 Mac-disconnect pause, retained.
- Remaining handback item: resolve worker-to-router configuration delivery before deployment. model_router._rpc requires FACTORY_ROUTER_URL and FACTORY_ROUTER_TOKEN; batch_holder.dispatch constructs an environment without either; launch.sh does not deliver them to the worker and rejects unrecognized secret labels. The shared router service configuration alone does not configure worker clients. TLS trust must also be supplied through a supported deployment path. No existing pinned delivery path was found in this offline scan; no live image fallback was assumed.
- Required resolution: identify an already-supported pinned deployment path, or authorize a separately reviewed offline delivery fix and new pins. No mid-run code edit or invented credential path.
- Other planned actions are agent-executable under existing authorization: public deployment, noninteractive administrative unit installation, ledger/credit/R2/hash checks, cleanup arming, holder restart, publication-fault arming and reconciliation/disable. They remain unverified live checks, not additional founder approvals. Any failure still aborts.
- Status: STOP before live deployment; consolidated handback under the no-code-change rule.
- Practice spend: models $0; infrastructure $0. Worker IDs: none; no pending creation or cleanup required.

## Authorized resume — merged release, steps 0–3

- Status: PAUSED before step 4; Mac remains connected.
- Source commit: 02f3bc917d846134174b768cc9f5c5fb16575ec8.
- Step 0: PASS; fast-forwarded branch, clean HEAD equalled factory-simplify before pinning.
- Pin bundle label: unbug-practice-20261102-02f3bc9; new bundle, previous 3a50896 pins obsolete under parent resume authorization.
- Release ID: c55484c4fb2e27fb17dbb5a255b0a4804fa19faa5842de2be75a4baf010c2734.
- Pin verification UTC: 2026-11-02T11:41:50.713072+00:00; generated hashes, release and policy verified.
- Initial balance wrapper invocation: unsupported argument; no provider mutation. Corrected read-only observation follows.
- Step 1: PASS; Boat balance $4.17157 at 2026-11-02T11:42:14.015839+00:00.
- Auto top-up: OFF, prior founder operator confirmation retained.
- Provider cap: founder-accepted prepaid credit plus 60-minute TTL; infrastructure ceiling $5.
- Legacy launch b275ffccd6134a33833853ad1d31ed16: disposed by founder write-off; files retained, no completion markers fabricated.
- Step 2: PASS; pinned public host/release/policy hashes verified on control VM; cleanup unit and generated practice drop-in installed.
- Credential labels: claude-token; existing claude-factory-token-2; no exam label deployed.
- distinct_accounts: "unverified (founder accepted)".
- Account-2 attribution and natural 2→1→2 handoff: unproven.
- Router RAM acknowledgement: prior founder acknowledgement retained.
- Router credentials and TLS key: control-VM RAM only; founder private key remained on Mac.
- Router service: active; authenticated TLS verified internally and certificate trust verified externally; router endpoint firewall configured.
- Canonical shared router ledger: absent before deployment, initialized by pinned service; no historical ledger reset.
- OpenRouter credit schema: verified; available $11.3637556 at 2026-11-02T11:44:07.550400+00:00; no model call, no top-up.
- R2 access: verified at 2026-11-02T11:45:46.129667+00:00.
- Router authenticated TLS observation UTC: 2026-11-02T11:46:52.060027+00:00.
- Step 3: PASS; empty-input qualifier eligible, admission new, batch absent; prior spend $0.
- Holder credential availability: Claude labels 1 and 2 present; label 3 absent.
- Reservation operation ID: e88e8368-4edc-5f00-a7e7-0672bf5574cc.
- Launch ID: 0d25466ae06349778895f00cfb1b55b9.
- Reservation state: pending; reserved once through key-holder interface.
- Pause ordering: holder stopped while cleanup still unarmed, then cleanup armed; prevents automatic dispatch across the mandatory step-4 pause.
- Cleanup readiness: authenticated policy/operation/launch/timing binding verified; active PID 233956.
- Cleanup observation UTC: 2026-11-02T11:49:34.492015+00:00.
- Dispatch started: false. Worker ID: none.
- Final observation UTC: 2026-11-02T11:50:12.961752+00:00.
- Boat balance: $4.17157; full inventory hasMore=false, worker count 0.
- Router active leases: 0; paid total $0.000000000; paid outstanding $0.000000000.
- Practice spend: models $0; infrastructure $0; no practice worker created. Existing control-VM running costs are not claimed to be zero.
- Cleanup: armed and running, waiting; no deletion required or claimed verified. Holder inactive at pause; resume timer inactive.
- Remaining operator action: mandatory step-4 Mac-disconnect handback. No other deployment gap observed.
- Factory code changes during live run: none.
- Evidence recorded UTC: 2026-11-02T11:51:06.137343+00:00.

## Founder-approved step 4

- Founder approval (2026-11-02): "Go".
- Approval receipt recorded UTC: 2026-11-02T13:38:14.747032+00:00.
- Disconnect window: confirmed, 60 minutes after verified worker start.
- During window: all Mac-to-VM sessions closed; no VM or provider connections.
- VM-local holder restart: authorized once; no relaunch or second worker.

## Step-4 entry abort — pinned Boat CLI mismatch

- Status: ABORT before worker creation.
- Holder start requested UTC: 2026-11-02T13:38:37.968821+00:00.
- VM-local one-shot restart timer: unbug-practice-holder-restart.timer; scheduled delay 900 seconds, cancelled before firing.
- CLI observation UTC: 2026-11-02T13:40:46.848203+00:00.
- Installed CLI label: boat 1.0.87. Required pinned CLI label: boat 1.0.85.
- Abort condition: deployment prerequisite failed; pinned boat-call list refuses the installed version. No pin weakened, binary changed, code edited or relaunch attempted.
- Correction to step-2 PASS above: public host/release hashes and router checks passed, but the installed Boat executable version was not checked then. That deployment qualification was incomplete.
- Abort stop verified UTC: 2026-11-02T13:41:35.367012+00:00.
- Holder: inactive and disabled. Resume timer: inactive and disabled. Scheduled holder-restart timer: inactive, cancelled before restart.
- Cleanup unit: active, waiting; retained armed. Operation remains pending and is not falsely marked complete or retired.
- Final abort evidence UTC: 2026-11-02T13:42:03.334106+00:00.
- Pinned CLI refusal: verified.
- Reservation operation ID: e88e8368-4edc-5f00-a7e7-0672bf5574cc.
- Launch ID: 0d25466ae06349778895f00cfb1b55b9.
- Operation count: 1. Dispatch started: false. Dispatch exit: none. Worker ID: none.
- Creation records: 0. Worker-start records: 0. Full provider inventory hasMore=false; worker count 0.
- Publication fault: not armed; pinned arming requires dispatch_started=true. Publication/replay: unexercised.
- Disconnect window: not entered; no verified worker start.
- Boat balance: $4.17157, unchanged. Practice infrastructure spend: $0.
- Model active leases: 0. Paid total: $0.000000000. Paid outstanding: $0.000000000. Practice model spend: $0.
- Accounts used for model work: none. distinct_accounts remains "unverified (founder accepted)"; account-2 attribution and handoff unproven.
- Deletion: not required, no worker created; no deletion proof or completion marker fabricated.
- First fix: align the installed Boat CLI with the pinned 1.0.85 requirement and include that live version check in deployment qualification before another authorized attempt.
- Evidence recorded UTC: 2026-11-02T13:42:43.654930+00:00.

## Same-run resumption — Boat aligned to existing pin

- Parent decision: install exact pinned CLI; same run, same existing founder "Go" and 60-minute disconnect window.
- Original installer download endpoint: version query returned latest 1.0.88; candidate discarded, never installed.
- Exact release: original installer redirect's official boat-cli-v1.0.85 Linux asset; installed to original account binary location.
- Installed version: boat 1.0.85. Binary SHA-256: 5d7933a238dcea0446bbbee0e2506692961d16537b9960003e4ece9ecb1ec498.
- Installation and live pinned-list verification UTC: 2026-11-02T13:45:38.313574+00:00.
- Auto-update suppression: CLI-supported BOAT_NO_UPDATE=1, already enforced by pinned wrapper and services; added to account shell and user environment configuration and verified through login shell.
- Deployment qualification now includes: exact live boat --version match and successful pinned bin/boat-call list with complete inventory.
- Requalification UTC: 2026-11-02T13:46:29.960430+00:00.
- Deployment hashes: verified. Cleanup: armed. Empty-input admission: same-operation replay; no new reservation.
- Boat balance: $4.17157. OpenRouter available credit: $11.3637556. Paid total and outstanding: $0.000000000.
- Holder start UTC: 2026-11-02T13:47:02.244373+00:00.
- Replacement restart timer: unbug-practice-holder-restart-v185.timer; one VM-local restart after 900 seconds. Previous timer remains cancelled.
- No factory source or release-pin change.

## Same-run launcher abort — Codex login lifetime guard

- Status: ABORT before provider creation.
- Refusal observed UTC: 2026-11-02T13:47:26.621700+00:00.
- Fixed launcher diagnostic: codex_login_expired. Pinned offline login validation could not prove coverage of worker TTL plus margin; no provider identity call or model call used to diagnose it.
- This pinned launcher guard is unconditional before fresh launch, even though practice roles include no Codex route.
- Operation ID: e88e8368-4edc-5f00-a7e7-0672bf5574cc. Launch ID: 0d25466ae06349778895f00cfb1b55b9.
- Operation count: 1. State: failed. Dispatch started: true. Dispatch exit: 1. Incident: preflight_refused. Worker ID: none.
- Publication fault: armed after dispatch began, unconsumed; publication and replay unexercised.
- Abort stop UTC: 2026-11-02T13:48:27.695854+00:00. Holder inactive; restart timer unbug-practice-holder-restart-v185.timer cancelled before firing.
- Cleanup remains armed and active; no fabricated retirement/completion or deleted evidence.
- Final evidence UTC: 2026-11-02T13:49:51.397367+00:00.
- Creation records: 0. Worker-start records: 0. Monitor absent. Full provider inventory hasMore=false, worker count 0.
- Boat balance: $4.17157, unchanged. Practice infrastructure spend: $0.
- Active model leases: 0. Paid total: $0.000000000. Paid outstanding: $0.000000000. Practice model spend: $0.
- Accounts used for model work: none. Account distinctness remains unverified (founder accepted); account-2 attribution and handoff unproven.
- Deletion: unnecessary; no practice worker created. No deletion verification claimed.
- Disconnect window: not entered; no verified worker start.
- First fix: refresh the host-owned Codex login through the approved secret setup path and verify its lifetime before another authorized attempt. Do not weaken or bypass the pinned guard; do not reset this failed operation ad hoc.
- Factory source/release pins: unchanged. No relaunch, second reservation, second worker, top-up or paid call.
- Evidence recorded UTC: 2026-11-02T13:50:38.403877+00:00.

## Refreshed Codex credential handoff — stopped before admission

- Founder reported Codex login refresh: 2026-11-02, approximately 13:52 UTC.
- Transfer attempt: only the existing refreshed age ciphertext crossed the Mac-to-control connection; plaintext credential and founder identity were not sent from the Mac.
- Refreshed bundle decryption with existing control identity: FAIL.
- Diagnostic observation UTC: 2026-11-02T13:55:19.798735+00:00.
- Codex lifetime guard: NOT RUN on refreshed credential; the transfer failed before validation. The earlier combined transfer/validation result labelled fail at 2026-11-02T13:54:18.610886+00:00 was not evidence of a failed refreshed-login lifetime check.
- Control encrypted bundle: unchanged; no credential replacement completed. No decrypted credentials written or printed.
- Existing operation e88e8368-4edc-5f00-a7e7-0672bf5574cc: terminal failed/preflight_refused under existing pins. Same batch/job/source/release derives the same operation ID; reserve returns the retained failed operation, and reconcile excludes it.
- Practice manifest: one allowlisted job, replacement disabled, exact manifest matching required. No approved second job or reset path under current pins. No journal reset, release substitution or extra authority attempted.
- Status: STOP; need refreshed ciphertext decryptable by the existing control identity and an approved fresh-admission disposition before proceeding. Founder private key must remain on the Mac.
- Holder/restart timer remain stopped; no launch or provider request made during this handoff. Cleanup retained armed from prior abort.
- Practice spend remains models $0 and infrastructure $0; no worker created. Disconnect window not entered.
- Evidence recorded UTC: 2026-11-02T13:56:55.393173+00:00.

## Parent-authorized rewrapped bundle resumption

- Parent confirmation: rewrapped bundle has two recipients; mode 600.
- Observation UTC: 2026-11-03T08:12:56.143767+00:00.
- Bundle decryption: pass.
- Codex lifetime guard (60-minute TTL plus pinned margin): pass.
- Live entry observation UTC: 2026-11-03T08:15:07.951138+00:00.
- Step 1: pass; auto top-up OFF remains founder-confirmed.
- Boat credit: $4.17157.
- Pin/router check UTC: 2026-11-03T08:18:10.251384+00:00.
- New practice pin hashes: pass; router check: pass.
- Deployment observation UTC: 2026-11-03T08:20:18.034758+00:00.
- Approved pinned deployment: refused; source b75c9b45b020e2ba4996ef83ee834c183d38c35f.
- Deployment refusal occurred before a verified completion result; service transitions were not reverified after refusal. No journal or ledger reset was attempted. The old failed launch remains retained.
- Status: STOP at deployment refusal. Models $0; infrastructure $0; no new worker or admission.
- Parent stop rule applied: no further live calls after deployment refusal. New operation/worker IDs: none. Models $0; infrastructure $0; no new deletion required or claimed.
