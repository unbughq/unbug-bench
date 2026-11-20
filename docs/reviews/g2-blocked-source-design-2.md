# Design review 2: g2-blocked-source (goldfish)

Reviewer: fresh Claude subagent (general-purpose, no history), read-only. Personas: zoom_out, design_critic, implementation_readiness. Standards: Heilmeier and implementation-readiness, plus ENGINEERING §2 and §4. I reviewed revision 2 of `docs/designs/g2-blocked-source.md` against branch `fix/g2-blocked-source` (base 77f25170). The only thing I ran was the branch's own new test file (`python3 -B -m unittest tests/factory/test_g2_blocked_source.py`): 7 tests, all OK.

## Checked and found correct

- **Review 1 finding 1 (BLOCKING) is resolved.** `g2_source_ruling` returns None whenever `isinstance(answer, dict) and answer.get('same_bug') is True`, whether or not the answer is valid (`factory/run.py:2065`). It is also covered by the scope test "reviewer claims the match" (`tests/factory/test_g2_blocked_source.py:100`).
- **Only G2's identity changes.**
  - The constant is reached through `g2 → _g2 → confirm_hits → checked_freshness_verdict → g2_source_ruling → G2_SOURCE_RULINGS`, and `source_inputs` hashes constants by name (`gate_state.py:93-122`).
  - G2 is not a REUSABLE gate, so it has no pass cache to lose. Engine checkpoint entries carry `gate_state.inputs` per entry (`durable/checkpoints.py:107-120`), so a later ruling change cannot leave a stale G2 pass in place.
  - The stress `scientific_version` does not hash runner source (`gate_state.py:274-280`).
  - G1 and G3 always rerun. The G4/G5 caches keep their identities.
- **Why the sealed FOUNDER_RULING can't be used: the argument holds against the code.**
  - `contract.py:260` sends a ruling only to stress or gates.
  - `resume_held` sends only a hold id (`durable/engine.py` `resume_held`).
  - `review` appends `engine_review_ruling(c)` with no gate argument (`run.py:2474`, `3322`), so G8/G9 would read the ruling.
- **"The release is the resume" is correct.** `wait_for_fix` breaks out as soon as `(plumbing, bench)` differs from the failed pair.
- **The schema and the effect leave no open decision** (note lines 49-100). Review 1 findings 3-11 are handled as their resolutions say.

## Findings

