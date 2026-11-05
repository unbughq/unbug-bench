# Diff review 1: sealed-audit-exam-packaging

**Reviewer.** A fresh goldfish, run as a `claude -p` subprocess with no conversation history. It is the same model family as the elephant, because no other family could be reached from this cloud session.

**Tools.** Read-only: Read, Grep, Glob, git show/log/diff, ls, wc. It was also allowed to run the focused test and the tool's own read-only commands.

**Method.** Personas zoom_out and implementation_readiness, Mode REVIEW, against `implementation-readiness-standard.md`. It reviewed `git diff origin/factory-simplify...HEAD` at `ae356d5`, checking it against the final design and design reviews 1–4.

## Verbatim review

**Summary.** The branch adds only docs, one read-only tool and one test file. It changes no budget, ledger, route, enablement or batch file, and none of its files appear in the `git diff --stat` of `prep/practice4-checkpoint-carry-20261104` or `fix/registry-stale-history`. `tools/sealed_inventory.py` matches the final design text: the gate-cell rule, `registry_cell`, the three `unavailable:` tokens (each last in its criterion), the dedup and wipe rules, the check that a card's hash matches its own final `<case>.tar.gz.age` only, `ValueError` → `fail:metadata` while any other exception aborts with the case ID, the `--round` tie-break and messages, and the fix from design review 4 (`--round` judges the snapshot flags it is given, proven by the `seen` assertion at `tests/tools/test_sealed_inventory.py:132`). Both permitted commands ran: `python3 -B tests/tools/test_sealed_inventory.py` passed 10 tests, and `--markdown` ran. I checked the report against the real files and these claims hold: 47/3 split of metadata errors, the seven cards missing from the 2026-10-30 inventory, 43 Mac / 46 VM entries, 54 VM cards, clean wipe records and Mac+VM final-archive presence for fcde6b/86b100/18681d, the registry entries for a4e4d9/a36ad8/fcde6b, and the gates and stop states of the three VM-only fixtures. The 48-creation bound is kept, money, deadline and timeouts are null and listed as founder-required, and no practice or dry-run card is counted. One blocking problem remains: the freeze-blocker test is tied to one checkout and fails in the main checkout. There are also several accuracy nits.

1. **BLOCKING — Test 8 reads the filesystem, not the committed tree, so it fails in the main checkout.**
   - **Evidence:**
     - `tests/tools/test_sealed_inventory.py:202-207` lists the top-level names under `ROOT` and compares them with the list at `docs/exam-packaging.md:84-100`.
     - The main checkout `/home/user/unbug-bench` has an untracked top-level `.claude/` directory (it holds the agent worktrees). That name is not in `INPUTS`/`EXCLUDED`, so `bin/freeze:60-62` would report it, and so would the test.
     - The test passes only in this worktree, which has no `.claude/`. The parent's full suite on the merged tree (ENGINEERING §1 step 4) would fail if it runs in the main checkout, as would any checkout with a stray untracked top-level file.
     - The doc's claim "these top-level names" is therefore also specific to one checkout.
   - **Fix:** Limit the comparison to tracked top-level names, for example `{p.split('/')[0] for p in git ls-files}` filtered by the same predicate, or intersect `iterdir()` with that set. State in `docs/exam-packaging.md` (and in design test 8) that the list is for a clean checkout of the committed tree, and that untracked names in a release checkout also make `bin/freeze` refuse.

2. **NIT — The report describes fcde6b's calibrators wrongly.**
   - **Evidence:** `docs/reports/sealed-audit-20261104.md:86` says "`calibrators: {}`", but the card has no `calibrators` key (`jq 'has("calibrators")'` → `false`).
   - **Fix:** Write "the card has no `calibrators` field".

3. **NIT — The "hard candidates" label overstates 18681d.**
   - **Evidence:**
     - `docs/reports/sealed-audit-20261104.md:87-88` calls 86b100 and 18681d `hard` candidates.
     - 18681d's strong calibrator shows `run_error: 2`, `fix_failed_all_runs: 1`.
     - `FACTORY.md:101` says only an all-`wrong_fix` G17 verdict earns `hard`.
     - ENGINEERING §3 says broken runs are never scored.
   - **Fix:** Say that 18681d's strong 0/3 includes 2 run errors, so it is not a clean zero-solve, and that `hard` still needs G17.

