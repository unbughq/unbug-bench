I found no blocking issue, so the verdict is **PASS** (0 Blocker, 0 Major, 1 Nit). The flagged dead-URL hole from round 3 is fixed with a one-line move. Every earlier finding, including diff-1 B1 and M1–M4, stays fixed. The rebase onto `ac33267` doesn't open a new way to score or restart a broken run. I ran no tests or workloads, as required. Full review text for you to save verbatim:

---

# Invalid-runs diff review 4: PASS (0 Blocker, 0 Major, 1 Nit)

**Range:** `ac33267..ebed7c2` on `invalid-runs`.
- The merge-base equals the `factory-simplify` tip `ac33267`, so the branch is rebased.
- Since diff-3, the branch adds `676db10` (the fix plus its test), `9de2247` (design and response text) and `ebed7c2` (validation record only).

**Mode:** REVIEW, against the Zoom-Out and Implementation-Readiness standards. Heilmeier was design context only.

**How I reviewed:** read-only. I read the design, including all three normative diff-review sections, the diff-3 review and response, the validation record, the fix and its test assertions, the compatibility pins and the code the single-path base increment touches. I ran no tests or workloads.

## Independent checks at HEAD

- **Pins:** every `current_files` digest in `factory/invalid-runs-compat.json` matches the file at HEAD. Every `base_files` digest matches `6f17c5f`, which is an ancestor of `ac33267`. That includes `case_contract.py`, and `bin/run_validity.py` is pinned as absent in the base.
- **Runner AST pins:** all seven `current_runner` entries equal `gate_state.source_inputs('calibrate','checkpoint','verdicts')` at HEAD. `signal` is absent and `time`/`tree_digest` are present, exactly as pinned.
- **Migration code:** `compatible_identity` still drops an absent target rather than keeping it, and returns `False` for any digest it does not know.

## Diff-3 B1 (flagged dead URL counted): resolved

- **The fix:** at `factory/run.py:1655-1656`, the `retrieved_from == 'none'` check now runs after both the flagged `retry(...)` branch and the unflagged `try` branch. Flagged and unflagged rows with identical runner bytes are now treated the same.
- **Other ways the row could still count:**
  - `freshness_counts` (`:1615`) drops every row in `freshness_unfetched`.
  - Cached reuse at `:1665` requires `freshness_unfetched` to be empty.
  - `admission.reusable_search` re-checks the minimums.
  - `freshness_topup` (`:360-362`) marks the row `runner_retrieval_unavailable`, which makes the bounded topup ask for an alternative.
  - No other code computes search counts.
- **Archive-backed rows** (`retrieved_from='archive'`) keep their bytes and still count, which matches the archive ruling.
- **Regression test:** `test_dead_flagged_result_clears_the_hit_but_never_fills_a_search_minimum` uses the real practice log.
  - It asserts the starting counts are exactly 3 / 3 / 2.
  - It flags the unique GitHub URL and patches only `freshness_retrieval.fetch`: a 404, then an empty `archived_snapshots`.
  - The reviewer seam writes an answer that agrees with the runner receipt, so the real `confirm_hits` and `checked_freshness_verdict` run.
  - It asserts: `unreachable_hits == 1`, `hits == 0`, `counted.builder_github == 2`, outcome `evidence_incomplete`, `unfetched_searches == 1`, and no `public-search.json`.
  - These assertions test the right property: the hit clears, but the search does not count.

## Earlier findings: still resolved at HEAD

| Finding | Status |
|---|---|
| Diff-1 B1 (G16/G17 evidence) | Resolved. Every try workspace, including early-probe and replacement workspaces, is a digest-bound input. Owner transcripts are copied. Missing inputs are refused. This code was not touched after diff-3. |
| Diff-1 M1 (missing-fix replacement) | Resolved. Each missing try gets its own one-try series, reviewed in the same invocation. A completed no-fix replacement is never bought again. The original G10 records and the valid suffix are kept. Not touched. |
| Diff-1 M2 (blocked unflagged URL) | Resolved. Unfetched unflagged rows are uncounted, their history is kept, and the bounded topup asks for alternatives. Dead pages are now uncounted for flagged rows too. |
| Diff-1 M3 (row 36 wording) | Resolved. Infrastructure exhaustion is an unscored stop for stream D's diagnosis, never a candidate rejection. |
| Diff-1 M4 (retry allowance after success) | Resolved. A success clears `invalid_attempts`. |
| Diff-2 B1, M1, N1–N3 | Resolved. Nothing in that code changed after diff-3. |
| Diff-3 N1 / N2 | N1 is resolved: the design (`:457-458`) now says the bound is two attempts per unchanged runtime. N2 (re-fetch latency) was accepted, and no speculative cache was added, which is correct. |

## Rebase onto `ac33267` (single-path increment)

- **Base changes:** in `factory/run.py`, the base adds only `--case-id` / `--batch-release-sha256` argument checks and stamps the card. `factory/batch.py` adds no scoring reader. No single-path contract is edited on this branch.
- **Worker inventory:**
  - `launch_manifest.py` keeps `batch.py` and adds `collection.py` (trusted host), `run_validity.py` (worker bench) and `invalid-runs-compat.json` (worker config).
  - The test's expected set names `batch.py` plus all four C helpers.
  - `BATCH_SOURCE` already ships `factory/`, so the release carries the compatibility file.
- **Restarting an exhausted case:**
  - A batch continuation goes in as `--restore` with mode `case`. `key_holder` then calls `require_holder_stop`, which raises on `infrastructure_exhausted`.
  - The Boat path goes through `launch.sh` → `raised_limits`, and `restart.py` → `require_restart_stop`. Both refuse an exhausted card.
  - `factory_auto_resume` returns early for batch releases.
  - None of the new single-path routes can restart an exhausted case or turn an infrastructure failure into a scientific failure.

## Nit

- **N1.** `docs/reviews/invalid-runs-validation.md:11` points the full-suite log at `/tmp/invalid-runs-full-suite-final-rebased.log`. Only its SHA256 is durable, and `/tmp` will not survive.
  - **Fix (optional):** keep the log alongside the other retained validation outputs, or say in the record that only the hash is retained.

## Not judged

- Whether the suite passes. I relied on the saved record (133 scripts, 0 failed; 34 invalid-run tests; 8 archive-ruling tests).
- Live S11 qualification. Row 14 correctly stays open because launches are prohibited here.
- Remote VM card provenance, beyond the documented card-only limit.
- How good the models' adjudication would be.

**PASS:** no blocking issue remains.

## Elephant response

PASS accepted; no blocking or major findings remain. N1 is addressed by clarifying
in the validation record that the full-suite log is temporary and only its hash is
durably retained. This commit changes review/validation documentation only.
