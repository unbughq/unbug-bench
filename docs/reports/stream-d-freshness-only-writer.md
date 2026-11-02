# Freshness-only extension writer continuation

The branch merged factory-simplify e1087df before implementation. Both extension
writer completion checks now use full-tree identity for unchanged_repair, while
ordinary non-extension checks retain repair_requested. The obsolete after_stop
refusal was deleted. Search-evidence-only changes proceed through ordinary
validation and stress without another writer round; exact no-op terminal proofs
and their authentication remain intact.

The focused tests cover fresh completion, retained completed receipt, recovered
writer completion, and real G2 consuming a new hit over saved HTTP bytes. External
writer, stress, fetch and reviewer outputs are labelled controls. The prior
repair-True evidence-stop test is explicitly superseded by the approved design;
no other assertions or ordinary runtime tests were weakened.

Design reviews: docs/reviews/stream-d-freshness-only-writer-design-{1,2}.md.
Round 2 passes. During test implementation, public-search.json was confirmed to
hold counts/bindings rather than URLs: its flagged_hits count is asserted, while
the exact new URL is asserted in reviewer input, verdict and retrieval receipts.
This preserves the round-1 blocker fix: ignoring the new hit fails the test.

Full suite passed 174 scripts / 0 failures at 655b5f0 (tree
33322355c567b18426f1348e2e49aa01a90d6acc), in 2380.07 seconds. Record:
stream-d-freshness-only-suite-20261102T062945Z-a0fda9ec.json and matching log;
log SHA-256 6216e327d542350c7f428b98595da390018018f4504244d4bb8ad7850bfaf357.
All 18 focused tests pass; existing 42 runtime and 63 dispatch tests pass unchanged.
Fresh diff review pending. No Murphy rows close. Activation,
limits, attribution, schema and scientific versions are unchanged. The remaining
item-7 slices and lane estimates are listed in the design; the pre-existing
irrelevant-edit reroll limitation belongs to lane 2's rejected-writer/progress
slice. Linux/live qualification remains outside this offline slice.
