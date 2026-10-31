**PASS. 0 blockers, 5 majors, 8 nits.**

All three blockers from review 1 are fixed, and so are M1–M3 and N1–N4. None was rejected. All four of your blockers are named. Each is either resolved or deferred with a reason and an exact exam. Legacy cases retire and are never held. The five majors are about precision, and the zero-decision rule says the implementer should not have to choose any of them. Fix them before implementing.

---

# Goldfish design review: `docs/designs/stream-b-blocker-resolution.md` (revision 2, review 2)

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Worktree `t3-ded79ec5` at 9b9e5e0. The design and review-1 files are untracked.

I read:
- `docs/ENGINEERING.md` and review 1;
- `bin/boat-spend`, and `bin/boat-launch-guards.sh` (the `--check` call on line 33 and the `--finish` call on line 318);
- `factory/batch_service.py` (`collect`, `plan`) and `factory/batch_holder.py` (`_source`, `_post`, `reserve`, `collect`, `dispatch`);
- `factory/batch_status.py` around line 241, and `factory/registry.py` `atomic_json`;
- `stream-b-practice-blockers.md`, `stream-b-delayed-creation.md` and `isolation-timeouts.md`;
- the cleanup-qualification `report.md` and `observations.json`, and `batch-service-inventory-20261030.json`;
- `tests/factory/test_isolation_timeouts.py` lines 378–465 and `tests/factory/test_batch_service_d.py` lines 20–95;
- the Murphy rows 6, 17, 27, 28, 29, 35, 49 and 51.

## Verdict: PASS

## Prior findings

| Review-1 finding | Status in rev 2 |
|---|---|
| B1: one admission per home blocks the practice run | **Fixed.** Lines 78–83 and the table row on line 124 state plainly that after the first finish, all Boat admission on the home is refused, non-batch callers included. Relaunch, settlement and multi-worker exams are listed as blocked by the named "Boat attributed settlement" increment, not promised by this patch. |
| B2: four blockers not named; b275 in limbo | **Fixed.** The table (lines 117–126) names your four blockers, not the scanner's labels. b275's debt must be reconciled before the first new admission, and the evidence needed is named (provider non-creation, or a linked worker plus deletion completion and charges). Lines 131–133 admit the ledger cannot see it. |
| B3: "fail-closed" overclaim | **Fixed.** That wording is gone. Line 37 refuses any other reservation, whether reserved, finished or reconciled_expired. Line 40 says the TTL amounts are estimates, not a ceiling. |
| M1: superseded contracts and reversed tests | **Fixed.** Line 128 names the superseded clauses, and lines 181–183 name the two reversed tests and the file for the new tests. |
| M2: paths and exact behaviours | **Fixed.** The design now gives the paths, record fields, refusal record, refusal order, finish validation, conflict refusal, `atomic_json` under `batch_money.locked`, and the return value when diagnosis is off. |
| M3: Heilmeier gaps | **Fixed.** Lines 5–9 add a plain objective, the impact and a timeline. Line 108 adds the cost. |
| N1–N4 | **Fixed** at lines 130, 164, 159 and 175–176. |

## What is sound

- **Legacy cases retire, never hold.** Retirement happens before the `DIAGNOSIS_ENABLED` gate and before stored facts are read. It is terminal and is not a case pass. There is no import path. The frozen disposition covers the whole 2026-10-30 inventory and needs no provenance reconstruction.
- **The spending rule is now internally consistent.** Since any other row refuses, the old reserved-sum comparison drops away. Refusal skips the balance query for the first three refusal reasons and never writes the ledger.
- **The deferrals are honest.** USD 5 is kept. An empty fleet and a retired case are not claimed as cleanup proof. The old staged release is called obsolete.
- **Nothing speculative is added**: no new ledger, reset path, supervisor or adapter.
- **No Murphy rows are closed**, which is right for offline exclusion tests.

## Major

**M1: "Admissions stay disabled until then" (table, line 123) claims enforcement that no code provides.**
- `HOLDER_ENABLED=false` blocks only holder `reserve`.
- A manual `factory/launch.sh` on the control VM calls `boat-spend --check` against a ledger the observations show as missing. That check is admitted.
- Lines 131–133 admit this, but the table reads as if code enforces it.
- **Fix:** in the table, say the b275 condition is an operator entry condition. Code enforces it only for the holder path, not for non-batch Boat launches on that home.

