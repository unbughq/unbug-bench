**Goldfish diff review: practice fresh admission (`b-plumbing-practice-2`), diff round 1 of 2**

Mode: REVIEW, read-only. Personas: `tools/egm/agents/zoom_out.md` and `tools/egm/agents/implementation_readiness.md`. Standards: `zoom-out-standard.md` and `implementation-readiness-standard.md`. Step 2 was skipped under the parent-approved small-fix exception, so I reviewed against the commit message of 26ec10a, `docs/designs/practice-run.md` and `docs/reports/practice-fresh-admission.md`.

## Verdict: PASS

There are no blockers and no majors. Four nits follow; all are optional.

## Scope check (zoom-out)

- **Source commit 26ec10a** touches only what the requirement names:
  - validator: `factory/practice.py`, where `BATCH`, `EXPECTED.id` and `EXPECTED.jobs.practice.case` changed;
  - manifest, renamed with only the `id` and `case` lines changed (93% similarity);
  - preflight drop-in: `factory/practice_preflight.py` `DROPIN`;
  - cleanup unit: `control/unbug-practice-cleanup@.service`;
  - run plan: `docs/designs/practice-run.md` step 6 and the closing paragraph;
  - one new test, plus a fixture change so `practice_policy(record=None)` builds its manifest path from `record["id"]`.
- **No mechanism added.** There is no new retry, admission, reset or migration path, no new ledger, and no other source change. Nothing is over-engineered. This is the smallest change that does the job.
- **Commit ef6279b** adds only report and suite records. I confirmed this with `git diff 26ec10a ef6279b`: three files, all under `docs/reports/`.
- **Old ID gone from code.** Searching the repo for `b-plumbing-practice` outside `docs/` finds it only in the new test's old-record fixture. Every other hit is in historical docs: `practice-readiness.md`, the 20261102 run report and earlier reviews.
- **Murphy register.** It is untouched and no rows are closed, which matches the claim.

## Requirement trace (readiness)

| Requirement | Evidence |
|---|---|
| Exact rename in all four places | Diff lines above. The test asserts `practice.BATCH`, the manifest `case`, `DROPIN` and the unit file's text all agree. |
| Old ID cannot be admitted | `practice.active` returns False when the policy `batch.id` differs from `BATCH`, so `holder.enabled` raises `request_refused` (`factory/batch_holder.py:37-43`). `_admit` checks `matches` only for the new ID. `money.authorize` raises `MoneyWait` for any record with `practice_admission` (`factory/batch_money.py:160`). `MoneyWait` subclasses `ValueError`. |
| Regression authenticates the old manifest | The test writes the old record at `factory/batches/b-plumbing-practice.json`, pins its sha in the policy and source-manifest, and asserts `money.manifest(policy, root) == old`. So it is not a missing-file refusal. |
| Holder and legacy refusal under both environment values | `subTest` loops over the old ID and `practice.BATCH` with `HOLDER_ENABLED=False`, asserting `active` is False and that `reserve` and `money.authorize` raise. |
| The test fails if the old ID becomes admissible again | If `BATCH` reverted, the first `assertEqual` fails. If `active` accepted the old ID, `matches(old)` would be False and `active` would raise inside `assertFalse`, so the test errors. Both are caught. |
| Earlier terminal state keeps its bytes | A failed operation is seeded through real `reserve`/`record_exit` with `HOLDER_ENABLED=True` from the HolderTests fixture. The test then snapshots every file under `home`, attempts the refusals, and compares the bytes. |
| Limits unchanged | The test pins `money_limit_usd`, `requested_total_usd`, the `practice_admission` baseline of 0 and increment of 19.99, `--max-spend 5` and `--ttl-hours 1`. The manifest diff confirms nothing else moved. |
| $0 earlier spend is recorded | `docs/reports/practice-run-20261102.md:12-13,35,45,62,79,95` record model $0 and infrastructure $0, no worker and no pending creation. Line 132 records router paid total $0. The report correctly limits the carry-over to this one zero-spend fact. |

## Evidence I checked

- I ran `tests/factory/test_practice_readiness.py` offline in the worktree: 15 tests, OK. I did not rerun the holder and money scripts or the full suite (suite reruns were out of scope). Those results come from the record.
- Tree of 26ec10a is `4d4dc878…`, which matches `source_tree` in the JSON.
- The `.log.gz` sha256 is `fdfb9cce…` and the uncompressed log's sha256 is `442db400…`. Both match the JSON.
- The log tail reads `176 test scripts run; 0 failed.`, which matches `test_scripts`/`failed_scripts`. The command recorded is the shared-lock `lockf` form.

## Findings

**Nit 1: the old ID now passes through `key_holder.batch_request` instead of being refused there.**
- Scope: `factory/key_holder.py:474-481` (unchanged code whose behaviour changes because of the rename), and the test's legacy coverage.
- Before the rename, an old-ID policy matched `practice.BATCH` and got `request_refused` straight from `batch_request`. Now `batch_request` returns `None` for it, and the request falls through to the legacy launch path.
- On that path, the code-fingerprint check (`fingerprint(ROOT) != policy['code_sha256']`) refuses any old policy before the `boat-call list` inventory call. Failing that, the old manifest is gone from the release, so manifest authentication refuses. Failing that, `money.authorize` refuses with `money_wait`. No worker and no money are reachable, so this is not a gap.
- However:
  - the test calls `money.authorize` directly rather than going through `batch_request`;
  - the public reply on this path is `money_wait`, which is a wait-class error, not `request_refused`.
- Option: add `assertIsNone(key_holder.batch_request(old_policy, {...launch...}))` to pin the fall-through. Or reword the report so it says the legacy path's last refusal is a `money_wait` from authorize, behind the fingerprint and manifest gates.

**Nit 2: `assertRaises(ValueError)` accepts any refusal.**
- Scope: test lines 117-120.
- `MoneyWait` is a `ValueError`, so any refusal for an unrelated reason (deadline, a fixture problem) would also pass.
- Option: `assertRaisesRegex(ValueError, 'request_refused')` for `reserve`, and `assertRaisesRegex(money.MoneyWait, 'money_wait')` for `authorize`.

**Nit 3: the seeded terminal state is not shaped like the real one.**
- Scope: test lines 109-111.
- The real old operation ended through a `preflight_refused` incident. The test seeds an ordinary `record_exit(..., 1)` failure instead.
- Byte preservation is still proved for a real holder layout, so this is acceptable. Ideally the test would note the difference, or seed with the incident.

**Nit 4: wording in docs.**
- `docs/designs/practice-readiness.md` still describes the old ID with no pointer to the change. It is historical, but one "superseded by practice-run.md (2026-11-02)" line would help.
- The first section of `practice-fresh-admission.md` still says "Full-suite and fresh review records follow", and the Validation section right below it already has them. This is harmless.

## Out of scope, noted only

- `practice-run-20261102.md:131` records a Boat balance of $4.17157, which is below the $5 infrastructure ceiling. Live checks govern that, not this diff.
- Deployment and repinning stay as a stated pre-launch step: "Merge and repin before deployment".

## Constraints honoured

I made no edits, commits, pushes, provider, network or model calls, and I did not delegate. The only command I executed was the offline targeted test.
