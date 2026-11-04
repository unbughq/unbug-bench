# Exact November4 smoke budget disposition

Founder approval09df201 authorizes only bx_bykfqbyn's reserved0.036 budget debit.
Original Nov3 decision/hash/schema remain unchanged. No live application, worker,
new cap/payment/top-up, generic forgiveness or Murphy closure. Actual stays null.

Extend existing lifecycle helpers with an explicit selector legacy(default) or smoke;
unknown selectors refuse. Each selects a fixed factory decision filename and pinned
raw SHA. budget_amount selects from the persisted decision_sha256, then validates
the unchanged exact schema/row reconstruction against that particular approval.
Old helpers' default and --record-approved-legacy-debit behavior stay unchanged.
Add --record-approved-smoke-debit with no user-defined scope/amount. Same home lock,
atomic ledger write, snapshot shape and no-op finish/settle/record replay.

Smoke original row must have exactly usd,expires_at,status,state_path,vms,ttl_seconds,
max_spend_usd (optional actual_spend_usd=null), with values exactly the supplied
reserved row: usd0.036, expiry1793790083.3712797, approved state path,1 VM,3600s,'5'.
No finished_at fabricated; no settlement/budget proof accepted as original. Snapshot
all prior fields. First apply checks exact spend SHA, Boat allowed envelope/unknown
actual, strict owned IDs/unique creation, monitor spend binding, matching exact
completed deletion and pinned raw request/completion hashes. Root's saved binding
is evidence, not reconstructed raw bytes. Local initial-apply test transport is
explicitly AUTHORED where canonical files/raw SHA are unavailable.

Runtime factory approval copy is already present, identical to docs; include only
that path in existing host trust inventory. No new owned source roots. Mixed old
and new budget rows sum0.072, minimum original5 remains enforced, leaving4.928
before other liabilities. Replay validates both decisions without provider/evidence
reads or writes (apart from reading pinned public decision). Larger caps cannot reset.

Files: boat_lifecycle.py, boat-spend, launch_manifest.py, existing legacy debit tests,
this design/reviews/report. Sequence: design review; implement selectors/strict scope;
focused initial apply/negative/replay/mixed-cap/packaging checks; fresh diff review;
final commit then one full suite using TEST_SLOTS=4 TEST_JOBS=4, Docker smoke unset,
caffeinate. Record UTC elapsed minus monotonic elapsed and pre/post tree/cleanliness.
Offline effort about one hour plus suite. No runtime deployment/pin changes here.
Root must use an inactive compatible runtime without changing running source or
invalidating old journals; old82 parser cannot accept the new row. Root owns safe
integration/re-pin/application order. Approval does not authorize successor admission.
