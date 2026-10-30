The verdict is PASS with no blockers: the rebase left B's code unchanged apart from one test line that had to merge with the maxima change, and the full suite passed (146 test scripts, 0 failed). Here is the full review; I saved no files.

---

# Goldfish review: B final rebase/integration (B2b.2 accounting + projection, factory_bug_held status)

**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, HEAD `5067d5d`
**Mode:** REVIEW. **Personas:** `zoom_out`, `implementation_readiness`. **Standard:** `implementation-readiness-standard.md`, ENGINEERING.md §1 step 5.
**Scope:** only what changed because of the rebase onto `49b178b` (router maxima). The designs (status held design 2, batch-service design 15) and the pre-rebase diffs (`batch-status-held-diff-1.md`, `batch-service-diff-13.md`) already passed and are not re-reviewed.

## Verdict: PASS, no blocking findings

## Evidence

1. **Base.** `49b178b` is an ancestor of HEAD. The B commits sit on top in this order: `f334be1`, `22894b2`, `ad765e2`, then `5067d5d`, which is docs only (+51 lines: an appended note in `batch-service-diff-13.md` and `batch-service-practice-route-block-20261030.json`).
2. **Status commit `f334be1` vs pre-rebase `23e29b1`.** The patches are byte-identical once `index` lines are ignored, and the stable patch-ids match (`0472bc66…`). The code did not change.
3. **Accounting commit `22894b2` vs pre-rebase `6a69978`.** The patch-ids differ, but the patch text differs on exactly one line (diff line 988), in `tests/tools/test_launch_manifest.py`:
   - The context line now includes `'factory/model_call_gate.py'`, which the maxima merge added to `expected_worker`.
   - B's own change is unchanged: `'factory/batch_status.py', 'factory/batch_accounting.py',`.
   - This is a correct merge of the two changes, not new B behaviour.
4. **Files both sides touched.** Only `factory/launch_manifest.py` and `tests/tools/test_launch_manifest.py` overlap. Maxima added `token_prices.py` and `model_call_gate.py` to `TRUSTED_FILES` and `REQUIRED_RELEASE`. B adds `batch_accounting.py`. The two sets are disjoint and the merged manifest test passes inside the full suite.
5. **Maxima API agreement.**
   - `factory/batch_accounting.py` imports only the standard library and `batch_money.amount`. It does not depend on `model_router`, `model_call_gate` or `Lease`.
   - `maximum_usd`, `booked_usd` and `remaining_usd` are row fields the module validates itself.
   - The maxima merge does not touch `budget.py`, `diagnosis.py`, `batch_service.py`, `batch_status.py`, `collection.py` or `batch_money.py`, so B's accounting and projection inputs have the same shape as when they were reviewed.
   - B's diff adds no `Lease(` construction or `route_maximum` use. The reserve helper in `tests/factory/test_stream_d.py` is the explicitly synthetic-maximum, accounting-fixture-only helper described in the brief, and it comes from the maxima side.
6. **Focused tests at HEAD (this review).**
   - `test_batch_accounting`: 12 tests, OK.
   - `test_batch_service_d` + `test_batch_status`: 23 tests, OK. This covers projection (9), the factory_bug_held known unscored status action and the saved-card tests.
7. **Authoritative full suite.**
   - Log: `/tmp/unbug-b-49b178b-suite.log`.
   - The process's working directory was this worktree; HEAD `5067d5d` (05:49) changed only docs after the log started at 05:48, so the run covers all B code.
   - Footer: **`146 test scripts run; 0 failed.`** No `FAIL` or `Traceback` lines in the log. The last script reported `Ran 9 tests … OK`. Its `Unlock diagnostic … RuntimeError` line is expected diagnostic output from a passing negative test.

## Items checked and accepted (not blockers)

- **Route admission is blocked, as expected.** `route_maximum` covers only the Claude $50 route, which is above the user's $3 limit. B claims no live qualification, and `batch-service-practice-route-block-20261030.json` records the block correctly. The cheap route is with A.
- **The carry-over backlog `new-batch-service-4` stays deferred.** Nothing in the rebase starts implementing it. That is correct.
- **No Murphy rows closed.** No `Closed by` was set, so there is no closure test for a diff goldfish to verify.

## Nits (optional)

- The `Reviewed-by:` trailers on the merge commit should also cite this integration review once the elephant saves it.

**Result: PASS. No blockers. Full suite at `49b178b`+B: 146 test scripts run, 0 failed.**


## Elephant resolution

PASS accepted. No blocking findings or rejections. Full suite146 scripts,0
failures independently checked. Adapter remains False; live practice route cap
and holder/publication/source integration remain prerequisites, no row closure.
