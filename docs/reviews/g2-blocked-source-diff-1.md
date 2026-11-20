# Diff review 1: g2-blocked-source (goldfish)

**Reviewer:** a fresh, read-only goldfish. Personas: zoom_out and implementation_readiness. Standards: implementation-readiness, plus `docs/ENGINEERING.md` sections 1, 2 and 4.

**Scope:** branch `fix/g2-blocked-source` at fe241635, against base 77f25170, reviewed against `docs/designs/g2-blocked-source.md` revision 3.

**What I ran:** the new suite and five existing suites. I compared runner identity between base and head with my own script. I also tried three runtime mutations (monkeypatched, no file edits). All scratch files are under `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/g2rule/review/`.

## Checked and found correct

- **Only G2's identity moves.** I checked this myself, not through the branch's test.
  - I ran `gate_state.source_inputs` on base `run.py` and head `run.py` for every gate root plus `EXTRA_ROOTS`.
  - G1, G3–G11 and G13–G17 are identical. So are the calibrate root (`calibrate`/`make_pilots`/`calibration_identity`) and the stress roots. G12 has no runner.
  - Only G2 changes, and only by `G2_SOURCE_RULINGS`, `g2_source_ruling` and `checked_freshness_verdict`. `loop_freshness` reaches the same three names, but the stress `scientific_version` hashes no runner source (`factory/gate_state.py:273-280`).
  - None of the changed files matches any `STAGE_DEPENDENCIES` or judge pattern. That covers `ordinary_freshness.py`, `tools/`, `tests/` and `docs/designs|reviews`: `*.md` matches top-level files only.
  - `calibration.py`, `gate_state.py`, `bin/claims.py` and the delivery contract are untouched.
- **`g2_source_ruling`'s scope is correct** (`factory/run.py:2059-2080`).
  - It needs all of these: a `case/statement.md` digest match, an exact URL match, the runner receipt showing `access_failure`, no reviewer `same_bug is True` (valid or not, `:2065`), and exactly one valid entry.
  - `freshness_retrieval.load` already checks receipt and row URL alignment (`freshness_retrieval.py:114`), so a ruling cannot be applied using another row's receipt.
  - A 404/410/DNS page and a page read live are excluded.
  - A `hand_checked` / `reports_this_bug: true` ruling raises `freshness_confirmed_hits`. `_g2` then reports `public_match` (`run.py:2003-2006`), and `confirm_hits` keeps the receipt (blocked == confirmed).
  - A withdrawn ruling fails closed: on the next read the retained verdict blocks again and is re-asked.
- **With no ruling, the output is byte-identical.**
  - `ruled_rows` is added only through `setdefault` when a ruling applies.
  - The card `pop` does nothing when the key is absent.
  - `ruled(c)` returns `set()`, so `stalled` and `metadata()` are unchanged.
  - The `case` attribute in the `keep_mixed_receipt` namespace has no effect without a match.
  - The new suite passes (11/11). So do `test_stream_d_retries` (68), `test_freshness_archive` (7), `test_freshness_restore_fixes` (13), `test_invalid_runs` (32) and `test_admission` (30, run as a script with `BENCH`).
- **The card record.** `ruled_rows` (row number plus the whole entry) appears in `card.freshness_confirmation`, in G2 info (`**c.freshness_review_summary`, `run.py:2003`), and in `freshness-verdict.json`. Neither `admission_freshness` nor `freshness_confirmation` is read anywhere outside `run.py`, `ordinary_freshness.py` and the two tools.
- **The `ordinary_freshness` changes.**
  - `stalled` leaves ruled URLs out of `held` (`:50`). A ruled row never sets `transport_pending`, so `stalled` runs only when another row is held.
  - `metadata()` now leaves out only rows that are both ruled and unfetched (`:180`), which matches `freshness_counts` (`run.py:1913`) for those rows. Other unfetched rows keep their existing projection.
  - The new top-up path is bounded by `completed_defects` (`:189-196`, `:255-256`).
  - I found no new loop. A top-up row that is itself unreadable falls into the existing `last_topup` refetch loop, as it does today for any unfetched row.
- **Mutations are caught.** Dropping the `same_bug` guard fails 2 tests. Dropping the `access_failure` guard fails 1. Emptying `ruled()` (both `ordinary_freshness` fixes off) fails the 18681d end-to-end test and the stall test. The 18681d test ends on the harness cancel after 8 cycles; it does not hang.
- **`tools/check-g2-rulings.py` is read-only.**
  - It sets `PGOPTIONS` read-only before psycopg or SQLAlchemy connect, so any write would raise rather than land.
  - `wrapped_key` and `get_sealed` only read, and the snapshot is opened in memory.
  - `OK` means the candidate's own `g2_source_ruling` returned that exact entry (`got is ruling`), so the verdict is meaningful.
- **The shipped entries.** They match the fixture's VM-read digests and URLs, and `case` matches. `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case` guards any future entry. The 18681d template in step 4.1 matches the validator's keys.
- **The Murphy row** `new-g2-blocked-source-1` is present and honest ("open until merge + release + G2 pass"). Its test uses the real rows, receipts and retained answers of all three cases. The real digest match is backed by the recorded live run, as the row says.

## Findings

