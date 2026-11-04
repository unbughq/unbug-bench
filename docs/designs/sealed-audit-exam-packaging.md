# Sealed-case audit, inactive production manifest and exam packaging

Cloud handoff Job 3 ("parallel preparation", `docs/cloud-handoff.md`). Branch
`claude/sealed-audit-exam-packaging`, cut from `origin/factory-simplify` at
`fbca505`. Preparation only: nothing here launches, deploys, creates a worker,
decrypts a case, reads a key, changes a model route or changes any budget,
ledger, journal or spending authority.

## Problem

The handoff checklist has three open items that need no live authority:

1. "Audit the sealed inventory once and count only qualified hidden cases."
2. "Review/pin the bounded production manifest, completion timeouts, roles,
   cumulative money ceiling, deadline and attempt/concurrency limits" (48 worker
   creations including retries; money cap and deadline need the founder).
3. "Freeze encrypted cases, hashes, public cards, scoring/run settings and the
   reproducible exam launch procedure."

Today nobody can say how many hidden cases qualify. The facts are spread across
several files:

- 51 public cards in `sealed/`;
- a 54-card VM read on 2026-10-29 (`docs/designs/stream-d-cost-evidence.json`);
- a ciphertext inventory from 2026-10-30
  (`docs/reports/batch-service-inventory-20261030.json`);
- the gate table in `FACTORY.md`;
- the exam admission check `factory/sealed_audit.py:verify_exam_metadata`.

The only statement of the G16/G17 gap is a sentence in `docs/designs/stream-d.md`
("No card records a G16/G17 pass"). A hand count goes stale as soon as a new
card lands. It can also include a dry-run card by mistake: one of the 51 cards in
`sealed/` is a dry run.

There is also no written production manifest proposal, and no written
procedure that says what a frozen 24-case exam package contains.

## Change

### 1. Read-only inventory tool: `tools/sealed_inventory.py`

**Inputs.** Public files only.

- `--cards DIR`, default `sealed/`: every `case-*.scorecard.json` in DIR. The
  tool never scans `g11-review-*` receipts as cases. It reports them under the
  case they review, using their `case` field.
- `docs/designs/stream-d-cost-evidence.json`: the 2026-10-29 VM card hashes.
  Their recorded method (`extraction_method.vm`) is
  `sha256(json.dumps(card, sort_keys=True, separators=(",", ":")).encode())`.
  Applied to this checkout, that method reproduces all 51 VM records whose
  cards are present. Three VM cards are not in this checkout: c7d405, e15450
  and 873d7f.
- `docs/reports/batch-service-inventory-20261030.json`: Mac and VM ciphertext
  names and SHA-256s, plus the file SHA-256 of each card (`card_sha256`).
- `sealed/statement-registry/registry.json`: for each case, whether an entry
  exists and the value of its `complete` flag. The tool never opens the
  `.age` objects. A `complete: false` entry is a historical import: per
  `factory/registry.py:83`, it was never screened as a fresh reservation.

**Hidden or excluded.** A card is **excluded** (not hidden) if any of these
holds, and the first one that holds is recorded as the reason:

- `dry_run is True`;
- `source` is not in `{"port", "hunt"}`. These are the two real sources in
  `factory/launch.sh:2`; `plant` is not used for hidden cases;
- the case ID matches `practice` or `smoke`.

Excluded cards are listed separately and never counted.

**Cells.** For each hidden card the tool writes a status/stop summary and the
gates passed. It runs `sealed_audit.verify_exam_metadata`, the existing
pre-decryption admission check that `bin/exam-launch` and `bin/run-exam`
already run, and records the error text or `ok`. It reuses that check rather
than writing a second definition. It also fills one cell for each of the eight
handoff criteria.

Gate cells use one rule, shown here for gate `Gn`:

| Card value | Cell |
|---|---|
| `gates[Gn] == "pass"` | `pass` |
| `gates[Gn] == "fail"` | `fail:Gn` |
| key absent | `missing:Gn` |
| any other value, e.g. `skipped (model gate)` | `missing:Gn` |

The JSON output lists every non-pass part for each criterion (`findings`), in
the order shown below. The criterion cell in the table is the first entry in
that list, or `pass` if the list is empty. Parts marked *unavailable* always
appear, because public files cannot supply them.

