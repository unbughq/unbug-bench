**PASS.** The fix commit closes both blockers from diff-1, and no blocking finding is left open. HEAD is `eae085f`, base `54344fc`.

I read `docs/ENGINEERING.md`, both personas, the readiness standard, the design's test section and diff-1, using Mode: REVIEW. I changed no files, started no subagents and created no checkout. The worktree is clean.

## What I checked myself

- **Package tests:** I re-ran `tests/factory/test_stream_d_execution.py`: 27 tests, OK. The dispatch tests (`test_stream_d_dispatch.py`) also pass: 57 tests, OK.
- **Suite record:** the record's tree `0a3d1e3…` matches `58b2625^{tree}`, and the log's sha256 `06e2096…` matches the record. It shows 160 scripts run, 0 failed.
- **No production changes since diff-1:** after `d1917ed`, only `tests/factory/test_stream_d_execution.py` and `docs/` changed. The production files on the branch (`diagnosis_dispatch.py`, `extension_package.py`, `gate_pipeline.py`, `run.py`) are the same ones diff-1 reviewed.
- **Scope:** `murphy-register.md` is untouched and no closures are claimed. The "Package increment 2" checkbox at `docs/designs/stream-d.md:3726` is still open. There is no terminal-outcome, entry-capture, comparison, routing or lane-1 work in the branch.

## B1: dispatch recovery after history commits before the card — closed

Test: `test_dispatch_recovers_history_committed_before_card` (`test_stream_d_execution.py:559-579`).

- It uses a real admitted row and a real package completion, then rolls the card's `extension_history` back to `outcome_sha256=None`.
- It then calls the real `apply` with `resume=True` and `DIAGNOSIS_ENABLED` patched on, while `writer_receipt` raises if called.
- It covers all four pieces diff-1 named (`diagnosis_dispatch.py:236-247`):
  - **History lookup:** `active()` is None, so `apply` falls back to the last history row.
  - **`exhaustion_id` match:** the matching ID takes the recovery route.
  - **Routing:** if `apply` read the outcome from the lagging card, it would take the `writer_receipt` path and the test would fail. So the test does tell the two routes apart.
  - **Return value:** it asserts the extension ID comes back.
- **Different exhaustion:** with another ID, `row` is None and `apply` falls through to `stop(STOPS['close_to_passing'])`. The test asserts `^extension_comparison_pending$`, which is the plain stop label (`diagnosis_dispatch.py:30`).

## B2: real G1/G2 runs and the evidence-root table — closed

- **G1** (`:264-277`): runs the real `run.g1` over the practice case. That case comes from `invalid-runs-practice.json.gz`, and the setup checks each file's sha256.
  - It asserts `content_checks == 'on'`, that scenarios were counted, and that replay matches.
  - It checks that `case.json`, `base/app.patch` and `promise.md` were retained byte for byte.
  - It does not assert pass or fail, which matches its stated purpose of keeping the real diagnostics.
- **G2** (`:279-314`):
  - The saved HTTP fixture's hash is checked first.
  - Only two things are authored, and both are named as such: the external fetch transport and the model's answer.
  - The real `run.g2`, retrieval and confirmation validators run.
  - It asserts that `public-search.json`, `freshness-verdict.json`, `verdict.json`, `review-completed.json`, the retrieval receipts, the `.body` files (exact bytes) and `confirmation-retrieval-*` were all retained.
  - Replay runs with both the fetch and the model answer set to raise, so it is proven to make no network or model call.
- **Root table** (`:316-370`):
  - The expected roots are written out in the test rather than taken from `Records.sources`, so deleting a root fails the test.
  - Broadening the calibration filter is also caught, because `workspace/private.txt` and `prompt.txt` are planted as files that must not be copied.
  - It covers transcript selection (an `unrelated.jsonl` is planted and must be left out), checks copied bytes, and checks that pilot homes are never touched.
  - The expectations match `extension_package.py:141-159` rule for rule.

## Blockers

None.

## Optional (non-blocking)

- **M4. The B1 test passes even if the `completed_route(c, row)` call at `diagnosis_dispatch.py:245` is removed.** `completed_route` only checks that the stress record exists and is valid (`extension_package.py:263-267`), and the test never makes that check fail. Suggested fix: delete or tamper with the stress record, then assert that `apply` raises `extension_outcome_changed`. diff-1 did not ask for this, so I'm not treating it as a blocker.
- **Nit.** In the root table, the "no pilot" assertion (`:370`) can never fail, because no pilot directory is in any root list. It is harmless and documents the rule.
- **Earlier items.** diff-1's M1–M3 and nits 1–5 are still recorded as non-blocking. Nothing in this fix reopens or worsens them.

## Zoom-out

The fix adds only tests: no new production paths, no helpers and no speculative scaffolding. The tests reuse the existing setup (`ExecutionTests.setUp`, `test_scientific_receipts` fixtures), and authored inputs are limited to the external fetch transport and model answers, as the design allows.

## Out of scope (not reviewed, as instructed)

Terminal writer and public-match outcomes, entry capture, isolated comparison and version drift, diagnosis routing, lane-1 legacy allowances, live qualification, and Murphy closures. I did not start package increment 2.

**Verdict: PASS.**

## Implementation disposition

Accepted PASS. B1 and B2 are independently closed by this fresh review. Optional M4 and the earlier non-blocking recommendations remain recorded; no additional scope is started. No Murphy rows close. The package completion checkbox remains open for deferred work.

