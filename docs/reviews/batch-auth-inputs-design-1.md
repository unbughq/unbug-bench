**FAIL**: 2 blockers, 6 majors, 5 nits. The scope is right. It keeps the single launch path, adds no legacy import, does not overstate what it proves, and leaves all three Murphy rows open. But the checkpoint check as written can never accept a valid checkpoint, and the one change to launch behaviour (the empty-input guard) does not say which paths it checks. I wrote, committed and ran nothing, and I ran no tests. The text below can be saved verbatim as `docs/reviews/batch-auth-inputs-design-1.md`.

---

# Review: batch-auth-inputs design 1. FAIL (2 blockers, 6 majors, 5 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`.

**Code read:**
- `factory/batch_holder.py`: `_source` 140, `_post` 160, `reserve` 177, `source_directory` 536, `dispatch` 690, CLI 775–795
- `factory/batch_money.py`: `locked` 108, `authorize_locked` 271, `advance_locked` 290
- `factory/batch_service.py`: `_load` 90, `_snapshot` 181, `collect` 207
- `factory/batch.py`: `restore_inventory` 35, `bind` 136
- `tools/migrate-legacy-checkpoints.py`: `complete` 270, `existing` 296, `run`, `estimate`, `main`
- `docs/reports/batch-service-migration-plan-20261030.json`: 64 entries (29 checkpoint, 17 final, 16 rewrap_key, 1 divergent_checkpoint, 1 card_bound_absent)
- Murphy rows `new-single-path-1`, `new-batch-service-1` and `new-batch-service-2`

**Scope accepted:** the real migrated store is absent, the rows stay open, and the founder migration is outside this change.

## Blockers

**B1. The checkpoint check can never pass a valid checkpoint (lines 26–28).**
- The design says the `input` operation "exercises `_source` for a checkpoint … and runs `authorize_locked` on an in-memory copy of money state".
- In `reserve`, a checkpoint whose generation is newer than the job's current source first goes through `money.advance_locked(state, …, ack)` (holder 199–200). Only after that does it reach `authorize_locked`.
- `authorize_locked` raises `MoneyWait` whenever `row['authority']['source_generation'] != source_generation` (money 276–277).
- So running `_source` and then `authorize_locked` as written reports every real successor checkpoint as ineligible. It also skips the `row['sources'][-2]` freshness check (holder 201–202).
- **Fix:** don't rebuild the sequence by hand. Pull the read-only part of `reserve` out into one function, from the `_source` call through `authorize_locked`, plus the new guard. `reserve` calls it on the locked state. The qualifier calls it on a `deepcopy`. Then the two cannot drift, and the qualifier exercises the real reservation logic.
- **Test:** an authored successor checkpoint (the setup that `test_lifecycle_status_ack_retirement_source_and_replay` already uses) qualifies as eligible. The same checkpoint with a stale `sources[-2]` is refused.

**B2. The guard does not say which paths it checks (lines 18–20).** This breaks the Zero-Decision Rule. There are two `sealed`/`generations` namespaces, and the design names neither.
- **Holder side:** `home/batches/<id>/generations/<case>/` and `home/batches/<id>/current/<case>.json`.
- **Sealed side:**
  - `root/sealed/` and `<git-common-dir>/../sealed/` (`restore_inventory`, batch 37–42);
  - the migration output root `sealed/generations/<case>/` (plan `output_root`).
- **"Same-name sealed files" has no name set.** A prefix glob on `case-<batch>-job1` also matches `case-<batch>-job10`.
- **Fix:**
  - List the exact directories.
  - Define the name set as `launch_manifest.collection_files(case)`, which `collect` already uses. Do not write a new pattern.
  - State the existence test: `os.lstat` succeeds, so dangling symlinks count.
  - Say whether an empty `generations/<case>/` parent counts. `collect` can leave one behind after a crash (service 213–214).

## Majors

**M1. Where the guard goes, and when replay is allowed, is unclear (lines 17–21).**
- **Reserve:** "Before money writes" is ambiguous. The replay branch writes too (`_save` at holder 191). Say whether the guard runs before or after the `identity in ops` branch.
- **"Until output exists" is undefined.** It could mean `op['output_generation'] is not None`, or that the filesystem shows a generation. Pick one.
- **Dispatch:** "Dispatch POST validation" means `_post`. `_post` is shared with `source_directory`, which the CLI `restore-check` and path-printing commands also call (holder 786). A guard in `_post` makes those commands refuse for an empty operation once collection has created its generation directory. Say whether the guard goes in `_post` or only in `dispatch`, and whether the `source_directory` change is intended.

**M2. The new hazard has no Murphy row (lines 43–44, 57–61).**
- The design fixes a real hazard: an empty input can be reserved in a namespace that already holds case evidence. It does not register that hazard.
- ENGINEERING §2: every design names the rows it closes, and a new failure gets a `new-<topic>-<n>` row before it is fixed.
- **Fix:** add `new-batch-auth-inputs-1` for the empty-input collision. Close it with the real-artifact collision test, or say why that test does not prove the row.

**M3. "Reads existing journals without creating directories" has no mechanism (line 26).**
- Every existing read path takes `money.locked`. That runs `mkdir(parents=True)` and opens `lock` with `'a'`, which creates the file (money 110–112).
- The qualifier needs its own read path. One option: if the batch directory exists, open `lock` with `O_RDONLY|O_NOFOLLOW`, take a shared `flock`, then call `_operations`/`load_locked`.
- **Missing state needs explicit report labels:**
  - no batch directory;
  - no journal;
  - `_source` raising `KeyError` because there is no ack.
