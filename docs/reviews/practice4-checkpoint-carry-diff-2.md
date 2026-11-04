# Goldfish diff review 2: practice4-checkpoint-carry

- **Reviewer personas:** Skeptical Architect (zoom_out) and Implementation Readiness Goldfish (`tools/egm/agents/zoom_out.md`, `tools/egm/agents/implementation_readiness.md`)
- **Standards:** `zoom-out-standard.md`, `implementation-readiness-standard.md`
- **Mode:** REVIEW
- **Target:** `git diff origin/factory-simplify...origin/claude/practice4-release-prep`. Head confirmed after fetch: `0e4ac165c0247bfb2c604199cd1130e9eacf3580` (commits 91fa8c6, 07df660, b97b0c2, 0e4ac16). Merge base: `e2c40b61`.
- **Design:** `docs/designs/practice4-checkpoint-carry.md` at head
- **Method:** read-only. I read every file with `git show` at the head, and I hashed fixture bytes from `git show`. I did not run the test suite.

## Verdict: PASS WITH NITS

Blocking finding #1 from diff review 1 is resolved:
- The design now says the ordering is procedural.
- A dormancy test was added. It tests exactly what the amended design claims, and its assertions really do discriminate.

No new blocking problem was found. The reason given for leaving nit #3 open does not hold, and nit #7 leaves a test time bomb that will go off in about two days. Both stay nits.

### Checks that passed
- **Head commit 0e4ac16 changes no production code, fixture or contract.** `git diff b97b0c2 0e4ac16 -- factory/ control/ tests/factory/fixtures/` is empty, and `factory/practice.py` is byte-identical to 07df660.
- **EXPECTED contract is unchanged:**
  - The `EXPECTED` literal parsed from `factory/practice.py` equals `json.load(factory/batches/b-plumbing-practice-4.json)`. It is still a separate literal, not loaded from the file it is compared to.
  - `carry_from.manifest_json` is byte-identical to `b-plumbing-practice-3.json`, and its sha256 equals `carry_from.policy.batch.manifest_sha256`.
  - Compared with -3, the only key-level differences are `carry_from` (added), `id` and `jobs` (the practice case only).
  - The pins match the design text: snapshot `d0f19598…856d`, release `cde6dc92…a7f4`, generation `b615c37c…d6d9`.
- **Retained fixtures match `provenance.json` byte for byte:**
  - All 15 files listed in `provenance.json` exist, no file in `tests/factory/fixtures/practice3-transfer/` is unlisted, and all 15 sha256 values match.
  - The `manifest_json` and `public_policy` in `source-public.json` equal the `carry_from` values.
  - In the source snapshot, the smoke operation has `retirement` set, `incident: None` and `output_generation = b615…`. `money.jobs` contains only `smoke`, so the fresh practice job is not blocked by the carried-liability check at `batch_holder.py:304-308`.
- **Finding 1 test is sound (`tests/factory/test_practice4_carry.py:134-145`):**
  - `holder.reserve` calls `enabled()` first (`factory/batch_holder.py:365`, which raises at `:55`). `HOLDER_ENABLED = False` (`:26`).
  - The test asserts `assertFalse(practice.active(...))` before it expects the refusal, so the `request_refused` comes from the opt-in gate and not from one of the other ~40 sites that raise the same message.
  - In this authored layout, an opt-in of `-4` would make `practice.active` raise rather than return False, because `matches` fails on the authored `carry_from` release path. So the `assertFalse` really does discriminate.
  - The no-side-effect checks (no target directory, no source `export.json`) match the elephant's response.
- **Design amendment (`docs/designs/practice4-checkpoint-carry.md:58-65`)** honestly limits the claim: "The test asserts only that practice cannot be reserved without the -4 opt-in". No guard was added to `_admit`, which is consistent with "add no generic practice framework".
- **Nits #2, #4, #5 and #6 are fixed as described.**
  - #2: comment at `tests/factory/test_boat_retirement.py:37-39`.
  - #4: stale-unit case at `test_practice4_carry.py:129-130`.
  - #5: AUTHORED line at `:5`.
  - #6: every file in `generation_manifest` is hashed at `:102-104`.
