**Verdict: PASS.** No blocking findings remain. I made no edits, ran no tests, made no live or paid calls, and did not merge.

**Where it stands:** All three round-1 fixes now hold up against the code. The G2 test would now fail if G2 ignored the new row, so B1 is closed. The routing change is the same as in round 1, and I re-checked it at the current HEAD (6b1c482).

### Re-checked against the code
- **The two check sites match the design.** In `factory/run.py:1364-1367` (resume) and `factory/run.py:1523-1526` (fresh completion), the `case_hash` equality stays. The second half becomes: for an extension, compare the full tree with `entry.case_sha256`; otherwise use `repair_requested`. When `extension is None`, that reduces to today's behaviour. The `after_stop` keyword (`extension_package.py:350`), its refusal (`:355`) and the call that passes it (`:416`) are the code the design deletes.
- **B1 is fixed: the G2 test can now fail.**
  - `_g2` sets `flagged_hits = len(flagged)`, counting only rows marked as hits or ambiguous (`run.py:2181,2195`).
  - The old rows are kept as non-hits, so if G2 skips the new row, `flagged_hits` is 0. The reviewer is also never called, because `confirm_hits` only runs when something is flagged (`run.py:2192`). The new URL then could not appear in the reviewer rows, the verdict or the retrieval receipts. Every one of the design's assertions would fail.
  - The planned URL passes `search_url_error` (`admission.py:94-102`). The patched `fetch` returns `final_url = url`, just as the existing test's fetch does.
  - The test class supports this: `UnchangedTests` builds on `ExecutionTests.setUp`, which patches `loop_freshness`, not `run.g2`. So `run.g2`, retrieval and the validators run for real.
- **M2 is fixed.** The done-writer test now says to append the row before resuming, and lists the expected results: no `builder-9`, one `attacker-9`, G1 called, `outcome` None, no outcome snapshot directory, and a stop at the `test_stress_handoff` stub. This matches the existing no-repair test (`test_stream_d_unchanged.py:115-124`).
- **M1 and N1–N3 are handled.** The reroll limitation is stated and assigned to lane 2. The fallback is described as not expected on a live path. The plain-language objective is the first sentence. The estimate now includes the G2 evidence test.
- **The ownership table is consistent.** It lists six slices. Lane 1 has 8–13 h and lane 2 has 16–26 h, which adds up to 24–39 h. It assigns no Murphy closures and changes no activation, limits, attribution, schema or scientific version.

### Nit (optional)
- **N-a (design lines 62-67): the old rows have expired.** The saved practice rows are older than `SEARCH_TTL` (24 h, `admission.py:15`). `search_evidence_error` would mark them `evidence_expired`, which forces `invalid > 0` and skips the reviewer. So the test must first refresh their timestamps to now with `hit=False`, the way the existing test does (`test_stream_d_execution.py:284-288`). "Use the existing fixture's old rows" implies this, and the test would fail loudly without it.
  - Admission already happens in `setUp`, so the refresh runs after admission. The freshness change is then the refresh plus the append, not a single appended row. The test's conclusions still hold, because `case_hash` ignores `freshness.jsonl` and the new-URL assertions only depend on the appended row.
  - A one-line note in the design would remove the guesswork.

As planned, the land-8 merge containing 184e81c has to land before implementation starts.

## Writer disposition

PASS accepted. N-a is incorporated: refresh saved baseline timestamps after admission and mark those rows non-hit before appending the unique hit. Implementation waits for the required land-8 merge.