1. **NON-BLOCKING: the pre-release check does not show the two snapshot facts that decide whether the release can succeed.**
   - **Defect count.** `freshness-repair.json` is retained in the snapshot (`run.py:3252`), and `completed_defects` survives a resume while the statement is unchanged (`ordinary_freshness.py:163-164`).
     - The design's 18681d path ("one builder top-up; two that add nothing end `freshness_evidence_unavailable`") holds only if that count is 0.
     - At 1, a single top-up that adds no builder/web search ends the attempt.
     - At 2, the first short cycle stops at `:255-256` with no top-up at all.
     - `freshness_evidence_unavailable` is in diagnosis `_CASE_CAUSED` (`factory/durable/steps/diagnosis.py:61`), so the agent may retire the case rather than just hold it.
     - The design records `last_topup` for all three cases, but not `completed_defects`.
   - **Money.** The case-money remainder is "read before releasing", but no threshold is given. That leaves the decision to the operator.
   - **Fix:**
     - Have `check-g2-rulings.py` print `completed_defects`, whether `last_topup` equals the digest of the rows, and the case money left.
     - In operator steps 1 and 4.3, add a stop rule. Suggested: stop if `completed_defects ≥ 1` for a case that needs a top-up (18681d, and 2a7b2a on a cycle with no archive copy), or if money left is below the expected spend for G1, G3 and the re-asked review.

2. **NON-BLOCKING: the cost section does not mention a behaviour change for 2a7b2a.**
   - Before the `metadata()` fix, a cycle where the Shopline archive copy is missing went into the free refetch loop. Design review 3 judged that loop helpful.
   - It now goes into a builder top-up. That costs model money, and it is charged as a defect if it adds nothing.
   - The first cycle likely reuses the saved archive receipt (`ordinary_freshness.py:82-84`). But a reviewer re-ask refetches every flagged URL (`:250-251`), and that can lose the archive copy.
   - **Fix:** say this in "Cost and risk of the resume". Finding 1's printout also covers it.

3. **NIT: operator step 1 says "Stop on any MISMATCH", but a wrong digest prints NO RULING and exits 0.**
   - `check()` filters entries by digest before matching (`tools/check-g2-rulings.py:38`).
   - **Fix:** reword to "stop unless the output is exactly: cae763 OK, 2a7b2a OK, 18681d NO RULING, each with `flagged rows with this url: 1`". The URL-count clause covers the one-row constraint that design review 3, nit 5 only printed.

4. **NIT: two changed lines are not covered by any test.**
   - `confirmation.pop('ruled_rows', None)` (`run.py:2315`): no test reuses one card across two verdicts.
   - `case=c.case` in `keep_mixed_receipt` (`ordinary_freshness.py:136`): no test drives `keep_mixed_receipt` with a ruling.
   - **Fix:** add two asserts:
     - a ruled verdict, then an unruled verdict on the same card, leaves no `ruled_rows`;
     - `keep_mixed_receipt` with a `hand_checked` / `true` ruling lists that row in `confirmed_rows`.

5. **NIT: the cae763 end-to-end test still answers with the harness's live clearance, not the case's real answer.**
   - That answer contradicts the 202 receipt. The test passes because the ruling ignores everything in the answer except `same_bug`.
   - **Fix:** emit the fixture's `HELD[CAE763]['answer']` so the test runs on the real answer shape.

6. **NIT: the design's wording on the 18681d top-up disagrees with itself.**
   - Lines 130 and 196 say the top-up is "charged". Line 233 says "no defect charged".
   - Both are right: the top-up is charged only if the case is still short after it (`ordinary_freshness.py:189-190`).
   - **Fix:** say that once.

7. **NIT: the validator is looser than the design's "exactly these keys".**
   - It accepts `"hand_check": None` on a `not_needed` entry.
   - It accepts extra keys inside `hand_check` (`run.py:2074-2079`).
   - **Fix:** check `set(check) == {checked_at, checked_by, page_says, reports_this_bug}`, and require `hand_check` to be absent for `not_needed`.

**Verdict: PASS**

## Resolution (elephant)

All findings accepted; none rejected. Reviewer note: a fresh Claude goldfish (same family as the writer). A
different family (Codex) was not used because the diff carries real case rows, receipts and answers, and the
operating brief forbids sending case content to another web service.

1. Fixed: the check prints each case's `G2 repair` line (`completed_defects`, and whether `last_topup` is the
   digest of the snapshot's rows). Live run, 20 Nov: cae763 0 / True, 2a7b2a 1 / True, 18681d 0 / True. Operator
   step 1 now names the exact expected output and the stop rule, and says to read the case money on the card.
   No money threshold is set here (that is the operator's or founder's call).
2. Fixed in the note: 2a7b2a's no-archive cycles now buy a builder top-up, and with `completed_defects` 1 one
   that adds nothing ends `freshness_evidence_unavailable`.
3. Fixed: step 1 says "exactly", with `flagged rows with this url: 1`, and that a wrong digest prints NO RULING.
4. Fixed: `test_the_card_shows_only_the_latest_verdicts_rulings` and
   `test_the_mixed_receipt_lists_a_hand_checked_match_as_confirmed`.
5. Fixed: the cae763 end-to-end test answers with the case's real retained answer.
6. Fixed: the note says once that a top-up is charged only if the case is still short after it.
7. Fixed: `not_needed` must have no `hand_check` key; `hand_check` must have exactly its four keys (two new
   scope negatives).

