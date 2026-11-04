# Design review 2: sealed-audit-exam-packaging

**Reviewer:** a fresh goldfish, run as a `claude -p` subprocess with no conversation history. It is the same model family as the elephant.

- **Tools:** read-only.
- **Personas:** zoom_out, design_critic, implementation_readiness.
- **Mode:** REVIEW.
- **Standards:** `heilmeier-standard.md` and `implementation-readiness-standard.md`.
- **Reviewed:** the revised design, together with `docs/reviews/sealed-audit-exam-packaging-design-1.md`.

## Verbatim review

The revised design still fails. All six blocking findings from review 1 are fixed in the text, but I found three new blocking problems. Two are in the "Distinct bug" rule: test 3's expected values contradict the design's own rule, and the claim that the three G1–G15 cards could become eligible after a rerun is wrong. The third is a registry check that would accept a released (rejected) case. I checked everything with Read/Grep only; I ran no Python and executed no code.

## Summary verdict

The design stays inside the job's limits:
- It uses only public files and opens no `.age` or `*key*` file.
- It records unavailable evidence as unavailable, so the qualified count is 0 by design.
- It excludes dry-run and smoke cards.
- The manifest is inactive: money, deadline and completion timeouts are null and founder-required; 48 creations including retries; no new routes.
- It reuses `verify_exam_metadata`, adds no runner, and records the `bin/freeze` refusal as a known blocker.

Review 1's blocking findings:
- **#1 (count):** fixed, `:156`, `:187`, `:245`.
- **#2 (freeze, package location):** fixed, `:194-196`, `:223-228`.
- **#3 (hash method):** fixed, `:47-52`.
- **#5 (`--round`):** fixed, `:119-136`.
- **#6 (manifest fields):** fixed, `:171-178`.
- **#4 (rules for each cell):** the decision table exists, but its tests and expected results contradict it, and the registry rule is incomplete. That is findings 1–3 below.

## Findings

**1. BLOCKING: test 3 expects values the design's own rule cannot produce.**
- *Evidence:* The rule at `:91-93` says a criterion cell takes the first non-pass part, in order (G2, G4, then `dedup`, then registry). Checked against the real cards:
  - fcde6b has no `dedup` key at all (it is not among the 31 files matching `dedup` in `sealed/`). Its "Distinct bug" cell is therefore `missing:dedup`, not `missing:registry-screening` as test 3 says (`:257`).
  - 953035 has `"gates": {}` (`sealed/case-20261019T022248Z-953035.scorecard.json:6`), so its cell is `missing:G2`, not `fail:duplicate_of=…` (`:256`). The other two cards with a `duplicate_of` value, 6a8a7d and 5a6ef3, also have no G2/G4 pass. No real card can reach the `duplicate_of` part at the criterion level.
  - a869de is excluded (`:62`), and cells are written only for hidden cards (`:71`). So "a869de has `skipped (model gate)` read as missing" (`:259`) can never be observed.
- *Fix:* Pick one option and state it:
  - (a) Also emit one cell per part (e.g. `parts.distinct_bug.dedup`) and point test 3 at the part cells.
  - (b) Keep only criterion cells and change test 3's cards: use e5caf7 or another card with G2/G4 pass, `dedup.duplicate_of: null` and `complete: false` for `missing:registry-screening`. Test the `skipped` → `missing` rule with `--cards` pointed at a directory containing a hidden card that has a skipped gate, or drop that case.

  Either way, say that `fail:duplicate_of` has no real card that reaches it at the criterion level.

**2. BLOCKING: the eligibility path for the three G1–G15 cards is wrong, and so is the shortfall basis built on it.**
- *Evidence:*
  - `:158-161` says fcde6b, 86b100 and 18681d each need "a G16, G10 and G17 rerun before it can become eligible". Under `:93`, none of the three has `dedup`, so each also fails `missing:dedup`.
  - All 37 registry entries for cards in `sealed/` are `complete: false` (historical imports, `factory/registry.py:82-85`). The 4 `complete: true` entries belong to cases with no card in `sealed/` (a4e4d9, a36ad8, 112411, 2d787b).
  - The audit rerun `sealed_audit.run` (`factory/sealed_audit.py:217-229`) produces neither a `dedup` record nor a fresh registry reservation.
  - So under this design, no existing card can ever become public-eligible. §2, §3's `:186-190` and the "three legacy candidates" in test 8 (`:281`) suggest otherwise.
- *Fix:* State in §2 and in the manifest's shortfall/blockers that each legacy card also needs a dedup check and registry promotion. Name the mechanism (the historical-promotion path in `registry.py:60-66`) or record it as an open blocker. Do not relax the rule. Add a test-2 assertion that each of the three is `missing:dedup`.

