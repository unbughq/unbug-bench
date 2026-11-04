# Exam packaging: layout and procedure

This document says how to package a frozen 24-case scored exam. It is
preparation only. It grants no authority to decrypt, launch, create a worker or
spend money. Design: [sealed-audit-exam-packaging](designs/sealed-audit-exam-packaging.md).

**Current state (2026-11-04):** 0 qualified hidden cases. See the
[sealed audit](reports/sealed-audit-20261104.md). No package can be built
until 24 hidden cases are qualified. Practice and dry-run cases never enter a
package.

## Layout

The package goes in `results/exam/<round-id>/`. `results/` is git-ignored, and
`bin/freeze` and `bin/exam-round` already accept it. Nothing in the package is
committed except the hashes the founder chooses to publish.

| Path | Content | Made by |
|---|---|---|
| `round.json` | `bin/exam-round` spec: `accounts`, `arms`, `tries`, and 24 `cases[].archive` entries of the form `../../../sealed/<case>.tar.gz.age` | hand-written, then checked (step 2) |
| `design.json` | `analysis/ROUND_REPORT.md` design: `synthetic: false`, rule C, no interim look, each case's `tries` and `maintenance_steps`, the seeded third-try subset | hand-written from `analysis/fixtures/measurement-round/design.json` |
| `run-settings.json` | Arms (the main B and C pair, plus any frozen extras), tries (3, or 2 plus a preselected third), 30 judge runs per checkpoint, account round robin, the `--parallel` value, and the `bin/exam-launch` TTL/spend flags. Tries, accounts, parallelism and spend are **founder-fixed at freeze time**; `EXAM.md` section 10 still leaves 2 or 3 tries open | hand-written, founder values |
| `inventory.json` | `python3 -B tools/sealed_inventory.py` output at freeze time | step 1 |
| `audit/<case>.md` | Decrypting audit record for each of the eight criteria: distinct bug, viable reference fix, legitimate business behavior, discoverable requirements, deterministic scorer, adversarial checks, complete evidence, separation from contestant development | step 3, under founder authority |
| `cards/<case>.scorecard.json` | Copies of the public cards | step 4 |
| `cases.sha256` | One line per file: archive SHA-256 (must equal the card's `sha256`), card file SHA-256, and each G11/G16/G17 review receipt SHA-256 | step 4 |
| `freeze/` | `bin/freeze create` output (`manifest.json`, `manifest.sha256`, `source.tar.gz`) | step 5 |
| `PACKAGE.sha256` | SHA-256 of every file above | step 6 |
| `LAUNCH.md` | The exact launch and resume commands (below) | step 6 |

## Procedure

Each step must pass before the next one starts. If a step fails, stop and
report the failure. Never edit a frozen input to make a step pass.

1. **Inventory.** Run `python3 -B tools/sealed_inventory.py --inventory <fresh ciphertext inventory> --registry <fresh registry snapshot> > results/exam/<id>/inventory.json`.
   - Every case you plan to include must be listed as hidden with
     `public_eligible: true`.
   - The tool reads public files only.
   - The default inputs are the committed 2026-10-30 snapshots. Every case
     sealed after them stays non-eligible until both snapshots are refreshed.
   - The output's `inputs` block records the path and SHA-256 of each
     snapshot; keep it in the package.
2. **Round check.** Run `python3 -B tools/sealed_inventory.py --round results/exam/<id>/round.json --expect 24`.
   - It must exit 0.
   - It rejects any case that is unknown, excluded (dry run, practice or
     smoke), not eligible, or duplicated, and it rejects any count other than 24.
   - It does not open the archives.
3. **Decrypting audit.** This step needs founder authority and is not part of
   any cloud preparation job.
   - Write one record per case covering the eight criteria.
   - Run the existing archive-backed check `factory/sealed_audit.py:verify_exam`
     on the restored case.
   - Record who saw plaintext. That record is the separation attestation,
     which public files cannot supply.
   - A case is **qualified** only when all eight criteria pass.
4. **Hashes and cards.** Copy the public cards into the package and write
   `cases.sha256`.
   - The SHA-256 of each `sealed/<case>.tar.gz.age` must equal its card's
     `sha256`.
   - `bin/exam-round` hashes the archives again at launch and saves them in
     `results/exam-round/<round>/manifest.json`.
5. **Freeze.** Run `bin/freeze --root <release checkout> create results/exam/<id>/freeze --runtime <runtime.json> --evidence results/exam/<id>/inventory.json`.
   - Add one `--archive` per sealed case.
   - Check that `bin/freeze verify` passes.
   - **Blocked today:** see "Known blockers".
6. **Seal the package.** Write `PACKAGE.sha256` and `LAUNCH.md`, then hand
   the package hash to the founder. The founder decides whether to publish it.
7. **Launch.** This step needs founder authority. Run
   `cat /secure/founder-identity | bin/exam-round results/exam/<id>/round.json --parallel N`.
   - To resume, run the identical command.
   - `bin/exam-launch` re-runs `verify_exam_metadata` for each case, and
     `bin/run-exam` runs `verify_exam` on the restored archive.
8. **Report.** Run `analysis/report_round.py` on the collected scorecards
   with the frozen `design.json`.
   - Handle missing or invalid checkpoints under the frozen
     missing-data rule; never drop them silently.

## Known blockers

- **`bin/freeze create` refuses this tree.** `source_files` (`bin/freeze:58`)
  raises `Unclassified bench inputs` for these top-level names:
  - `AGENTS.md`
  - `BRIEF-v2.md`
  - `CLAUDE.md`
  - `DESIGN.md`
  - `EXAM.md`
  - `EXPLAINER.html`
  - `PRODUCT.md`
  - `V2.md`
  - `analysis`
  - `control`
  - `docs`
  - `refusal-integration-r5.json`
  - `refusal-integration-r6.json`
  - `refusal-integration-r7.json`
  - `refusal-integration-r8.json`
  - `report`
  - `tools`

  Step 5 cannot run until a separately reviewed change classifies these names
  as inputs or exclusions. Until then this procedure is not reproducible.
  `tests/tools/test_sealed_inventory.py` fails when this list no longer
  matches the real refusal.
- **Zero qualified hidden cases.** The three G1–G15 cards are fcde6b, 86b100
  and 18681d. Before any of them can count, each needs:
  - a G16, G10 and G17 rerun under the current binding
    (`docs/designs/stream-d.md`);
  - a dedup check;
  - registry promotion from its historical entry (`complete: false`) to a
    screened `completed` reservation (`factory/registry.py:60-66`);
  - step 3.

  The audit rerun (`sealed_audit.run`) produces neither the dedup check nor
  the registry promotion. That remains an open blocker.
- **No fresh ciphertext inventory or registry snapshot.** The committed
  2026-10-30 inventory was a one-off read-only survey. No committed tool
  produces one.
  - Step 1 needs a new snapshot taken after the last case seals. It must have
    the same schema: per host, `checkpoints[]` entries with `case`,
    `card_sha256`, `card_archive_sha256`, and `files[]` entries with `name`,
    `sha256` and `size`.
  - It also needs a copy of the control VM's live
    `sealed/statement-registry/registry.json`.
  - Both need host access under founder authority.
- **No archives in this checkout.** The final `*.tar.gz.age` files exist only
  on the founder's Mac and the control VM, per the 2026-10-30 inventory.
  Step 4 must run where they are.