**M2: The disposition schema drops case-key digests, but the text promises all digests.**
- Lines 62–63 promise "all retained card/archive digests", and line 99 says "preserves all digests".
- The schema on lines 172–174 keeps only `case`, `card_sha256`, `card_archive_sha256` and `files`.
- The source inventory also has `casekey` and `casekey_metadata.sha256`: 13 Mac and 16 VM records. None of those digests appears in `files`.
- The implementer has to choose. **Fix:** include `casekey` and `casekey_metadata` verbatim, or drop "all digests" and say case-key metadata is out of scope.

**M3: The error-message contract on lines 153–154 conflicts with existing code and gives no instruction.**
- The design says error messages never include exception or provider output.
- But `--finish` writes `balance_after_error=str(exc)` and prints `WARNING: actual spend unavailable: {exc}` (`bin/boat-spend:159-160`).
- And `main` exits with `boat-spend: {exc}` for every handled exception (`:173-174`), including `CalledProcessError` from `balance()`.
- **Fix:** say exactly which outputs change, and to what fixed labels. Or limit the rule to ledger-validation errors.

**M4: The runtime retirement record has no reader, so "operators get a terminal legacy disposition" (line 6) overstates what they see.**
- Nothing reads `retirements/<case>/<generation>.json`.
- `batch_status.py` maps a collected entry to `phase='stopped'` and only reads holder op incidents. A `reserve` refused in `_source` creates no op, so status never shows "retired".
- **Fix:** either have status report it (one lookup), or say the record is a durable file only and status is unchanged. The second is the lazier option and is fine.

**M5: The test plan leaves several exact contracts unchecked.**
Lines 94–100 and 181–187 omit:
- an existing target spend record kept byte-for-byte on refusal;
- a new refusal record with `allowed=false` and null balances;
- no `billing` call for the first three refusal reasons (the existing test checks only `list`);
- an accepted same-key replay not overwriting the record;
- a linked or non-regular retirement record refusing with `retirement conflict`.

Also, the existing tests `test_unbound_legacy_{known,null}_precollected_refuses_without_changes` (`test_batch_service_d.py:75-91`) assert `legacy_projection_unbound` and an unchanged journal. Name them as reversed or renamed, the same way the isolation tests are named.

## Nits

- **N1.** Line 41 still says "This is cumulative admission". Under refuse-any-other-row it is single-admission per home, and the table defers cumulative accounting. Reword it.
- **N2.** Line 34's "records without attributable actual charges" suggests a charged row could be skipped. Line 140 says no field is settlement authority. Drop the qualifier.
- **N3.** Line 51's "the batch directory" should name the `batch_money.locked(home, id)` state directory explicitly.
- **N4.** Murphy row 17 ("Boat wallet checks race across launchers", `bin/boat-spend:77`) is the row this change touches most directly. It is missing from the not-closed list on line 103. Name it, with the reason: offline billing double, not a real run.
- **N5.** Line 128 supersedes clauses in `stream-b-delayed-creation.md` and `isolation-timeouts.md` but does not say to mark those docs. The earlier delayed-creation design did that edit.
- **N6.** Table line 125 says "runtime source refusal" proves exclusion. The inventory cases have no journal entry or ACK and can never reach `_source`; the static disposition is what excludes them. `_source` only catches new collections that have `job_money` but no `diagnosis_state`. Say so, so readers don't over-read the runtime guard.
- **N7.** "Retirement" is already the holder's word for worker-deletion proof: the `op['retirement']` field and `_retirement()`. Line 19 already separates the two. A comment in `_source` would stop confusion.
- **N8.** Writing in `_source` breaks its "Read-only predecessor proof" docstring. Update the docstring, and say the legacy check runs after `_entry` verification, so no record is written for an unverified request.

## Scope honesty against your requirement

- **Cleanup cost guarantees:** deferred to live practice. The provider-contract or founder re-approval prerequisite is stated, and USD 5 is not relaxed. Honest.
- **Cumulative infrastructure accounting:** deferred to live practice after a named settlement increment. This patch only stops reuse of unknown liability, and the design says it freezes Boat after the first finish. Honest, apart from N1's wording.
- **Legacy provenance:** resolved by retirement, with the founder's 2026-10-30 approval recorded. Retire, never hold. Met.
- **Deployment qualification:** deferred to live practice, and the exact recordings are listed. Honest.
- No workers, paid calls, pushes or activation are allowed by the design. The holder and diagnosis switches stay off.

The design passes. Fix M1–M5 in a rev-2 touch-up before implementation, so the implementer has no choices left to make.

## Elephant disposition

PASS accepted. M1–M5 and N1–N8 accepted and clarified in the design before
implementation: operator-only b275 entry condition, case-key metadata retained,
fixed errors, file-only terminal disposition, full test contracts, precise
single-admission scope, row 17 and supersession notes. No finding rejected.