| Criterion | Parts, in order |
|---|---|
| Distinct bug | G2, G4; `dedup` absent → `missing:dedup`, `dedup.duplicate_of` non-null → `fail:duplicate_of=<id>`; registry: no entry → `missing:registry-entry`, `status == "released"` → `fail:registry-released`, `pass` only when `complete is True` and `status == "completed"`, otherwise → `missing:registry-screening`; *unavailable: screening verdict content* |
| Viable reference fix | G5 |
| Legitimate business behavior | G5, G9 |
| Discoverable requirements | G8, G16 |
| Deterministic scorer | G7 |
| Adversarial checks | G6, G11, G13, G14, G15 |
| Complete evidence | G10, G12, G17; `verify_exam_metadata` raises `ValueError` → `fail:metadata` (any other exception aborts the tool with the case ID); card `sha256` not equal to a final `<case>.tar.gz.age` (never a checkpoint) in the 2026-10-30 inventory → `missing:ciphertext-inventory`; *unavailable: archive-backed verify_exam* |
| Separation from contestant development | `wipe` not a dict, or any of `plaintext_files_left`, `named_dirs_left` non-zero, or `guard_image_left`, `db_volume_left` true, or `factory_cleanup_ok` not true → `missing:wipe-record`; *unavailable: no-exposure attestation* |

A case is **public-eligible** when every cell is `pass` except the
*unavailable* parts. A case is **qualified** only when every cell is `pass`.
Public files can never supply the *unavailable* parts, so the qualified count
from this tool is 0 by design. Public evidence can disqualify a case, or make
it eligible for the decrypting audit. It can never qualify a case. The tool
reports four numbers: hidden, excluded, public-eligible and qualified. It never
lowers this bar.

**Hash cells.** These are informational and never part of qualification:

- the card's canonical hash against the 2026-10-29 record: `match`, `differs`
  or `not-recorded`;
- the card's file hash against the 2026-10-30 `card_sha256`: `match`,
  `differs` or `not-recorded`;
- which of the Mac and VM inventories hold a file whose SHA-256 equals the
  card's `sha256`.

**`--round round.json [--expect 24]`.** This checks a proposed
`bin/exam-round` spec before any freeze or launch. The tool parses the JSON
itself. It maps each `cases[].archive` to a case ID with `bin/exam-round`'s
rule: the basename with `.tar.gz.age` removed. It then looks the ID up among
the cards in `--cards`. It never opens, stats or hashes the archive. It exits
nonzero with one line per problem:

| Problem | Message |
|---|---|
| No card for the case | `unknown case <id>` |
| The card is excluded | `not hidden <id>: <reason>` |
| The card is hidden but not public-eligible | `not eligible <id>: <first non-pass cell>` |
| The same case appears twice | `duplicate <id>` |
| The count is wrong | `expected N cases, got M` |

`bin/exam-launch` keeps its own per-case check at launch. This check applies the
same rule earlier, to the whole round. Even a passing round still needs the
decrypting audit record for each case (§4).

**Output.** JSON by default; a Markdown table with `--markdown`. The tool
makes no network, Docker, model or cloud call, and it opens no `.age` file and
no file whose name contains `key`.

### 2. Audit report: `docs/reports/sealed-audit-20261104.md`

The report holds:

- the generated table;
- the four counts, with the reason for each;
- the list of unavailable evidence;
- the three VM-only cards from 2026-10-29. Their public copies in
  `tests/factory/fixtures/` (for example `e15450-round9-collected-card.json`)
  show empty gates and stopped status. Because they are not in `sealed/`, they
  are reported but not counted.

Expected from the survey (the generated report and test 6 are authoritative):

- 50 hidden cards; 1 excluded (`case-20261014T130816Z-a869de`, a dry run);
- **0 public-eligible, 0 qualified**;
- three cards pass G1–G15: fcde6b, 86b100 and 18681d. Each lacks G16/G17,
  `owner_contract`, `delivery_provenance` and a `dedup` record, and each
  registry entry is a historical import (`complete: false`). To become
  eligible, each needs:
  - a G16, G10 and G17 rerun under the binding migration in `stream-d.md`
    (§"Remove the paid cap");
  - a dedup check;
  - registry promotion through the existing historical-promotion path
    (`factory/registry.py:60-66`), screened to `completed`.

  The audit rerun `sealed_audit.run` produces neither of the last two, so
  this is recorded as an open blocker. The rule is not relaxed.