4. **NIT — The report's "All 51 cards" hash claim and design test 1 ("every present card") are not fully tested.**
   - **Evidence:**
     - `docs/reports/sealed-audit-20261104.md:28` claims all 51 cards reproduce their 2026-10-29 hash.
     - `tests/tools/test_sealed_inventory.py:69` checks only the 50 hidden cards. The excluded a869de is never hashed (`inventory()` skips it at `tools/sealed_inventory.py:154-157`).
     - My sandbox did not allow running an ad-hoc hash, so I could not confirm a869de independently.
   - **Fix:** Add a `hashes.vm_20261029` cell to excluded rows and assert it in test 1, or change the report to say "all 50 hidden cards".

5. **NIT — The `inputs` block does not cover every input.**
   - **Evidence:** Design `:68-69` says the JSON "records the path and SHA-256 of every input under `inputs`". `tools/sealed_inventory.py:184-187` hashes only the ciphertext inventory, the registry and the VM record. Card and G11-review file hashes are never output, only `match`/`differs`. Step 1 keeps `inventory.json` as the package evidence, so the card bytes judged are not pinned by it.
   - **Fix:** Add `card_sha256` (the file hash already computed at `:162`) to each hidden and excluded row, or narrow the design sentence to "every snapshot input".

6. **NIT — Every package's `round.json` would map to the same `bin/exam-round` state directory.**
   - **Evidence:** `bin/exam-round` keys its state on `args.round.stem` (`results/exam-round/<stem>`). The package layout fixes the filename as `round.json` (`docs/exam-packaging.md:20`, step 7 at `:71`), so every package maps to `results/exam-round/round/`. A second round would be refused with "round changed …".
   - **Fix:** Name the spec `results/exam/<round-id>/<round-id>.json` and update `docs/exam-packaging.md:20`, `:44` and `:71` (and design §4) to match.

7. **NIT — The tool aborts on one condition the design does not mention.**
   - **Evidence:** `tools/sealed_inventory.py:152-153` raises when a card's `case` field differs from its filename. The design's exception rules (`:118`) do not mention this.
   - **Fix:** Add one sentence to design §1 ("a card whose `case` field differs from its filename aborts the tool").

8. **NIT — Test 2 does not check the `fail:metadata` cell the design names.**
   - **Evidence:** `tests/tools/test_sealed_inventory.py:82` checks the metadata text, but not that `fail:metadata` appears in `findings['complete_evidence']`, which design test 2 lists.
   - **Fix:** Add `self.assertIn('fail:metadata', card['findings']['complete_evidence'])`.

Verdict: FAIL

## Disposition (elephant)

The blocking finding is fixed. No finding was rejected.

1. **Fixed.**
   - The freeze-blocker test now takes the top-level names from the committed tree (`git ls-files -z`) and applies `bin/freeze`'s own predicate to them, so untracked local names such as `.claude/` no longer count.
   - `docs/exam-packaging.md` and design test 8 now say the list is for a clean checkout of the committed tree. They also say that untracked top-level names in a release checkout make `bin/freeze` refuse.
2. **Nit, accepted.** The report now says fcde6b's card has no `calibrators` field.
3. **Nit, accepted.** The report now says 18681d's strong 0/3 includes 2 run errors and 1 fix that failed all runs, and that its easy tries all hit the time limit, so it is not a clean zero-solve. It also says `hard` still needs an all-`wrong_fix` G17 verdict for both cases.
4. **Nit, accepted.** Excluded rows now carry `hashes.vm_20261029`. Test 1 asserts that a869de matches, so the report's claim that all 51 cards match is now tested.
5. **Nit, accepted.** Every hidden and excluded row now records `card_sha256`. Test 1 checks each value against the file bytes. The design sentence now reads "every snapshot input under `inputs`, and the file SHA-256 of every card in its row".
6. **Nit, accepted.** The round spec is now named `results/exam/<round-id>/<round-id>.json` in `docs/exam-packaging.md` (layout, step 2 and step 7) and in design §4.
7. **Nit, accepted.** Design §1 now says that a card whose `case` field differs from its filename aborts the tool.
8. **Nit, accepted.** Test 2 now asserts that `fail:metadata` is in `findings['complete_evidence']`.
