**Verdict: PASS.** No blocking findings. I made no edits, live or paid calls, merges or pushes, and the worktree is still clean.

**Where it stands:** The change at 655b5f0 is the approved design and nothing beyond it. The suite record is genuine: its hash and tree match. The four new tests would fail if the behaviour regressed.

### What I checked
- **Both writer-loop checks** (`factory/run.py:1364-1366` resume, `factory/run.py:1523-1525` fresh completion) keep the `case_hash` equality. For an extension, the second half now uses only full-tree identity against `entry.case_sha256`; otherwise it uses `repair_requested`. With `extension is None` this is exactly the old behaviour. The prototype check (`run.py:1237`) is untouched. The 42 runtime tests are unchanged and pass in the suite.
- **The `after_stop` deletion is complete.** The keyword and its refusal are gone (`factory/extension_package.py:350-355`). Grep finds no remaining uses. Both callers (`:411`, `:415`) are now the same call, and the `raise` after `:415` still passes the original stop through. No catch, retry or result was added.
- **Genuine unchanged behaviour is untouched.** The terminal proof path, the `refuse()` calls for frontier, evidence-name and tree mismatch, and `stop_unchanged` are unchanged. The existing tests for no-op completion, accounting-free replays, completed checkpoints, done-writer, no-repair and invalid proofs are byte-identical and pass.
- **Test changes:** the only file touched is `tests/factory/test_stream_d_unchanged.py`. The only removed assertion is the superseded `test_freshness_only_repair_keeps_evidence_stop_and_open_history`. Its replacement (`:151`) mirrors the existing no-repair route test: builder and attacker each called once, G1, early checks and freshness reached, no outcome, no outcome snapshot directory. Nothing else was weakened.
- **New tests:**
  - **Completed receipt** (`:160`): no writer, only `attacker-9`.
  - **Done-writer recovery** (`:171`): the freshness row is appended before resuming, only `writer_call_done` is authored, and it ends at the stress handoff stub with outcome None.
  - **Real G2** (`:183`):
    - The baseline rows are refreshed to now and set `hit=False`, then a hit with a unique URL is appended.
    - The test asserts repair True and `output_sha256 == before_repair_sha256`, and that `complete_unchanged` returns False.
    - G2 runs for real through `records.capture`, and the test checks `flagged_hits == 1`, exactly one reviewer call, the new URL in the reviewer input and in the retained `verdict.json` and `retrieval/receipts.json`, and that the body bytes equal the saved HTTP bytes.
    - If G2 ignored the new row, nothing would be flagged and the reviewer would never be called, so the count, reviewer and URL assertions would all fail.
- **Count instead of URL in `public-search.json`:** the design (line 68) and the report (lines 17-20) both say it stores counts, not URLs. The exact new URL is still asserted in the reviewer input, verdict and retrieval receipts, as the design requires.
- **Suite record:**
  - The log's SHA-256 is `6216e327…f357`, which matches the JSON record and the report.
  - `655b5f0^{tree}` is `33322355c567b18426f1348e2e49aa01a90d6acc`, which also matches.
  - The log ends with "174 test scripts run; 0 failed."
  - Commits after 655b5f0 change only docs.
- **Merge and scope:** e1087df is an ancestor of HEAD and is the current tip of `factory-simplify`. No Murphy closures. No activation, limit, attribution, schema or version changes. The reroll/progress limitation is deferred to lane 2 (design lines 41-47), and the design's ownership table assigns public-match, blocking-stress and post-extension factory-bug to lane 1.

### Optional nits (not blockers)
- **N1** (`tests/factory/test_stream_d_unchanged.py:226`): `assertIn('"flagged_hits": 1', …)` is a plain text match. It would also accept `10` and breaks if the JSON formatting changes. Parsing the JSON and comparing `== 1` would be more robust.
- **N2** (`test_stream_d_unchanged.py:162-163` and `:173-174`): the same freshness-append snippet appears three times, counting `prepare`'s `noop`. A small helper would remove the duplication. Purely cosmetic.

### Tests run
- I ran `uv run --with numpy --with scipy python -B -m unittest tests/factory/test_stream_d_unchanged.py` at HEAD de628d6: 18 tests, OK, in 53.9 s.
- I did not re-run the full suite. I accepted the recorded run after checking its hash and tree.

## Writer disposition

PASS accepted. No blockers remain. Optional N1 and N2 are deferred to avoid expanding this passing slice; the real G2 result separately asserts flagged_hits == 1. No production or test changes follow review. factory-simplify was rechecked before handback and is already merged.