### 3. Inactive production manifest proposal: `docs/designs/production-manifest-proposal.json`

The proposal lives under `docs/`, not `factory/batches/`. That keeps it away
from `batch.build`/`verify`, the release builder and the deploy path. It
contains:

- `status: "inactive-proposal"` and `launch_authority: false`.
- `max_worker_creations_including_retries: 48`.
- `money_limit_usd: null`, `batch_deadline: null` and
  `completion_timeouts: null`. All three are named in `founder_required`.
  The record cites the current facts: the 8 h default worker TTL
  (`factory/launch.sh:4`, Murphy 5) and the pilot's 30-minute cutoff, which
  was an experiment and not a completion timeout (`pilot-run.md`). It does
  not choose a value.
- `per_case_limits: {extensions: 5, factory_bug_resumes: 3}`, from ENGINEERING
  §3. These are existing rules, copied and not changed.
- `max_concurrency: 1` until parallel admission, spending and cleanup are
  qualified; ramp milestones 3/10/17/24.
- Role routes: a reference to the pins already reviewed in
  `docs/designs/pilot-bounded-roles.md`, with no new route. That design binds
  admission to `b-real-pilot` with exactly three templates. Admitting this
  proposal therefore needs its own reviewed admission change, recorded under
  `blockers`.
- `qualified_hidden_cases_at_proposal: 0`, copied from the generated audit.
- A shortfall estimate, which is not a limit change. The public G1–G15 seal
  rate is 3 of 50 hidden cards. At that rate, 48 creations would not yield 24
  qualified cases, and even those 3 need G16/G10/G17, dedup and registry
  promotion. As the handoff says, the shortfall is reported; limits are not
  raised and quality is not lowered without notice.

### 4. Exam packaging procedure: `docs/exam-packaging.md`

**Location.** The package lives in `results/exam/<round-id>/`. `results/` is
git-ignored and already accepted by `bin/freeze` and `bin/exam-round`.
`bin/freeze` runs with `--root` set to the release checkout.

**Contents:**

- `round.json`: the `bin/exam-round` spec, listing 24 archives;
- `design.json`: the `analysis/ROUND_REPORT.md` design with `synthetic: false`;
- the `bin/freeze` manifest;
- `cases.sha256`: the archive, card and review receipt hashes;
- copies of the public cards;
- `run-settings.json`: arms, tries, 30 judge runs, accounts and parallelism.
  Tries, accounts and parallelism are fixed by the founder at freeze time,
  because `EXAM.md` still leaves 2 or 3 tries open;
- the generated inventory JSON;
- the per-case decrypting audit records;
- the launch commands.

**Procedure:**

1. Run the inventory.
2. Run the `--round` check.
3. Record a decrypting audit per case. This is done under the founder's
   authority, not in this job.
4. Run `bin/freeze create`.
5. Hash the package.
6. Hand the package to the founder for launch.

The procedure reuses `bin/exam-round`, `bin/exam-launch`, `bin/freeze` and
`analysis/report_round.py`. It adds no new runner.

**Known blocker.** `bin/freeze create` refuses this tree today. `source_files`
(`bin/freeze:58`) raises "Unclassified bench inputs" for top-level names
outside `INPUTS`, such as `docs`, `tools`, `analysis` and `control`. Step 4
cannot run until a separately reviewed change classifies those names. The
document lists the blocker, and test 8 keeps that list in step with the real
refusal. Until then the procedure is not claimed to be reproducible.

## What it deletes

Nothing in code. The generated audit replaces hand counts in prose. The G16/G17
sentence in `stream-d.md` stays as history. No existing tool does this job:

- `deployment_inventory.py`, `tests/factory/test_restore_inventory.py` and
  `tools/migrate-legacy-checkpoints.py` inventory checkpoints for restore, not
  for exam qualification;
- `tools/unlock_sealed_audit.py` decrypts cases, so this job must not use it.

## Tests: `tests/tools/test_sealed_inventory.py`

Every test uses the real saved cards and reports in this checkout. No test
generates its input with the tool under test.

