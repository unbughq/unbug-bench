# Diff review 2: sealed-audit-exam-packaging

**Reviewer.** A fresh goldfish with no conversation history, run as a `claude -p` subprocess from the same model family as the elephant.

**Setup.**
- Tools: read-only, plus permission to run the focused test and the tool's own read-only commands.
- Personas: zoom_out and implementation_readiness.
- Mode: REVIEW.
- Standard: `implementation-readiness-standard.md`.

**Scope.** `git diff origin/factory-simplify...HEAD` at `01b5650`, checked against the final design, design reviews 1–4 and diff review 1.

**Result.** PASS. No blocking findings.

## Verbatim review

## Diff review 2: sealed-audit-exam-packaging (goldfish, zoom_out + implementation_readiness, Mode: REVIEW)

**Summary.** I reviewed `git diff origin/factory-simplify...HEAD` (merge base `fbca505`, head `01b5650`, 11 new files, all under `docs/`, `tools/sealed_inventory.py` and `tests/tools/test_sealed_inventory.py`) against the final design and design reviews 1–4. All eight findings from diff review 1 are fixed:

- **Finding 1 (the blocker).** Test 8 now builds its name list from `git ls-files -z` (`tests/tools/test_sealed_inventory.py:211-215`). `docs/exam-packaging.md:83-85` and design test 8 say the list is for a clean committed tree and that untracked names also make `bin/freeze` refuse.
- **Findings 2 and 3.** The report now says fcde6b has no `calibrators` field, and that 18681d's strong 0/3 includes 2 `run_error` and 1 `fix_failed_all_runs` (`docs/reports/sealed-audit-20261104.md:85-92`). Both match the card at `sealed/case-20261017T125556Z-18681d.scorecard.json:355-395`.
- **Findings 4 and 5.** Excluded rows carry `hashes.vm_20261029` and every row carries `card_sha256` (`tools/sealed_inventory.py:154-168`). Both are asserted at `tests/tools/test_sealed_inventory.py:70-75`.
- **Finding 6.** The spec is named `<round-id>.json` (`docs/exam-packaging.md:20,44,71`), and `bin/exam-round:120` keys its state on the file stem.
- **Finding 7.** Design §1 now says a card whose `case` differs from its filename aborts the tool, and the code does that (`tools/sealed_inventory.py:152-153`).
- **Finding 8.** Test 2 asserts `fail:metadata` (`tests/tools/test_sealed_inventory.py:89`).

The code matches the final design text: the gate-cell rule, the three `unavailable:` tokens (each last in its criterion), `registry_cell`, the check that a card's hash matches only its own final `<case>.tar.gz.age` (the 2026-10-30 inventory has 89 `.checkpoint` and 56 final names), `ValueError` → `fail:metadata` with any other exception aborting with the case ID, `--round` judging the flags it is given, its first-non-unavailable tie-break and its five messages.

Both permitted commands ran: the focused test passed 10/10, and `--markdown` ran. I checked these claims against the real files and they hold:

- 47/3 split of metadata errors;
- seven cards missing from the 2026-10-30 inventory (6d8046, aeefd5, 01eae8, 832462, 7d8a30, 5a6ef3, a61f54);
- 43 Mac / 46 VM inventory entries and 54 VM cards;
- a869de's `source: "fixture (dry-run)"`;
- registry statuses (37 `completed`/`complete:false`, 1 `released`, 3 `screening`/`complete:true`);
- 18681d's single final-archive hash `90fa095f…` on both hosts, with different checkpoints;
- `bin/freeze` `--root`/`--evidence`/`--archive`, `bin/exam-round` stdin identity and archive resolution;
- `bin/exam-launch:20` calls `verify_exam_metadata` and `bin/run-exam:324` calls `verify_exam`;
- `factory/launch.sh:4` gives the 8 h TTL;
- `pilot-bounded-roles.md:16,21` binds `b-real-pilot` to exactly three templates.

Hard constraints hold:
- public evidence only, with no decryption or key read (test 5 guards it);
- the three unavailable items are recorded as unavailable;
- dry-run and smoke cards are excluded;
- no budget, ledger, route or enablement file is touched;
- 48 creations, with money, deadline and timeouts null and listed as founder-required;
- quality rules are not lowered;
- none of the 11 files appears in `git diff --stat` for `prep/practice4-checkpoint-carry-20261104` (27 files) or `fix/registry-stale-history` (6 files). That branch's `factory/registry.py` change starts at line 101, so the cited lines `:60-66` stay valid.

No blocking problem remains; only the three nits below.

1. **NIT: Murphy row 41 is already closed, but the design calls it "touched, not closed".**
   - **Evidence:** `docs/murphy-register.md:53` has row 41 `closed` by `tests/factory/test_invalid_runs.py::test_row_41_…`. `docs/designs/sealed-audit-exam-packaging.md:360-363` lists it under "Rows touched, not closed", and `docs/reports/sealed-audit-20261104.md:124` cites it without saying so. A reader would think it is still open.
   - **Fix:** Reword both places, for example: "41 (already closed): the legacy G1–G15 cards predate that fix and carry no G16/G17 result."

2. **NIT: a `dedup` record without a `duplicate_of` key passes "Distinct bug".**
   - **Evidence:** `tools/sealed_inventory.py:110-112` passes any dict where `value.get('duplicate_of') is None`, so `{}` passes. Every real record has `checked_against` and `duplicate_of` (e.g. `sealed/case-20261018T144339Z-e5caf7.scorecard.json:98-102`). The code matches the design text literally, and the registry part still blocks eligibility, so nothing is miscounted today.
   - **Fix:** Pass only when `'duplicate_of' in value` and `isinstance(value.get('checked_against'), int)`, and add that to the design's Distinct-bug row.

3. **NIT: `--round` does not tie an archive to the card directory it judges.**
   - **Evidence:** `check_round` takes the archive basename and looks it up in `--cards` (`tools/sealed_inventory.py:215`). `bin/exam-round:42-44` instead resolves the archive relative to the spec and uses the scorecard next to it. A spec pointing at `../elsewhere/<case>.tar.gz.age` would be judged on `sealed/<case>.scorecard.json` but launched with a different card. `bin/exam-launch` re-runs the metadata check, so this is defence in depth only.
   - **Fix:** In `check_round`, resolve `(spec.parent / archive)` and report `wrong directory <id>` unless its parent equals `--cards` resolved. Add the message to the design's `--round` table and one round to test 8.

Verdict: PASS

## Disposition (elephant)

The review reports no blocking findings. Of its three nits, two are fixed and one is declined.

1. **Nit, fixed.** Design and report now state that row 41 is already closed (`tests/factory/test_invalid_runs.py`). The legacy G1–G15 cards predate that fix.
2. **Nit, fixed.** "Distinct bug" now passes `dedup` only when the record has a `duplicate_of` key and an integer `checked_against`. An empty or partial record gives `missing:dedup`. The design row is updated to match. The counts and the generated table are unchanged, and the focused tests still pass.
3. **Nit, declined (optional).** The review rates this as defence in depth: `bin/exam-launch` re-runs `verify_exam_metadata` on the card next to each archive at launch. It is left as a follow-up, because the packaging procedure already requires archives under `sealed/` next to their cards.

The two fixes were made after this review and change only wording plus a stricter dedup predicate. The full offline suite was run on the head that contains them.