- **Murphy register edit is legitimate:**
  - `docs/murphy-register.md:89` changes only the mitigation text of `new-smoke-1`, adding a pointer to the inactive -4 continuation.
  - Status stays `open`, `Closed by` is unchanged, no row number was added and no other row was touched. This is allowed by ENGINEERING.md section 2.
  - `new-boat-stop-capture-1` (`:92`) stays open, as the design's Murphy scope requires.
- **Authored content is not presented as live evidence, with one partial exception (finding 2).** The runbook addition in `docs/designs/practice-run.md` and the design both say there is no live authority, worker, export or ledger mutation. Authored doubles in the tests are labelled.

## Findings

### 1. NIT: the dormancy test proves batch-wide dormancy, not anything about practice in particular
- **Evidence:**
  - The `enabled()` gate (`factory/batch_holder.py:48-55`) is the same for every job, so `test_practice_stays_dormant_without_current_opt_in` would pass unchanged with `'smoke'` in place of `'practice'`.
  - Once the operator sets `UNBUG_PRACTICE_BATCH=b-plumbing-practice-4` for the smoke continuation, which the runbook in `docs/designs/practice-run.md` requires, a fresh `practice` reservation becomes admissible. After that point the only barriers are `max_concurrency=1` and the runbook sentence.
  - The design (`:62-65`) states this correctly, but the phrase "dormant practice" at `:62` and the test name could be read as code-enforced dormancy of the job.
- **Fix:** rename the test to `test_whole_batch_refuses_without_current_opt_in`, or extend its comment with "once -4 is opted in for smoke, practice dormancy is procedural only". Optionally add the same wording to the runbook line "Do not reserve or dispatch the dormant practice job…".

### 2. NIT: the reason for leaving nit #3 open does not hold
- **Evidence:**
  - The elephant says (`docs/reviews/practice4-checkpoint-carry-diff-1.md:131`) that "Editing `provenance.json` would change a retained fixture hash". But `provenance.json` is not in its own `files` map (`tests/factory/fixtures/practice3-transfer/provenance.json:7-23`).
  - I searched the head for its sha256 prefix `870b2158be22c614` and found nothing, and no test or code reads the file. Editing it would change no pinned hash.
  - The second reason, "Neither this session nor the reviewer has that path", is weakened by the register itself. `docs/murphy-register.md:92` names `results/infrastructure/2026-11-04-plumbing-practice3/` as the retained public evidence location. That directory is not in the repo tree, but its name is recorded.
  - The substantive issue remains. `provenance.json:6` says "adaptations: None in these retained files", but `source-public.json`, `collection-public.json` and `publication-public.json` are JSON wrappers that combine several originals. The non-derivation parts of `collection-public.json`'s `journal` are not bound by any pin. This is a small case of an assembled artifact being labelled as unadapted.
- **Fix:** edit `provenance.json:5-6` to say "three *-public.json files are JSON projections: source-public = {snapshot, public_policy, manifest_json}; collection-public = {journal, generation_manifest}; publication-public = {current, outbox}; originals under results/infrastructure/2026-11-04-plumbing-practice3/ on the control VM". None of the 15 listed hashes changes. If the elephant still wants to leave `provenance.json` untouched, put the same sentence in the design's Tests section instead, and correct the stated reason in the review record.

### 3. NIT: nit #7's test time bomb is pre-existing, but it now goes off in about two days and the branch already edits the affected setUp
- **Evidence:**
  - `tests/factory/test_boat_retirement.py:74` calls `holder.reserve(...)` on the retained -3 contract with the real clock. `_admit` checks `datetime.now` against the 2026-11-07T00:00:00Z deadline (`factory/batch_holder.py:293`), and `practice.admission` requires more than 3600 s of headroom (`factory/practice.py`, `admission`).
  - The suite will therefore start failing at about 2026-11-06T23:00Z. Today is 2026-11-04.
  - The elephant's reason ("predates this branch") is accurate. However, this branch already modifies that `setUp` (`:37-42`), so the clock patch that `test_startup_smoke` uses (`for module in (holder, practice, job_authority): patch.object(module, 'datetime', Clock)`) is a three-line addition there.
  - The follow-up is recorded only in the review file.
  - The new -4 tests are not affected: `batch_transfer.py:209` and `batch_money.py:177` use `time.time`, which `test_practice4_carry.py:79` fixes.
