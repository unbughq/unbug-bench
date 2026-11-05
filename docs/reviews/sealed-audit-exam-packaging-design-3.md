# Design review 3: sealed-audit-exam-packaging

Reviewer: a fresh goldfish (`claude -p` subprocess) with no conversation history and the same model family as the elephant. Its tools were read-only. It used the zoom_out, design_critic and implementation_readiness personas in REVIEW mode, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. It reviewed the twice-revised design together with design reviews 1 and 2.

## Verbatim review

**Summary verdict.** Every blocking finding from the two earlier reviews (review 1 #1–6, review 2 #1–3) is fixed in the design text, and I checked those fixes against the real files. The design stays inside the job's limits:
- it uses public files only and opens no `.age` or `*key*` file;
- evidence it can't get is recorded as unavailable, so the qualified count is 0 by design;
- practice, smoke and dry-run cards are excluded;
- no budget, ledger, route or enablement changes;
- 48 creations including retries, with money, deadline and timeouts left null and founder-required.

One new blocking problem remains. Two of the tool's inputs are fixed snapshots: the 2026-10-30 ciphertext inventory and the checked-in registry. No case sealed after those snapshots can ever become public-eligible. So the §4 packaging procedure can't pass the `--round` check for any real 24-case round, which is the round it exists for.

## Prior blocking findings: checked

- **R1 #1 (count):** fixed (`:156`, `:256`). Grep of `sealed/case-*.scorecard.json` gives 51 cards. Only a869de has `dry_run: true` / `source: "fixture (dry-run)"`; the other 50 are `port` or `hunt`.
- **R1 #2 (freeze, package location):** fixed (`:203-205`, `:234-239`, test 8 `:308-312`). The predicate matches `bin/freeze:60-62`.
- **R1 #3 (hash method):** fixed (`:47-52`).
- **R1 #4 (rule for each cell):** fixed (`:77-100`).
- **R1 #5 (`--round`):** fixed (`:119-136`), with the same `removesuffix(".tar.gz.age")` rule as `bin/exam-round:45`.
- **R1 #6 (manifest fields):** fixed (`:179-188`).
- **R2 #1 (test 3 values):** fixed. Findings now list every non-pass part (`:86-89`). e5caf7 passes G2 and G4, has `dedup.duplicate_of: null`, and its registry entry has `complete: false` (`sealed/case-20261018T144339Z-e5caf7.scorecard.json:8-10,98-101`). 8f9762 has a string `wipe` (`:8742`). 1ad7fa's `sha256` is its checkpoint hash (`batch-service-inventory-20261030.json:207-208`).
- **R2 #2 (eligibility path):** fixed (`:158-169`, `:195-199`). The promotion path exists: `factory/registry.py:62-66` promotes a historical `completed`/`complete:false` entry to a fresh `screening` entry.
- **R2 #3 (registry status):** fixed (`:93`). In the registry, a4e4d9 is `complete:true` and released; a36ad8 is `complete:true` and screening.

## Findings

**1. BLOCKING: dated snapshot inputs make the packaging procedure fail for every future case.**
- *Evidence:* The tool's purpose is to be rerun as new cards land (`:31-33`). Its inputs are hard-coded files with no flag to replace them: `docs/reports/batch-service-inventory-20261030.json` (`:53`) and `sealed/statement-registry/registry.json` (`:55`). Only `--cards` can be changed (`:44`).
- Under "Complete evidence" (`:99`), any card whose final archive is missing from the 2026-10-30 inventory gets `missing:ciphertext-inventory`. Every case sealed afterwards falls into that group, and the design says all 24 must come from future production (qualified count 0, `:157`).
- Similarly, the registry cell needs `complete is True and status == "completed"`, read from a checked-in copy that the live coordinator registry won't update.
- Result: procedure steps 1–2 (`:223-224`) reject every real round with `not eligible <id>: missing:ciphertext-inventory` or `missing:registry-*`. The design lists stale inputs as a risk (`:330-331`) but doesn't say what this means for §4. Whoever implements it has to decide how fresh evidence gets in, which the zero-decision rule forbids.
- *Fix:*
  - Add `--inventory PATH` and `--registry PATH`, defaulting to today's files.
  - In `docs/exam-packaging.md` step 1, say that the freeze-time run uses a ciphertext inventory and registry snapshot taken after the last case sealed. Name the existing producer, or record it as a founder-authority blocker beside the `bin/freeze` blocker. Record the inputs' hashes in the package.
  - Don't relax the cell. A case missing from a stale snapshot must stay non-eligible.
  - Add a test that runs `--round` with `--inventory` pointed at a different real inventory file (or the same file) and checks that the path is honoured.

**2. NIT: test 3's registry cases have no card, and the design names no interface to test them.**
- *Evidence:* a4e4d9 and a36ad8 have no card in `sealed/`, and cells are computed only for cards (`:71`). Test 3 (`:273-275`) says the entries "map to" values, but the design names no function to call.
- *Fix:* Name the predicate, e.g. `registry_part(entry) -> str`. Test 3 calls it on the real entries.

**3. NIT: the spelling of *unavailable* findings isn't defined.**
- *Evidence:* `:89` says unavailable parts always appear in `findings`, and `:102` excludes them from eligibility, but the design never gives their string form (e.g. `unavailable:screening-verdict`). Test 6 only checks the report against the tool's own output.
- *Fix:* Give the exact token for each of the four unavailable parts, and say whether the criterion cell skips them when choosing its first entry.

**4. NIT: 1ad7fa is called "paused", but its status is "stopped".**
- *Evidence:* `:277` says "a paused card". `sealed/case-20261017T212118Z-1ad7fa.scorecard.json:15716` has `"status": "stopped"`.
- *Fix:* Change the wording to "stopped".

**5. NIT: the implementation is already on the branch.**
- *Evidence:* Commit `227d5e2` already contains `tools/sealed_inventory.py` and `tests/tools/test_sealed_inventory.py`, so they were written before this design passed review.
- *Fix:* After revision, the diff review must check the code against this final text, especially finding 1 and the tie-break in finding 3.

Verdict: FAIL

## Disposition (elephant)

The blocking finding is fixed and nothing is rejected.

1. **Fixed.**
   - **New flags.** The tool now takes `--inventory PATH` and `--registry PATH`. Both default to today's snapshots. Its JSON output records the path and SHA-256 of every input under `inputs`.
   - **Cell rule unchanged.** A case absent from a stale snapshot stays non-eligible.
   - **Packaging step 1.** `docs/exam-packaging.md` step 1 now says the freeze-time run must use a ciphertext inventory and a registry snapshot taken after the last case seals, and that both input hashes go into the package.
   - **Blocker recorded.** No committed tool produces a fresh inventory. The 2026-10-30 file came from a one-off survey. This gap is now a founder-authority blocker, listed next to the `bin/freeze` blocker, together with the schema the new snapshot must follow.
   - **Test.** `test_snapshot_paths_are_honoured` builds copies of the real inventory and registry with fcde6b removed. Run through both the function and the `--inventory`/`--registry` CLI, fcde6b gets `missing:ciphertext-inventory` and `missing:registry-entry`.
2. **Nit, accepted.** The design names the predicate `registry_cell(entry) -> str`, and test 3 calls it.
3. **Nit, accepted.** The design lists the three exact unavailable tokens. Each is always the last entry of its criterion, and the table cell shows the first finding, which can be an unavailable one. The review counted four unavailable parts. There are three, one each for distinct bug, complete evidence and separation.
4. **Nit, accepted.** Changed "paused" to "stopped".
5. **Nit, noted.** Code and tests were committed on the branch at `227d5e2` while the design was still in review. This is allowed: ENGINEERING section 1 step 4 says to commit as often as you like. The diff review will check the code against the final design text, in particular finding 1 and the tie-break.
