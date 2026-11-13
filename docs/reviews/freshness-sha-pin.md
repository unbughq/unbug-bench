# Goldfish review: SHA-pinned case freshness version (1110b)

Reviewer: fresh Claude subagent, given only the diff and the bug statement. It ran
`tests/factory/test_loop_freshness.py` (24/24) and `tests/factory/test_freshness_restore_fixes.py`
(18/18), and confirmed the new SHA-pin test errors with the `run.py` fix removed.

**PASS**

1. **NIT, `factory/run.py:1192`:** `v2.19.0` and `2.19.0` count as two versions, so the case
   stops needlessly. Strip a leading `v` as `durable/admission_reasons.py:134` does.
2. **NIT, `factory/run.py:1192`:** the version comes from model-written rows and is not checked
   against the pinned SHA. Adds no new trust: flagged rows already carry their own model-written
   `app_version` into `confirm_hits`, which checks the reviewer's answer against it. Later, resolve
   SHA to tag from the repo or image.
3. **NIT, `factory/freshness_fanout.py:90`:** `pinned_version(c)` duplicates the old case.json-only
   lookup; rows fanout writes on a SHA-pinned case would carry an empty `app_version`.
4. **OK, `tests/factory/test_freshness_restore_fixes.py:127`:** the test edit does not hide a
   regression; it still covers the "no version anywhere" stop and asserts no reviewer call.

---

## Resolution (elephant)

- **1: taken.** Test first: a `v2.19.0` row added to the SHA-pin test failed on the branch, then
  passed after normalising the prefix.
- **2: not taken.** Same trust level as flagged rows today; noted in the PR as the known ceiling.
- **3: rejected.** `fan_out` returns at once when `pinned_version(c)` is None
  (`freshness_fanout.py:268-269`), so on a SHA-pinned case fanout writes no rows at all; it cannot
  write empty-version rows. Fanout being skipped on SHA pins is a separate gap (it is an opt-in
  flag) and is left for its own change.
