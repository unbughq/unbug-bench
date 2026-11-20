# Design review 3: g2-blocked-source (goldfish)

Reviewer: a fresh, read-only goldfish with no earlier context. Personas: zoom_out, design_critic, implementation_readiness. Standards: Heilmeier, implementation-readiness, and `docs/ENGINEERING.md` sections 2 and 4. I reviewed revision 3 of `docs/designs/g2-blocked-source.md` on branch `fix/g2-blocked-source`, base 77f25170. The only thing I ran was `python3 -B -m unittest tests/factory/test_g2_blocked_source.py`: 9 tests, all OK.

## Checked and found correct

- **Review 1, finding 1 (BLOCKING) is resolved.** At `factory/run.py:2065`, `g2_source_ruling` returns None whenever the answer is a dict with `same_bug is True`, whether or not the answer is valid. The scope test "reviewer claims the match" covers it (`tests/factory/test_g2_blocked_source.py:124`). The pre-release check covers it too (`:110`).
- **Review 1, finding 2 (BLOCKING) is resolved.**
  - The note now says the release is the resume, and that it costs each lineage its first of 3 resumes.
  - `wait_for_fix` ends a hold when `(plumbing, bench)` changes (`factory/durable/engine.py:1929-1931`).
  - `lineage_factory_bug_resumes` is set only from a resume record (`engine.py:1988`), so an import lineage starts at 0.
  - The note says never to release to 18681d before its ruling (design lines 262-263).
- **Review 2, finding 1 (BLOCKING) is resolved.**
  - The check is now committed as `tools/check-g2-rulings.py`. It is read-only (`PGOPTIONS` sets read-only before connecting, `:50`). It runs the candidate's own `g2_source_ruling`, and prints OK, MISMATCH or NO RULING. It exits 1 only on MISMATCH.
  - Operator steps 1 and 4.3 name the tool.
  - The template is defined: the schema table plus step 4.1, which gives 18681d's digest and URL.
  - The old "18681d has no ruling" assertion is gone. `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case` (`:88-96`) checks any added entry against the held fixture.
- **The hard constraints hold.**
  - The diff touches only `factory/run.py` and `factory/ordinary_freshness.py` in factory code. `calibration.py`, `gate_state.py`, `bin/claims.py` and the delivery contract are untouched.
  - `run.py` is hashed per name (`runner_inputs`), not as a whole file. `test_only_g2_identity_reads_the_rulings` passes for every `STAGE_DEPENDENCIES` gate and for the calibrate and stress roots.
  - `ordinary_freshness.py` is not in any gate's dependencies (`gate_state.py:56-76`).
  - `freshness.jsonl` is excluded from every gate's identity except G8 and G9 (`gate_state.py:212`).
- **The ruling settles one URL and nothing more.**
  - It needs the runner's receipt to show an access failure, so a page read live or a dead page (404) is not ruled.
  - A ruled row skips `freshness_transport_pending` (`run.py:2268-2274`).
  - A row the ruling clears is not in `confirmed`, so `_g2` passes once the minima are met (`run.py:1995`).
  - With no ruling, the summary and card bytes are unchanged; the `pop` at `:2315` does nothing then.
  - Retained answers are re-judged on every read, so they cannot skip a ruling. A ruling withdrawn later fails closed: the row is blocked again and the reviewer is re-asked.
- **The argument against FOUNDER_RULING still holds**, as reviews 1 and 2 found.

## Findings

1. **NON-BLOCKING: a ruled row still counts as a bot wall in `ordinary_freshness.stalled`.**
   - `stalled` builds `held` from every receipt with an access failure (`factory/ordinary_freshness.py:43-45`), and that includes the ruled row.
   - Example: cae763 has 361 flagged rows, and row 277 (http_202, no archive copy) is ruled. Suppose any other flagged row gets a 429 or 5xx and is left unresolved, so `transport_pending` is set.
     - Today that is a 30-minute retryable `freshness_refresh_stalled`.
     - With the ruled row counted, `walled` is true. G2 stops after 3 cycles as `freshness_source_blocked`, which means a hold and a resume.
     - The card note then tells the operator to "rule the claim does not need it" about a page that is already ruled.
   - The risk is low, because other rows reuse their saved live receipts (`obtain`, `:76-78`). It is still a wrong stop, and a wrong stop costs a resume.
   - Fix: in `stalled`, drop the receipts whose URL appears in `info.get('ruled_rows')`. This is plumbing and changes no identity. Add one test. Or state the gap in the note.

