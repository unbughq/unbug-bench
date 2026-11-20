# Diff review 1: G2 top-up flagged expired row (1108c), commit a25d8035

Reviewer: fresh goldfish subagent (general-purpose), Mode: REVIEW, zoom_out + implementation_readiness.

VERDICT: PASS

Nothing blocking for releasing this to the one running case. It changes no gate identity and no G2 verdict rule. The test fails without the fix. One limit: what the test proves is the instruction text, not the model's behavior.

**1. Does it fix the loop, and does it touch gate identity?**
- **Fix:** yes, provided the model follows the new instruction. If the row keeps its url and `_search_id`, `finish_freshness_repair` finds exactly one match on the protected fields (factory/run.py:521-526), so it does not re-append the old row. The new `at` clears `evidence_expired`, the error count falls, and `ensure` takes the "fixed" path instead of raising `freshness_refresh_stalled` (factory/ordinary_freshness.py, `finish`).
- **The url is accepted:** `api.github.com/search/issues` does not match `SEARCH_PAGE`, so `search_url_error` returns None. The url therefore stays protected and valid (factory/admission.py:106-115).
- **Gate identity:** unchanged. I hashed `source_inputs` before and after the commit for every root g1–g17, plus `_g2`, the `EXTRA_ROOTS`, the calibrate, make_pilots and calibration_identity roots, and attack_report and stress_request. Every hash is identical, and no root reaches `freshness_topup`. The G2 `STAGE_DEPENDENCIES` files (admission.py, freshness_retrieval.py, independent_review.py) and prompts/ are untouched. The change ships on the plumbing channel only.
- **Verdict rules:** `search_evidence_error`, `superseded` and `REFRESH` are unchanged. Only the prompt's per-row reason text changes, and nothing else reads that reason string.

**2. Conflicts with other rules**
- **Flagged row with `search_page_url`:** no conflict. `flagged_expiry` rewrites the reason only when `search_evidence_error` returns exactly `evidence_expired`, and that check comes after the url check (admission.py:131-139). A search-page url keeps its own reason, so the phrase "even a GitHub search URL" can never apply to a Google or DuckDuckGo url.
- **Unflagged expired rows:** unchanged. They still get the plain `evidence_expired` reason, and the test asserts this.
- **GitHub no-result URL rule:** compatible. `github.com/search` is an accepted url.

**3. Does the test prove it?**
- **Fails without the fix:** yes. I reverted run.py in a scratch copy and the new test failed on the text assertion. With the fix, all 4 tests pass.

**Findings**
- NIT, factory/run.py:654-657: the base prompt still tells the searcher that when a rerun cannot retrieve a row's url, it should log a NEW row that "supersedes the old row". That is false for flagged rows, which are never superseded. The new per-row reason says to amend in place, which mostly overrides it. But for a flagged row whose page is dead, a model could still add a useless new row and leave the old one expired. This was already true before the commit; one clause excluding flagged rows would close it.
- NIT, factory/run.py:654: the shared text still says "retaining … its result page (never a search-results page, except that GitHub no-result URL)". The new per-row line contradicts it for the case's api.github.com url. The more specific per-row line should win, but the two now disagree inside one prompt — the same kind of wording that caused the original loop.
- NIT, tests/factory/test_freshness_concurrent.py:98-104 and 113-116: the fake model always amends in place whatever the prompt says, so the "amending clears the error" half also passed before the fix. The test proves the prompt contains the instruction and that the existing repair path accepts an in-place amend. It does not prove the url-swap loop is gone; only a real model run can show that. It would also help to state that this half is a check against regression, not proof of the fix.
- NIT, operational (not in the diff): case 1108c's log probably still holds the amended copies (issue-page url, ambiguous=true) left by the three earlier attempts. They pass validation, but G2 will judge them as extra flagged rows. Look at the live log before resuming so the reviewer load is not a surprise.

## Elephant's disposition
- Nits 1 and 2 taken in e738ad08 (flagged rows are amended in place, never superseded; an accepted url stays as it is). Review 2 found the second clause unsafe; it was removed in 4c3590eb.
- Test nit: accepted as stated; the second half is a regression guard for the in-place path. Only a real run proves the model complies.
- Operational nit: the two extra ambiguous rows (issue #15868, same query) are valid and go to the G2 reviewer with the rest; the earlier G2 passes judged that same issue page.
