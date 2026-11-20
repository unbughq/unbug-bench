# Diff review 2: G2 top-up flagged expired row (1108c), 625ce7e0..e738ad08

Reviewer: fresh goldfish subagent (general-purpose), Mode: REVIEW, zoom_out + implementation_readiness.

VERDICT: FAIL

The fix works for the 1108c row and changes no gate identity. One new clause in the general prompt contradicts the rule next to it, and it can cost a case a defect strike. That is the blocker.

**1. Is the loop fixed, and is identity unchanged?**
- **The loop is fixed for the 1108c row.** If the attacker amends the row in place and keeps its url, `finish_freshness_repair` finds exactly one match on the protected who/kind/query/url fields. It no longer re-appends the old row. The `evidence_expired` error goes away, so `fixed` is true and `ensure` does not raise `freshness_refresh_stalled`. The api.github.com search URL is not caught by `SEARCH_PAGE`, so the url check accepts it, and `metadata()` projects the row with its own url, so no defect is charged.
- **No identity change.** I computed `source_inputs` for every gate from both versions of `run.py`. All are identical, and neither `freshness_topup` nor `_freshness_searches` is reachable from any gate root. No file in `STAGE_DEPENDENCIES`, `factory/prompts/`, `admission.py`, `gate_state.py` or `ordinary_freshness.py` changed.
- **No verdict rule change.** `flagged_expiry` only rewords a reason that was already non-None, so `errors`, `short` and `targeted_errors` (which comes from `search_evidence_error` in `ordinary_freshness`) behave as before.

**2. Is the prompt consistent?**
- **BLOCKING, factory/run.py:680.** The new clause "a url with no url error below stays exactly as it is" relies on the validation list, but that list shows only the first error per row. `search_evidence_error` reports `retrieval_failed` and the missing-field / `app_version` errors before it checks the url (admission.py:128 vs :133). So a search-page url can be present with no url error shown.
  - The known shape is f46dac's: an unflagged row with `retrieved` false and a DuckDuckGo url, reported only as `retrieval_failed`.
  - The new clause tells the searcher to keep that url. The same parenthetical says "never a search-results page".
  - If the searcher re-reads the DuckDuckGo page and amends the row in place, the row turns into `search_page_url`. That is not a refresh reason, so it is charged as a defect. Two defects stop G2 with `freshness_evidence_unavailable`.
  - Before this diff the wording was just "never a search-results page", and the searcher would have replaced the url. The url isn't protected because it is invalid.
  - It doesn't bring back the stall, but it is a new contradiction that can spend a defect strike.
  - Fix: delete that clause. The per-row reason at :561 already covers 1108c exactly. Or define it by what G2 accepts: "a result page, an api.github.com URL or that GitHub no-result URL stays exactly as it is".
- **The other rules you asked about are consistent:**
  - The per-row flagged reason (:554–561) can't clash with "a search_page_url row's url must become its result page". `evidence_expired` is only reported once the url has passed its check, so the url it says to keep is always one G2 accepts.
  - A flagged row has a hit, so it is never a GitHub no-result search, and the no-result URL rule doesn't apply to it.
  - "A flagged row is never superseded: amend it in place" vs "log the rerun as a NEW row" (:682) holds together. A flagged row doesn't need `retrieved`, so the searcher can amend `at`/`note` in place even when it can't fetch the url, and log any new result as a new row.
- **NIT, :681–682.** "leave the row … (a flagged row … amend it in place)": "leave" and "amend" sit side by side. Clearer: "a flagged row is amended in place instead".

**3. Does the test prove the change?**
- At e738ad08 all 4 tests pass. With the pre-change `run.py` (625ce7e0) in a scratch copy, the new test fails on the flagged-reason assertion. So it does fail without the change.
- **NIT, tests/factory/test_freshness_concurrent.py:87.** The second half (one row kept, error cleared) passes with or without the change, because the fake model always amends correctly. It shows the in-place path clears the error, not that the prompt causes it.
- **NIT, same test.** Nothing covers the general-prompt clause added in e738ad08, or the case above where an earlier error hides a url error.

**Risk outside this diff (not graded)**
- Once the row is valid, `_g2` fetches its api.github.com search URL as a flagged page. Unauthenticated GitHub search often answers rate limits with 403, which is in `WALLS`. With no archive copy, 1108c could stop as `freshness_source_blocked` after 3 cycles. Worth watching on the re-run.

## Elephant's disposition
- BLOCKING: fixed in 4c3590eb by deleting the clause.
- Wording nit: taken in 4c3590eb ("it is amended in place instead").
- Test nits: the clause they asked to cover was deleted; second half kept as a regression guard.
- Outside risk: the same flagged row was fetched by the runner when G2 passed on 20 Nov 07:56 and in earlier passes; watch it on the re-run.
