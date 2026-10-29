# Goldfish review 4: docs/designs/status.md

Reviewer: fresh Claude Sonnet subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**Fourth pass: PASS.** I found no BLOCKING issues.

I checked the new "sealed" and "rejected" definitions against the 297 real cards:
- **Sealed:** 21 cards have `gates.G12 == "pass"` and no `failed_gate`. All 21 have `status` and `terminal_stop` unset, and 15 gates. They count as sealed, so the three-part definition matches real data.
- **Rejected:** 65 cards have `failed_gate` set, and all 65 also show `G12: pass` with no `terminal_stop`. That is the inflation the third-pass finding caught, and the new rule now counts them as rejected rather than sealed.

The other four changes hold up:
- **Generation match:** "card `sha256` equals the journal's latest collected generation" matches `restore_ledger.authenticate`, which binds a card by `sha256`.
- **Failed Boat list:** treating it as batch-unreadable avoids a wave of false `worker gone` flags.
- **"As of last card" spend:** it is honest about running cases, and the 5-hour stuck rule still covers them.
- **Waiting:** the definition is clear. It will show zero until stream A writes `provider_wait`, and the doc says so.

NITs, none blocking:
1. "Not stopped on a non-`complete` reason" should be implemented as "`terminal_stop` is null or `complete`". Real sealed cards carry null, not `complete`, so a literal `== "complete"` check would show zero sealed.
2. The test should include one real sealed card, one real rejected card, and one rejected card edited to carry a stop reason. That covers the exact bug the third pass caught.
3. A rejected case is a normal outcome and correctly raises no flag, but the doc doesn't say so in one line. Add it so nobody adds an alert later.

PASS.

## Elephant resolution

All three nits fixed before commit.