1. **BLOCKING: the 18681d leg of review 1's blocking finding 2 is still open. The pre-release check that guards it is not durable, and step 4 cannot be run as written.**
   - **Where the check lives.** The note says the check is "outside the repo because it needs the VM" (lines 200-203). It exists only at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/35da1f8b-8fdf-431c-a84e-d725cb8c71d1/scratchpad/g2rule/vmcheck.py`, a session scratchpad that a reboot or cleanup can wipe.
   - **Why that matters.** cae763 and 2a7b2a were already checked. 18681d's step 4.3 runs later, maybe in another session, after the founder's hand check. Under the note's own rule, any release to that batch is a resume, so a mis-keyed digest or URL there burns a lineage resume and loops on the 429 again.
   - **The stated reason does not hold.** Read-only local diagnosis tools already live in the repo (`tools/open-g2-verdicts.py`, which drives `run.checked_freshness_verdict`). Nothing stops this check from living there too.
   - **Step 4.1 points at something undefined.** "The founder fills in the hand-check template" (line 227): no template exists in the note or the repo.
   - **Step 4.2 is not data-only.** It calls itself "a data-only commit", but adding the entry breaks `tests/factory/test_g2_blocked_source.py:82`, which asserts 18681d has no shipped ruling. And no repo test would check the new entry against 18681d's fixture digest and URL.
   - **Fix:**
     - Commit the check as a read-only tool that prints OK, NO RULING or MISMATCH per case, and name its path in operator steps 1 and 4.3.
     - Define the template as the `hand_checked` schema row with a filled example.
     - Say the 18681d commit changes line 82 into an assertion that the shipped entry is valid and matches `HELD[D18681]`'s `statement_sha256` and URL.

2. **NON-BLOCKING: the remaining resume count is still not stated. The note conflates two different counters.**
   - The note says each release "uses one of the lineage's 3 factory-bug resumes. Each card shows `diagnoses: 1`" (lines 170-171).
   - The card's `diagnoses` is `diagnoses_used` for this workflow (`durable/engine.py:1312`).
   - The cap counts the lineage's `factory_bug_resumes`, which is carried across resume records (`engine.py:772`, `1302-1303`, `1988`, `468`). For `-h5` and `-h1` imports these can differ.
   - Review 1 asked for each lineage's remaining count. Fix: read `factory_bug_resumes` from each case's resume record or counters, and state it per case. If any lineage is at 2, this release is its last.

3. **NON-BLOCKING: the minima can change what happens after the ruling, and the note does not cover it.**
   - The ruled row stays in `freshness_unfetched`, so it never counts toward G2's minima (`run.py:1913`).
   - Today the transport hold is handled first (`ordinary_freshness.py:225`), before minima and repair (`:246-262`), so the hold can hide a minima shortage.
   - Once the ruling clears the row, a hidden shortage shows up as `evidence_incomplete` and triggers a top-up. That costs builder or attacker calls and adds rows to `freshness.jsonl`, which is part of G8/G9 identity (`gate_state.py:212`).
   - The end-to-end test already had to add a builder/web row for exactly this reason (`test_g2_blocked_source.py:147-151`; "cae763 counted 19").
   - Fix: state the counts without the ruled row for 2a7b2a and 18681d (cae763 has 19), and have the pre-release check print them.

4. **NON-BLOCKING: for a reviewed code constant, failing closed silently is the expensive failure mode.**
   - A malformed shipped entry applies nothing at runtime (note lines 97-98, `run.py:2069-2079`). The first sign would be a held case on the VM, at the cost of a resume.
   - Fix: add one test that runs every entry of `G2_SOURCE_RULINGS` through `g2_source_ruling` against its own digest and URL and asserts it comes back. That turns a bad 18681d entry into a failing test before the release. Runtime validation can stay.

5. **NON-BLOCKING: the note handles bug-naming text inconsistently.**
   - The fixture deliberately leaves out 18681d's two free-text fields "which name the case's bug" (fixture `_source` and `answer_redacted`).
   - Yet the design commits 18681d's `page_says` and `ruling` text verbatim into `factory/run.py` and onto the card. A hand check of whether a page reports the bug will naturally name the bug.
   - Fix: pick one rule. Either the template says `page_says` must not name the bug, or the note says why the repo may hold it, in which case the fixture redaction is unnecessary.

6. **NIT: wording that should be more precise.**
   - The Identity section says the new names are "reachable only from G2's runner root" (line 143). `loop_freshness` reaches them too, through `confirm_hits` (`run.py:1293`). This is harmless for identity, but the sentence should say "hashed only into G2's runner inputs".
   - The hard constraint is "lets G2 clear". Applying the ruling in the stress round (lines 76-77) goes slightly beyond G2. The note should say in one line that the founder's per-URL ruling covers that too.

7. **NIT: step 4.2 does not say who merges the 18681d entry.** Line 138 makes the founder's merge the seal, and ENGINEERING §4 forbids touching `main` without the founder. Step 4.2 should say "merged by the founder".

8. **NIT: the file path.** Line 4 cites "ENGINEERING.md section 4". The file is `docs/ENGINEERING.md`. The reasoning in lines 7-8 is still right: `*.md` in DEPENDENCIES globs only the top level.

FAIL

## Resolution (elephant)

All findings accepted; none rejected.

1. Fixed. The check is committed as `tools/check-g2-rulings.py` (read-only; candidate tree's own `run.g2_source_ruling`; prints OK / MISMATCH / NO RULING and G2's last counts). Its logic is tested on the fixture; its snapshot reading was run live, read-only, on the VM against the three held snapshots (cae763 OK, 2a7b2a OK, 18681d NO RULING; nothing written, disk unchanged). Operator steps 1 and 4.3 name it. The hand-check template is defined (step 4.1, schema table, and the filled template handed to the founder). The "18681d has no shipped ruling" assertion is gone; `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case` checks any added entry against the held fixture's digest and URL.
2. Fixed. All three workflows are imports (first result `admit:imported_hand`), so the lineage count is 0 and this release is each one's first resume of 3.
3. Fixed. Counts stated (cae763 19/25/8 met; 2a7b2a 3/4/6 met only when its archive copy is found; 18681d 2/4/4, one builder/web short) and printed by the check; the note says the top-up then runs and touches only G8/G9 inputs, which none of the three has passed.
4. Fixed: `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case`.
5. Fixed: one rule, `page_says` describes the page and its verdict without restating the bug; the fixture redaction follows the same rule.
6. Fixed (wording; stress round covered by the per-URL ruling).
7. Fixed ("merged by the founder").
8. Fixed.
