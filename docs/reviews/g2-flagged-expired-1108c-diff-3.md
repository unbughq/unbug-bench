# Diff review 3: G2 top-up flagged expired row (1108c), 625ce7e0..4c3590eb

Reviewer: fresh goldfish subagent (general-purpose), Mode: REVIEW, zoom_out + implementation_readiness.

VERDICT: PASS

The diff only changes the attacker/builder top-up prompt. It doesn't touch any verdict rule or gate identity. If the model follows the new per-row instruction, 1108c's loop ends. If it ignores it, the result is the same retryable `freshness_refresh_stalled` as before, so it is not worse and no defect is charged.

**1. Is the loop fixed, and is identity unchanged?**
- **Loop:** yes, if the model complies.
  - `flagged_expiry` only fires when the row's first error is `evidence_expired`. In `search_evidence_error`, that check runs after `search_url_error`, so the url is valid at that point. A valid url is a protected field in `finish_freshness_repair` (run.py ~520–525).
  - So a row amended in place with the same `_search_id`, who/kind/query and url makes exactly one match and is kept. The error count drops and `ensure.finish()` sees progress (`fixed`).
  - The api.github.com search url passes `search_url_error`: `SEARCH_PAGE` doesn't match it, and api.github.com is an allowed GitHub host.
- **Identity:** unchanged.
  - The diff touches only `factory/run.py` (`freshness_topup` and `_freshness_searches`) and the test.
  - I hashed `source_inputs` for roots g1–g17 (g12 has no root), plus the two `judge_dependencies` root sets, against the old and new run.py. Every one is the same; neither changed function is reachable from any gate root.
  - None of the G2 `STAGE_DEPENDENCIES` files and nothing under `factory/prompts/` changed, so the `run.prompt("reviewer")` hash is unchanged.
  - `admission.py`, `_g2` and `ordinary_freshness.py` are untouched, so no G2 verdict rule changed.

**2. Is the prompt consistent?** No blocking contradiction.
- The per-row reason (run.py:554–561) explicitly makes an exception to the general rule ("keep its url exactly as it is, even a GitHub search URL") and is limited to that one row. The parenthetical "a flagged row … is never superseded: it is amended in place instead" (run.py:682) agrees with it.
- The general `search_page_url` rule (run.py:670) can't apply to the same row. That reason is only sent when `search_url_error` failed, and in that case the url is unprotected and may change.
- Because only the first error is reported, the keep-url text can only appear when the url is already accepted. That avoids the problem that led commit 4c3590eb to drop the earlier clause.

**3. Does the test prove the change?** Yes.
- `BENCH=… python3 -B tests/factory/test_freshness_concurrent.py` passes all 4 tests on 4c3590eb.
- I copied 4c3590eb's tree into the scratchpad and swapped in the old run.py from 625ce7e0. The new test then fails at `tests/factory/test_freshness_concurrent.py:110`: the attacker prompt has only the bare `"evidence_expired"` for row 9.
- Its second half (amended in place, then one row kept and no error) also passes on the old code. It confirms `finish_freshness_repair` keeps an in-place amendment rather than proving this change. That is fine as a regression guard.

**Findings**
- **NIT (run.py:675 and run.py:680):** Two general rules still literally contradict a flagged api.github.com search url: "the only search URL G2 accepts", and "never a search-results page, except that GitHub no-result URL". That second rule is what drove the 1108c swap. The per-row text overrides both, but the override is the only guard. Adding "or a flagged row's accepted url" to the run.py:680 parenthetical would remove the conflict without affecting identity.
- **NIT (run.py:558):** Because only the first error is reported, a flagged GitHub-search-url row whose first error comes earlier (for example `missing_note` or `invalid_app_version`) gets no keep-url hint. If the model swaps its url, the original row is re-appended with the non-refresh error, and `metadata()` charges that as a defect. This existed before the diff and isn't in 1108c's facts. To close it, base the hint on `search_url_error(row) is None` for flagged rows instead of on the first error.
- **NIT (zoom_out):** The scope is right: a prompt-only change in the one closure, no new paths, no YAGNI. Nothing to reuse instead.

## Elephant's disposition
- Both prompt nits deferred: optional, not in 1108c's facts, and every further prompt edit on the critical path costs another review round. Worth taking on factory-simplify/main together with a Murphy row (this lineage has no docs/murphy-register.md).
