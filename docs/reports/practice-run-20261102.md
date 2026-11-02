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
