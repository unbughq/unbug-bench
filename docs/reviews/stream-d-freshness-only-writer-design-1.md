**Verdict: BLOCK.** There is one blocker, and it is a test-plan gap. The code change itself is sound.

**Where it stands:** The routing change is correct and narrow, and deleting `after_stop` is safe. Nothing in the design re-runs an identical input. The one fix needed is in the G2 test: as written, it would still pass if G2 ignored the new freshness row.

### What I verified
- **Only two check sites, and non-extension behaviour is unchanged.** `factory/run.py:1364-1367` (resume after a completed writer) and `factory/run.py:1523-1526` (fresh writer completion) are the only `unchanged_repair` checks on the extension path. The prototype check at `run.py:1238` only runs without an extension. With `extension is None`, the new conditional reduces to `repair_requested`, which is exactly what happens today.
- **The bug is real.** `case_hash` skips `freshness.jsonl` (`run.py:891-898`). So today, a repair-requested writer that only appends a freshness row raises `unchanged_repair`. `complete_unchanged(after_stop=True)` then refuses at `extension_package.py:355`, and the extension history stays open. The no-repair variant already continues (`test_stream_d_unchanged.py:115-124`).
- **Deleting `after_stop` is correct.** Under the new rule, an extension only raises `unchanged_repair` when the full tree equals the entry's `case_sha256`. So the refusal at `extension_package.py:355` can no longer be reached. Line 416 becomes the same call as line 412, and the existing `raise` already passes the original stop through. No test passes `after_stop`.
- **Identical input still ends the extension, with no new writer round.** A truly unchanged tree still produces the unchanged-writer proof, for either repair flag. "Scientifically different" is measured on the full tree including freshness, which matches the comparison binding at `extension_compare.py:54-57`. Writer recovery still goes through `extensions.writer_receipt` and `writer_intent_valid`, and nothing there changes.
- **No other path touches this.** The other `extension_snapshot_changed` tests (`test_stream_d_comparison.py:161-166`, `test_stream_d_execution.py:261`) cover entry capture and corrupted records. This change does not affect them.

### Blocker
**B1: the G2 test cannot fail if G2 ignores the new row** (design lines 62-68). The design says the test "verify[ies] the terminal producer declines before the real freshness path consumes it", and claims this "proves the distinction matters to bench science". But it never says what to assert about G2's result. If the test only checks that `complete_unchanged` returns False and that `run.g2` passes, it passes whether or not G2 read the appended row. That is a fixture proving nothing, which `docs/ENGINEERING.md` §4 rules out.

Required fix:
- State the order of steps: append the row, run `complete_writer` on the saved receipt (with repair True, `output_sha256 == before_repair_sha256`), assert `complete_unchanged(...)` is False, then `records.capture(..., 'G2', lambda: run.g2(c))`.
- Make the appended row a well-formed hit that the authored reviewer answer covers.
- Add an assertion that fails if the row is ignored. For example: `flagged_hits` is one higher than in the existing `test_real_g2_retains_freshness_confirmation_and_response_bytes` baseline, or the retained `public-search.json`/verdict names the new row.

### Optional findings
- **M1 (Major, rerolls; lines 8-9 and 42).** The design says G2 reads the new evidence. But `gate_state.inputs` leaves `freshness.jsonl` out for every gate except G8 and G9 (`gate_state.py:150`). G1, G3, G7, G10, G11 and G17 have no pass cache, so they re-run on unchanged files. That is effectively a fresh roll of those model gates, and a lucky result could count as progress. This is not new: the no-repair route and a `BUILD-NOTES.md`-only edit already behave this way. The design should state it plainly, and the rejected-writer/progress slice should own it.
- **M2 (Major, readiness; lines 56-60).** The done-writer recovery test does not say to append the freshness row before resuming, since no writer call happens there. It also gives no expected outcome. Expected: no `builder-9` call, one `attacker-9`, G1 called, `outcome` None, no `extension-snapshots/1/outcome` directory, and a stop at the `test_stress_handoff` stub.
- **N1 (Nit, lines 34-35).** The "propagate that original stop" path at `extension_package.py:416-417` can no longer return False, because `unchanged_receipt` requires before == output == `case_hash`. It is fine to keep, but the design should say so instead of describing it as a live case.
- **N2 (Nit, Heilmeier objective).** The opening paragraph is all code terms (`case_hash`, `unchanged_repair`, G2). Add one sentence for a newcomer: "a writer that only added search evidence is wrongly frozen; let it go through normal checks."
- **N3 (Nit, line 72).** The 1-3 h estimate does not include writing B1's comparison against the baseline. It is still small.

### Remaining-slice estimates
The arithmetic is correct: 6-10 + 3-5 + 2-3 + 6-10 + 3-5 + 4-6 = 24-39 h. Against the item 7 text (`stream-d.md:1632-1638`), package increment 2 and "All diagnosis outcomes" (`stream-d.md:3740-3745`), and Murphy `new-stream-d-current-comparison-1`, I found no missing item 7 obligation. Two things are covered elsewhere and are optional to state:
- Moving factory-bug resume cost to the infra-waste line (`new-stream-d-outcome-routes-1`) belongs to lane 1, in `stream-d-factory-bug-attribution.md`.
- Item 7's rule that an ordinary `unchanged_repair` case must have its writer receipt replaced through B's checkpoint adapter appears to be met already by extension admission. The table could note that it is satisfied, with a reference.

No Murphy rows close, and there are no activation, limit, schema, scientific-version or attribution changes. That matches the scope.

## Writer disposition

B1 accepted: revised test plan requires the new hit to appear in retained search/verdict/retrieval evidence and the reviewer input. M1 is explicitly assigned to lane 2's rejected-writer/progress work; M2 and N1–N3 are clarified. Slice ownership is updated to the parent's split. No implementation yet; fresh round-2 review requested.