- Without labels, the implementer has to invent this behaviour.

**M4. The qualifier has no test plan, and the test artifacts are unnamed (lines 48–51).**
- **Unnamed artifacts:** "Retained real encrypted artifacts" doesn't say which ones. Name the files, for example the opaque envelope from `test_batch_service` that `test_batch_holder` already uses.
- **No tests listed for `tools/qualify-batch-inputs.py`.** At minimum:
  - **Migrated store missing:** a missing store root or a missing per-row output fails. It is never skipped. Note that `existing` returns `None` here, so the qualifier must treat `None` as failure.
  - **Damaged output:** an output with a wrong byte hash or a changed `original-card.json` binding fails.
  - **Report contents:** the `divergent_checkpoint` row and the `card_bound_absent` row are counted.
  - **Overall status:** VM unwrap and R2 always show as unverified and block overall qualification.
  - **Write check:** directory listings and modification times are unchanged before and after a run.
  - **Eligible checkpoint (`input`):** see B1.
  - **Collision refused (`input`):** an empty input with an existing collision is refused, which is the M1 case.
- **Unnamed existing tests:** "Existing holder tests cover…" should name them. For example: `test_lifecycle_status_ack_retirement_source_and_replay`, `test_wrong_authority_and_pointer_alone_never_grant` and `test_two_sources_never_return_to_old_generation`.

**M5. The VM inspection and the committed evidence are unspecified (lines 52–53).**
- "Inspect the actual VM store" doesn't say how. Specify:
  - the command and transport (a read-only SSH listing, or the qualifier run on the VM);
  - the paths: `vm_root` `/home/user/unbug-bench/sealed` and the control home;
  - the output file, for example `docs/reports/batch-auth-inputs-<date>.json`, and its public fields.
- Without this, "commit public evidence" can't be checked.

**M6. Heilmeier gaps.**
- **Objectives:** the problem and change sections are written in internal shorthand ("holder `_source` proof", "ACK", "acknowledged outbox", `authorize_locked`). There is no plain-language statement of the goal. Something like this would do: "before any practice batch runs, prove which inputs may legally start a case, and prove that the migrated store is intact or absent."
- **Missing sections:** Impact (what this unblocks, and for whom), Risks/payoffs, Cost and Timeline.
- **Exams:** stated only as test activity. A mid-term exam would be the guard landing with its tests. The final exam would be the evidence report committed and the suite passing.

## Zoom-out notes (folded into the majors where relevant)

- **`migrated-store` should be a read-only mode of `tools/migrate-legacy-checkpoints.py`, not a new file.**
  - The migration tool already parses `--plan`/`--plan-sha256`, owns `existing`/`complete`, and has a dry-run path (`estimate`) that walks every row through `existing`.
  - A `--qualify` flag avoids copying the plan loading and digest checks into a second tool.
  - The `input` operation could then be a subcommand of `factory/batch_holder.py`'s CLI next to the B1 function, or stay in a small new tool. Either is fine once B1 holds.
  - If both stay in one new file, say why.
- **The `input` operation is fine to keep, though its result is already known today.** With no store present, it will report "no eligible checkpoint". It still earns its place because it is the admission check the practice batch needs. Keep it minimal.

## Nits

- **N1. Deletions (lines 42–44)** removes an *assumption* and deletes no code. Say plainly "deletes nothing", as ENGINEERING §1 step 2 expects.
- **N2. Symlinked `manifest.json`/`migration.json`.** `complete` reads both with `read_text()`, which follows symlinks, and `manifest.json` is not in its own `files` list. A local integrity qualifier should refuse a symlinked `manifest.json` or `migration.json`. Either note this as an accepted limit or add a `_regular`-style open.
- **N3. "Two differing checkpoint variants" (line 36).** In the plan these are one `checkpoint` row and one `divergent_checkpoint` row for `case-20261017T125556Z-18681d`. Name the case and the kinds so the report can be checked against the plan.
- **N4. Overall result.** State the exit code and the overall field for "local integrity passed, VM/R2 unverified", so callers can't read a partial success as qualification.
- **N5. Holder gate (line 30).** "No holder gate is enabled": add that the qualifier never imports with or flips `HOLDER_ENABLED`, and calls internals directly. `reserve`/`dispatch` refuse through `enabled()` while the gate is off.

## What holds

- One launch path is kept. No legacy import, and no fabricated bindings.
- Input qualification is kept separate from activation, account and cleanup proof.
- A missing store is a failure, never a skip.
- VM unwrap and R2 stay explicitly unverified and block overall qualification.
- No identity is read and no plaintext is decrypted.
- The three target rows correctly stay open while real migrated outputs are absent.

**Verdict: FAIL.** Fix B1 and B2, and resolve M1–M6. Then a fresh design review is needed.


## Author disposition
B1/B2 and M1–M6 accepted. Revised design shares admission including advance/freshness, enumerates exact paths and replay boundaries, specifies read-only locking/reports/tests/evidence, adds the Murphy hazard and Heilmeier sections. Nits addressed; migrated qualification now extends existing migration CLI. No blocker rejected. Pending fresh review.
