# Diff review 1: g2-18681d-hand-check (goldfish)

**Reviewer:** a fresh goldfish (Claude), with no prior context and read-only. I used the personas `zoom_out` and `implementation_readiness` in `Mode: REVIEW`, and read `docs/ENGINEERING.md` sections 1, 2 and 4.

**Scope:**
- **The entry.** Branch `fix/g2-18681d-hand-check`, `origin/main` 616ad550..3960b8ea, which touches `factory/run.py` (+11) and `tests/factory/test_g2_blocked_source.py` (+8/-2). I reviewed it against operator step 4 and section 3 of `docs/designs/g2-blocked-source.md`, and against the founder decision of 2026-11-20 as the spec.
- **The hotfix.** Branch `hotfix/g2-18681d-3dfdde3c` at 491b3dca, meant to be the batch source 3dfdde3c plus the G2 commits plus this entry.

**What I ran:**
- **Fixture key.** I read `tests/factory/fixtures/g2-blocked-source.json`. 18681d has `statement_sha256` `50f568b8…b5df5d5` and URL `https://www.answeroverflow.com/m/1273391376289239134`. Both match the entry byte for byte. The fixture is not touched by this diff; it comes from 15dfac53.
- **Tests on the worktree.** `test_g2_blocked_source.py`: 13 tests OK.
- **Tests on my own archives** (in my scratch folder):
  - 3960b8ea: `test_stream_d_retries`, `test_freshness_archive`, `test_freshness_restore_fixes` and `test_admission` all OK.
  - 491b3dca: `test_g2_blocked_source` (13 OK) and the same four suites, all OK.
  - I did not run the full `tests/run.py` suite. That is the elephant's step 4.
- **Mutation test of the shipped entry.** I wrote 14 changed copies of 3960b8ea's `run.py`, one mistake each, and ran the suite on each. Every one failed at least one test:
  - `reports_this_bug` set to True, or to the string `"false"`;
  - one hex digit of the digest changed;
  - a trailing `/` on the URL;
  - an unknown extra key;
  - `page_says` left blank;
  - `checked_at` not in `YYYY-MM-DD` form;
  - an empty `checked_by`;
  - `kind` changed to `not_needed`;
  - `gate` changed to G3;
  - `by` changed to `claude`;
  - the `hand_check` dict removed;
  - the entry dropped;
  - the entry duplicated.

  Main catchers are `test_a_hand_check_settles_18681d_either_way` and `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case`. The new assertion at test lines 82-87 is the only test that pins the founder's `reports_this_bug: False`. Before this change, a flip to True would have passed the suite.
- **Hotfix faithfulness:**
  - `git range-diff 15dfac53~1..3960b8ea 3dfdde3c..491b3dca`: the five picked commits (15dfac53, 8a366396, fe241635, 55bca9b2, 3960b8ea) have identical patches. Only the "cherry picked from" lines differ. The three Neuralwatt commits are correctly left out.
  - `git diff -U0 3dfdde3c 491b3dca` equals `git diff -U0 77f25170 3960b8ea` over the same 10 files once index and `@@` lines are stripped. Both have 10 files and 1363 lines.
  - `diff(77f25170→3dfdde3c)` equals `diff(3960b8ea→491b3dca)` on `run.py`, `ordinary_freshness.py` and the G2 test. So the picks landed on the batch source without altering anything around them.
  - The `G2_SOURCE_RULINGS` block is byte-equal in 3960b8ea and 491b3dca.
- **Identity.** I ran `myident.py` on my archives of 3dfdde3c, 491b3dca and 3960b8ea. From 3dfdde3c to 491b3dca, the only differences are:
  - `runner/G2/G2_SOURCE_RULINGS` added;
  - `runner/G2/g2_source_ruling` added;
  - `runner/G2/checked_freshness_verdict` changed.

  Model science, the delivery contract, judge, prompts, release pins, every other gate's runner inputs and all dependency files are unchanged. G2's three names hash the same in 491b3dca and 3960b8ea.

## Findings

**No blocking findings.**

1. **nit:** `tests/factory/test_g2_blocked_source.py:80-87, 248`. Design step 4.2 says the entry goes in "in one commit (no other change)", but this commit also edits two tests.
   - The edit is needed: without it nothing tests the founder's `reports_this_bug: False` (shown by the "set to True" mutant above).
   - The commit message already says so.
   - **Fix:** note this deviation from step 4.2 in the saved review record (`docs/reviews/g2-18681d-hand-check-diff-1.md`) so the design's "no other change" is not read as broken. No code change.

## Spec conformance (checked, no finding)

- **Required fields** (`factory/run.py:2056-2066`):
  - `case`, `statement_sha256` and `url` are exact.
  - `by` is "founder"; `at` and `checked_at` are "2026-11-20".
  - `checked_by` matches the spec string exactly.
  - `reports_this_bug` is `False`.
  - The key sets match design section 1 exactly.
- **`ruling`.** It carries the founder's words ("Yes, record it") and says who opened the page.
- **`page_says`** (section 3 rule):
  - It gives site, topic, product/version, date, title and the question, says there are no replies, cause or fix, and states that the page does not report this case's bug.
  - It correctly leaves out the spec's "no mention of deleted variants", which would point at the case's bug.
  - The page's own topic (a draft order marked paid does not reduce inventory) is the founder-confirmed reading of the page, not a restatement of the case bug.
- **No over-building.** The change is one tuple entry and two test assertions: no new code paths, helpers or config.

Verdict: PASS

## Elephant's record

- **Nit 1, taken as recorded here.** Step 4.2's "one commit (no other change)" means no other factory change. The same commit also points two 18681d tests at the shipped entry, so the founder's `reports_this_bug: False` is pinned by a test. No code change.
- **Left out on purpose.** `page_says` drops the spec's "no mention of deleted variants". Section 3 says `page_says` must not restate the case's bug, and that phrase points at it. The entry says instead that the page does not report this case's bug.
