# Goldfish diff review: `stream-d-package-freshness` (diff 1)

**Mode:** REVIEW
**Personas:** `zoom_out`, `implementation_readiness`
**Standards:** `zoom-out-standard.md`, `implementation-readiness-standard.md`
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632`, branch `t3/stream-d-gates`
**Range:** `eebbbda4775c7614423163c2b894d21f5a138d8a..HEAD` (one commit, `c68b819`)
**Design:** `docs/designs/stream-d-package-freshness.md` (design review `stream-d-package-freshness-design-1.md`: PASS)
**Scope reviewed:** package increment 1 only, the retained freshness recovery. Package completion is out of scope.

## Verdict: PASS

No blocking findings.

## What the diff does, checked against the design

- **Code change.** `factory/diagnosis_dispatch.py:25` adds `'loop_freshness'` to `CARRY`. It is copied through the existing `copy.deepcopy` loop in `carry_context` (`:280-287`). Nothing else in `factory/` changes. `factory/run.py` and `docs/murphy-register.md` are not in the diff, and `batch_service.DIAGNOSIS_ENABLED` is still `False` (`factory/batch_service.py:21`). This matches the design's "Change and deletions" section and the claims that activation is unchanged, no rows close and `run.py` is not edited.
- **Checklist.** The `docs/designs/stream-d.md` edit splits the package item into increment 1 (small) and increment 2 (large). It is consistent with the design.
- **Records.** The suite record shows the required command, exit 0, and start/finish timestamps. The log ends with `160 test scripts run; 0 failed.` Both touched files ran and passed: `test_freshness_restore_fixes.py` (21 tests, OK) and `test_stream_d_dispatch.py` (57 tests, OK). The design review is saved verbatim with an implementation response.

## Do the tests prove the hint is carried but only the validator grants reuse?

Mostly yes.

- **The hint survives an authenticated admitted replay.** `test_main_recovers_admitted_writer_before_ordinary_launch_twice` seeds `checkpoint_card['loop_freshness']` with a nested value. It then runs the real `run.py` main through `main_resume('active')` twice and checks two things each time: the returned card and the on-disk `scorecard.json` both hold an equal `loop_freshness`. Without the `CARRY` change this fails with a `KeyError`. The test is discriminating.
- **The value is deep-copied.** The harness already deep-copies at `main_resume:174`, and the subprocess goes through JSON, so the replay test cannot prove this. `test_freshness_context_is_deep_copied` proves it directly on `carry_context` by mutating the nested copy and asserting the original is unchanged. This is the right place for it.
- **Reuse comes from the real validator.** `test_diagnosis_republish_recovers_completed_freshness_without_reroll` works as follows:
  - a real `loop_freshness` runs one reviewer call;
  - it persists the scorecard and deletes only `freshness-verdict.json`;
  - `carry_context` runs into an empty `c.card` and the scorecard is republished;
  - real `loop_freshness` runs again, with any reviewer call raising.

  It asserts no reviewer call, empty `blocking`, an unchanged report, and a rebuilt `freshness-verdict.json`. Without the fix, `retained` is `None`, there is no receipt, and a new review starts, so the test goes red. The reuse goes through the existing `confirm_hits` retained-path branch (`run.py:2211-2236`), which checks the completion marker, case hash, search binding, retrieval digest, 24-hour mtime and `checked_freshness_verdict`. No new authority is added.
- **The validator refuses a partial answer.** `test_diagnosis_republish_cannot_reuse_without_completion_marker` deletes `review-completed.json`, republishes, and asserts exactly one new reviewer call. A carried path on its own does not grant reuse.
- **A public match is still a G2 failure.** `test_diagnosis_republish_preserves_public_match_failure` asserts that the recovered run raises `freshness_public_match` without a reviewer call and that `outcome == 'public_match'`.

The design said this is offline mechanics evidence, not live interruption evidence, and the tests stay within that. No Murphy row is claimed.

## Blockers

None.

## Non-blocking findings

1. **Nit (readiness / test strength): `tests/factory/test_freshness_restore_fixes.py`, `test_diagnosis_republish_preserves_public_match_failure`. The `gates['G2'] == 'fail'` assertion is satisfied by carried state.**
   - `completed_review_checkpoint(public_match=True)` already sets `c.card['gates']['G2'] = 'fail'` and persists it.
   - `CARRY` includes `'gates'`, so `diagnosis_republish` copies `G2: fail` into the new card before the second `loop_freshness` runs.
   - The assertion would pass even if recovery never set G2 again. The real proof is the `assertRaisesRegex('^freshness_public_match$')` plus the fresh `outcome == 'public_match'`, which `loop_freshness` overwrites.
   - **Suggested fix:** pop `gates`, `failed_gate` and `gate_results` from `self.c.card` after republishing. Then the G2 assertion proves that recovery re-derived the failure.

2. **Nit (readiness / test strength): `test_diagnosis_republish_cannot_reuse_without_completion_marker` doesn't confirm the hint was present.**
   - The test passes whether or not `loop_freshness` was carried, because a missing pointer also forces a new review.
   - To show that the validator rejected a hint that really was present, assert after republishing that `json.loads(scorecard)['loop_freshness']['verdict_path']` equals the deleted-marker directory's `verdict.json`.
   - The positive test already proves the hint is carried, so taken together the claim holds. This assertion would make the negative test prove it alone.

3. **Nit (consistency): the three new restore tests omit `self.addCleanup(offline_router()[0].close)`.** The neighbouring `loop_freshness` tests in the same file call it. The suite passes, so it is probably not needed on this non-`factory_job` path. Add it for symmetry, or leave it.

## Zoom-out

- **Root problem.** Republishing dropped the only pointer that the existing fallback uses. The fix restores that pointer in the one place cards are rebuilt (`CARRY`). It is not a local band-aid.
- **Simplicity.** The change is one line of code and reuses the existing deep-copy path. It adds no new recovery mechanism, allowance or helper. The tests reuse the existing harnesses as the design review recommended (`test_stream_d_dispatch` saved case/ledger and the `test_freshness_restore_fixes` transport) and don't build a third harness.
- **No dead ends.** A stale carried `loop_freshness` stays harmless, as the design explains. `recovery.freshness_retry_stop` acts only on `freshness_unresolved`, which `loop_freshness` raises only after it has overwritten the key.

## Implementation readiness

The diff carries out every item in the design's test plan:
- two-replay publication with deep copy;
- local HTTP retrieval with an explicitly authored model answer;
- deleting only the binding receipt, with the marker, the verdict younger than 24 hours, the snapshot and `retrieval/` all kept;
- no second reviewer call, an unchanged report, and a rebuilt receipt;
- one missing-marker negative case;
- public match still failing G2;
- the full suite logged and committed.

Nothing in it needed the implementer to make a design decision.

**Result: PASS.** Nits 1–2 would make the tests stronger and are optional.

## Implementation response

PASS with no blockers. Optional test-strength nits are retained for a future test edit; the reviewer confirms the combined positive/negative tests prove the intended contract. No code changed after this review. No Murphy rows close.