2. **NON-BLOCKING: for 18681d, "G2 runs its usual top-up search" (design lines 183-186) is not guaranteed.**
   - Two counts disagree:
     - `ensure.metadata()` counts every row, the unfetched ruled row included (`ordinary_freshness.py:173-176`), so it reports enough searches and no defect.
     - `_g2` leaves the unfetched row out (`run.py:1913`), so it reports one builder/web search short.
   - The guard at `ordinary_freshness.py:251` then skips the top-up and loops on backoff whenever `unfetched_searches` is non-zero (the ruled row always is unfetched) and `last_topup` equals the digest of the current rows.
   - Each pass of that loop refetches the 429 URL until the attempt deadline. That can happen in two ways:
     - an earlier attempt left `last_topup` in `freshness-repair.json`;
     - one top-up adds no fetched builder/web row.
   - For 2a7b2a this loop is harmless and even helps: a refetch can find the archive copy. For 18681d it never resolves, so it can cost a resume.
   - Fix, before 18681d is released (step 4 already gets its own goldfish review): have `check-g2-rulings.py` print whether `freshness-repair.json` `last_topup` equals the digest of the snapshot's rows, and say in the note which path 18681d will take.

3. **NON-BLOCKING: the pre-release check's "reviewer did not confirm" leg can pass vacuously.**
   - `main` takes the last `answer-N.json` in tar order whose length equals `flagged` (`tools/check-g2-rulings.py:86-89`).
   - `flagged` counts superseded rows too, unlike `_g2`.
   - If no file matches, `answers` is `{}`. The answer passed in is then None, and the case prints OK.
   - The impact is small, because the release re-asks the reviewer anyway.
   - Fix: print which answer file was used, or "no answer".

4. **NON-BLOCKING: the cost section is incomplete (Heilmeier Cost).**
   - It prices only cae763's re-asked review (about $0.5).
   - The rerun also pays for G1, G3, the re-asks for 2a7b2a and 18681d, and possibly 18681d's top-up. It runs against the case's remaining money (`wait_for_fix` takes a `case_limit`, `engine.py:1934`).
   - A shortfall would mean a money stop and another hold.
   - Fix: state each case's remaining case money against the expected spend.

5. **NIT: one URL can clear more than one row.**
   - The constraint says "that one row and only that one". The note says a ruling settles every flagged row with the same URL (lines 100-101) and adds "in practice each held case has one". Nothing checks that claim, and cae763 has 361 flagged rows.
   - The check uses `next(...)` (`:39`), so it cannot see duplicates.
   - Fix: have the check print how many flagged rows share each ruled URL.

6. **NIT: `case` is never checked.**
   - `case` is validated only as non-empty text (`run.py:2073`).
   - The shipped-ruling test matches entries by digest and URL, and never asserts `ruling['case'] == held['case']` (`test_g2_blocked_source.py:91-93`). A mislabelled entry would apply, and the card would show the wrong case id.
   - Fix: add that one assertion.
   - Also, `at` and `checked_at` are checked by regex only, so 2026-13-45 passes.

7. **NIT: the note contradicts itself on cached gates.**
   - The table says cae763 has "G1, G3 pass" on its card (line 30).
   - The cost section says the release keeps "cae763 G4/G5" caches (line 172).
   - Say that these are `gate_state` caches from earlier attempts, or fix one of the two.

8. **NIT: the Murphy closure leans on a run outside the repo.**
   - The repo tests use an authored statement, so the real digest match is proven only by the recorded live run of the VM check (line 224).
   - Fix: say in the Murphy row that its closure relies on that recorded run as well as the test file.

**Verdict: PASS** (no blocking findings)

## Resolution (elephant)

All findings accepted; none rejected.

1. Fixed: `ordinary_freshness.stalled` leaves ruled URLs out of `held` (`ruled(c)`, from the verdict's
   `ruled_rows`). Test `test_a_ruled_wall_never_stops_g2_while_another_row_is_held`.
2. Fixed in code rather than only in the check: `ensure.metadata()` leaves ruled (unread) rows out of the
   search evidence, as `_g2` does, so 18681d's short builder/web minimum is a charged top-up, not the
   `last_topup` refetch loop (the VM read confirmed `last_topup` equals the rows' digest for all three).
   Test `test_18681d_a_ruled_unread_row_short_of_searches_buys_one_top_up_not_a_refetch_loop`, on 18681d's
   real row shape; with the fix removed it loops until cancelled. The note states 18681d's path.
3. Fixed: the check prints the reviewer answer file it used (or None).
4. Fixed in the note: the rerun is paid from each case's remaining money; the operator reads it before
   releasing (not read here).
5. Fixed: the check prints how many flagged rows share each ruled URL.
6. Fixed: the shipped-ruling test asserts `ruling['case'] == held['case']`. Date validity stays a format
   check (a wrong date is visible on the card and harms nothing).
7. Fixed in the note: G4/G5 are `gate_state` caches from earlier attempts; the table is this attempt.
8. Fixed in the note: the Murphy closure names the recorded live run as well as the test file.