1. **Counts.** `sealed/` holds exactly 50 hidden cards and 1 excluded card
   (a869de, `dry_run`). The canonical hash of every present card equals its
   2026-10-29 record. The file hash of every card listed on 2026-10-30 equals
   that inventory's `card_sha256`.
2. **Zero eligible.** No card is qualified or public-eligible. For each of the
   three G1–G15 cards:
   - "Distinct bug" findings include `missing:dedup` and
     `missing:registry-screening`;
   - "Discoverable requirements" is `missing:G16`;
   - "Complete evidence" is `missing:G17`;
   - `verify_exam_metadata` returns its fairness error;
   - the card's `sha256` appears in both the Mac and VM inventories.
3. **Per-rule cases**, each on real data. These assert on `findings`, because
   no real card with a `duplicate_of` value passes G2 and G4:
   - 953035's findings include `fail:duplicate_of=case-20261017T212115Z-8acb5c`;
   - e5caf7 passes G2 and G4 and has `dedup.duplicate_of: null`, and its first
     Distinct-bug finding is `missing:registry-screening`;
   - the real registry entries a4e4d9 (`released`) and a36ad8
     (`screening`, `complete: true`) map to `fail:registry-released` and
     `missing:registry-screening`;
   - a card with a string `wipe` (8f9762) has `missing:wipe-record`;
   - a paused card whose `sha256` is a checkpoint hash (1ad7fa) has
     `missing:ciphertext-inventory`.

   No hidden card has a `skipped` gate value, so that rule has no real-card
   test.
4. **Smoke card.** With `--cards` set to
   `docs/reports/provisioning-startup-smoke/local-startup/`, the real smoke
   card `case-20261103T220109Z-391cbc` is excluded for `dry_run`, and the
   hidden count is 0.
5. **No secret reads.** While the full inventory runs,
   `builtins.open`, `io.open`, `os.open`, `Path.read_bytes` and
   `Path.read_text` are patched to raise on any path ending in `.age` or
   whose name contains `key`.
6. **Report in sync.** The table in `docs/reports/sealed-audit-20261104.md`
   equals the tool's `--markdown` output for this checkout, so the report
   cannot drift.
7. **Proposal inactive.** In the manifest proposal:
   - `status` is inactive and `launch_authority` is false;
   - money, deadline and completion timeouts are null and listed in
     `founder_required`;
   - creations equal 48, and per-case limits equal 5 and 3;
   - the qualified count equals the tool's;
   - no `factory/batches/*.json` has the proposal's `id`.
8. **Round check and freeze blocker.** `--round` gives the exact message for
   each of these rounds:
   - one naming the three legacy candidates (not eligible);
   - one naming a869de (not hidden);
   - one naming an unknown case;
   - one with a duplicate;
   - one with the wrong count.

   Separately, the unclassified top-level names are computed with the same
   predicate as `bin/freeze:60-62`: `ROOT.iterdir()` against the imported
   `INPUTS`/`EXCLUDED`. Nothing is hashed, so no `*key*` file is read. The
   names must equal the blocker list in `docs/exam-packaging.md`. If that
   list becomes empty, the test requires the blocker entry to be removed.

## Murphy rows

None closed. Rows touched, not closed:

- 41 (G16/G17 repeat the same inconclusive review): the audit shows that no
  card has G16/G17 at all.
- new-batch-service-1 (Mac and VM generations differ): the report shows the
  per-case Mac/VM ciphertext presence. For 18681d, both inventories list the
  same final archive hash; only the checkpoints differ.

No real-run failure was observed, so no row is added.

## Cost, timeline, risks

- **Cost and timeline:** zero model or compute spend. One implementation and
  review increment, plus one full offline suite.
- **Stale inputs:** the inputs are frozen snapshots. The 2026-10-29/30 VM
  evidence may be stale, and live R2/VM state is unavailable here.
- **Criterion mapping:** mapping the handoff criteria to gates is a reading
  of `FACTORY.md`. The decrypting audit stays the authority; this design
  does not weaken it.
- **Conflicts:** none of the files above is touched by
  `prep/practice4-checkpoint-carry-20261104` or `fix/registry-stale-history`
  (checked with `git diff --stat`). The registry JSON is only read.