- **Fix:** either add the `datetime` Clock patch for `holder` and `practice` in `RetirementTests.setUp`, or record the follow-up somewhere a later session will see it (a tracked task or a note in `docs/designs/practice-run.md`) before 2026-11-06.

### 4. NIT: the edited `new-smoke-1` mitigation keeps "run and passed before practice" next to the new pointer
- **Evidence:** `docs/murphy-register.md:89` still says the -3 smoke was "run and passed before practice". The same register (`:92`, `new-boat-stop-capture-1`) records that its lifecycle proof failed, which is why the -4 continuation exists. The new clause sits next to that wording. A reader could take "passed" as a completed qualification. The text is legitimate and closes no row, but it is ambiguous.
- **Fix:** change the wording to "…run before practice; lifecycle proof failed (`new-boat-stop-capture-1`); its prepared continuation is the imported smoke in `b-plumbing-practice-4` (inactive)".

### 5. NIT: the reason for leaving nit #8 open holds, though it is weak
- **Evidence:** `docs/reviews/practice4-checkpoint-carry-diff-1.md:138` keeps `factory/practice.py` byte-identical to the reviewed version. A comment would not change `EXPECTED`, so the stated risk is small. But the nit was optional, the duplication is required by `batch_transfer.predecessor`, and avoiding another contract-file change late in review is a reasonable call.
- **Fix:** none required. If `factory/practice.py` is touched for any other reason, add a one-line comment that the duplicated `carry_from` literal is required by `batch_transfer.predecessor` and must stay byte-exact.

The design's checklist is fully implemented, with no open design decision left to the implementer. The one remaining process step is the design's "one final full offline suite" on the exact landing tree. This review does not replace it.

---

## Elephant response

There was no blocking finding, and no nit is rejected. The fixes are in the commit after 229ba00. No production code, fixture byte or EXPECTED was changed.

1. **NIT: fixed.**
   - The test is renamed to `test_whole_batch_refuses_without_current_opt_in`. Its comment now says the gate is batch-wide, and that once -4 is opted in for smoke, practice dormancy and smoke-before-practice are procedural only.
   - The same wording was added to the design's test list and to the runbook line in `docs/designs/practice-run.md`.
2. **NIT: fixed in the design.** `provenance.json` is left byte-identical, so all 16 files in the fixture directory keep their recorded hashes, including the 15 listed in `provenance.json`.
   - `docs/designs/practice4-checkpoint-carry.md` (Tests section) now says which three `*-public.json` files are JSON projections, and of which keys.
   - It gives the Murphy-recorded evidence location, `results/infrastructure/2026-11-04-plumbing-practice3/`, noting that it is not in the repo tree.
   - It says the non-derivation journal parts are bound by no pin.
   - The wrong reason in the diff-1 response 3 is now corrected in place, with a note.
3. **NIT: fixed.**
   - `RetirementTests.setUp` now patches `datetime` in `batch_holder`, `practice` and `job_authority` with an AUTHORED `Clock` set to 2026-11-03T12:00Z. This is the same pattern `test_startup_smoke` uses.
   - Negative control, run ad hoc and not committed: with `Clock` moved to 2026-11-08, setUp fails with `MoneyWait: cleanup window unavailable`, so the patched clock is the admission gate.
   - The remaining real-time uses in `boat_lifecycle` are relative to the test's own `started` and markers, not to the batch deadline.
4. **NIT: fixed.** `new-smoke-1` now reads "…run before practice; lifecycle proof failed (`new-boat-stop-capture-1`); its prepared continuation is the imported smoke in `b-plumbing-practice-4` (…, inactive)". The row stays open, and no row number was added.
5. **NIT: no change.** As the reviewer accepted, `factory/practice.py` stays untouched.

Focused tests after these fixes, on Linux with Docker smoke unset:
- `test_practice4_carry`: 4 OK
- `test_boat_retirement`: 21 OK
- `test_practice_readiness`: 15 OK
- `test_startup_smoke`: 7 OK, 1 skip (Docker qualification)

The full suite result for the final head is recorded in PR #1.