**3. BLOCKING: the registry check ignores the entry's `status`, so a released or still-screening entry passes.**
- *Evidence:*
  - `:93` checks only whether an entry exists and its `complete` flag.
  - New reservations are written with `complete: true` and `status: "screening"` (`registry.py:83-85`). `released` means the entry was rejected or reselected (`registry.py:108-112`, `:142`).
  - The registry today holds `complete: true` entries with `status` `released` (a4e4d9) and `screening` (a36ad8, 112411, 2d787b).
  - The tool exists to be rerun as new cards land (`:31-33`), and `--round` relies on it. A card whose entry was released, or never finished screening, would pass "Distinct bug".
- *Fix:* Pass only when `complete is True and status == "completed"`. Map `status == "released"` to `fail:registry-released`, and any other status to `missing:registry-screening`. Add a test that runs the predicate on the real a4e4d9 and a36ad8 entries.

**4. NIT: how `verify_exam_metadata` exceptions are handled is not specified.**
- *Evidence:* `:71-73` says "records the error text". The function raises `ValueError` by design, but a malformed card can raise `KeyError` or `TypeError` (`sealed_audit.py:69` indexes `card["gates"]`; `:72` assumes `roles` is a dict).
- *Fix:* Catch only `ValueError` and record it as `fail:metadata`. Let any other exception abort the tool with the case ID.

**5. NIT: the ciphertext check also matches checkpoint archives.**
- *Evidence:* `:99` accepts the card `sha256` matching any file in the inventory. Several entries list `.checkpoint.tar.gz.age` files (e.g. `batch-service-inventory-20261030.json:5-12`, 11a9f1, where `card_archive_sha256` is the checkpoint).
- *Fix:* Only match files named `<case>.tar.gz.age`.

**6. NIT: test 8's "does not raise" branch would hash `*key*` files.**
- *Evidence:* If `source_files(ROOT)` (`bin/freeze:58-87`) succeeds, it hashes every input, including `scenarios/dev/*/key.json` and `cases/medusa-oversell-v2/answer-key.json`.
- *Fix:* Derive the unclassified names from `bin/freeze`'s `INPUTS`/`EXCLUDED` and `ROOT.iterdir()`, using the same predicate as `:60-62`. Or call `source_files` under test 5's open-guard.

**7. NIT: the number of tries in `run-settings.json` has no owner.**
- *Evidence:* `:205` lists tries. `EXAM.md:387-388` says 2 or 3 tries per arm is still undecided.
- *Fix:* Mark tries, accounts and parallelism as values fixed at freeze time by the founder, as was done for money and deadline.

Verdict: FAIL

## Disposition (elephant)

All three blocking findings are fixed in the design. None were rejected.

1. **Fixed, using option (a).** The tool's JSON lists every non-pass part for each criterion (`findings`). The table cell shows the first of them.

   Test 3 now asserts on `findings`, using these real cards:
   - 953035: `fail:duplicate_of`.
   - e5caf7: G2/G4 pass and `duplicate_of` is null, but `complete` is false, so its first Distinct-bug finding is `missing:registry-screening`.
   - 8f9762: a string `wipe`.
   - 1ad7fa: a checkpoint hash, which gives `missing:ciphertext-inventory`.

   The design now states two limits. No real card with a `duplicate_of` value reaches that part at the criterion level. The `skipped` rule has no real-card test.
2. **Fixed.** Each of the three G1-G15 cards also needs a dedup check and registry promotion through `factory/registry.py:60-66`. `sealed_audit.run` produces neither, so this is recorded as an open blocker. The rule is not relaxed.

   This is now stated in:
   - section 2 of the design;
   - the manifest proposal (`shortfall_estimate` and `blockers`);
   - `docs/exam-packaging.md`;
   - the report.

   Test 2 asserts `missing:dedup` and `missing:registry-screening` for the three cards.
3. **Fixed.** The registry cell passes only when `complete is True and status == "completed"`. `released` maps to `fail:registry-released`, and anything else maps to `missing:registry-screening`. Test 3 runs the predicate on the real a4e4d9 (released) and a36ad8 (screening) entries.
4. **Nit, accepted.** Only `ValueError` is recorded as `fail:metadata`. Any other exception aborts the run with the case ID.
5. **Nit, accepted.** Ciphertext matching uses only final `<case>.tar.gz.age` archives. Under this rule, 10 hidden cards have a final archive in both inventories.
6. **Nit, accepted.** Test 8 finds the unclassified names with `bin/freeze`'s own predicate (`INPUTS`/`EXCLUDED` and `iterdir`). It never calls `source_files`, so nothing is hashed.
7. **Nit, accepted.** Tries, accounts, parallelism and spend are marked as founder-fixed at freeze time.
