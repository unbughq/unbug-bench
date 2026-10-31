# Goldfish diff review: `stream-b-delayed-creation` (diff review 1)

**Verdict: PASS.** No blocking or major finding is open. The scope is narrow: the expired-hold release is deleted from `bin/boat-spend`, with its tests and doc updates. This review closes no live blocker and no Murphy row, and none is claimed. Both activation gates stay false. This review does not prove the cumulative USD 5 bound, the cleanup supervisor, the b275 legacy disposition or deployment qualification.

**Setup:** Mode REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`. Worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, branch `t3/batch-service-control-vm`, diff `0c4eb3a..cf1654b` (HEAD). Two commits: `6154653` (code, tests, docs) and `cf1654b` (suite evidence only).

**Read:**
- `docs/ENGINEERING.md`, both persona files and the standard
- the design `docs/designs/stream-b-delayed-creation.md` and design reviews 1 and 2
- the full diff
- all of `bin/boat-spend` at HEAD
- `BoatTests` in `tests/factory/test_isolation_timeouts.py` and the `list.json` fixture
- `tests/run.py`
- the suite log and result JSON
- `docs/reports/stream-b-provider-contract-20261031/sources.json`

**Independently executed (read-only on the worktree):**
- re-hashed the suite log and the three provider pages;
- ran `tests/run.py --list`;
- exported HEAD to a temp directory (`git archive`) and ran `BoatTests` there: 5 tests, all OK;
- in a second temp export, put back the `0c4eb3a` `bin/boat-spend` and ran `BoatTests` again (mutation check);
- deleted both temp directories.

**Not done:** no worktree edits, workers, paid or network calls, secrets, VM access, push or subagents. I did not re-run the full suite.

---

## Blocker dispositions (design review 1), checked against the code

### B3 (inventory-based release kept in code): FIXED and verified
- **Deletion is complete.** Lines 112–124 are gone from `bin/boat-spend`: the `expired` list, the `list --all` query, the inactive-state set and the `reconciled_expired` update.
- **Nothing in the code produces `reconciled_expired` any more.** `git grep` outside reports and reviews finds it only in the two docs and the historical test.
- **The admission sum is unchanged:** `status == 'reserved'`, excluding the record's own key. So every reserved hold counts no matter what `expires_at` says.
- **Kept as before:** `expires_at` is still written as metadata, and `time` and `processes` are still used. The lock, the schema, same-record idempotency and `--finish` are unchanged.
- **No other consumers.** `boat-reservations` and `reconciled_at` appear only in `boat-spend`, the tests and the docs.
- **Mutation check:**
  - With the old `boat-spend`, `test_concurrent_admission_reserves_whole_envelope_and_finish_observes_account` fails with `AssertionError: 0 == 0` (balance $4.17171, estimate $3.1288). The old code released the hold on the saved empty, complete inventory (`hasMore:false`, `sandboxes:[]`).
  - With the new code, the test passes.
  - So the inverted test really catches the regression, using a saved inventory artifact.

### B1 (provider evidence) and B2 (legacy route): still resolved, and still documentation only
- The design text is unchanged from what design review 2 passed.
- The SHA256 of all three provider pages matches `sources.json`: create.md, billing.md and auto-stop.md all match.
- The diff closes no provider gap and no b275 disposition, and claims none. Correct.

## Major dispositions

**M1–M3: still resolved in the design text.**
- The design says `--check` does not enforce settled + holds + new ≤ USD 5.
- It says the wallet is not a cap.
- It marks the later section as a direction, not a plan.

**M4 (historical `reconciled_expired` compatibility): FIXED and verified** by `test_historical_expired_release_remains_compatible`, which asserts all three required behaviours:
1. **Excluded from reserved totals.** `next.json` is admitted. Each estimate is about 0.75 × balance, so if the historical entry were counted, the second admission would exceed the balance. The concurrent test shows this sizing does refuse when the hold counts.
2. **Same-record re-check refuses reuse** with `completed reservation cannot be reused`. The entry is byte-for-byte unchanged afterwards (`== old`), so admission does not reclassify it.
3. **Ordinary `--finish` sets the status to `finished`** and keeps `reconciled_at`. The design records this as intended (lines 44–48).

**M5 (deployment inventory of reserved holds): carried correctly as a pre-deployment condition.**
- Design lines 29–36 require, before deployment:
  - an inventory of historical `reconciled_expired` entries, with their disposition qualified;
  - an inventory of every `reserved` hold, its expiry, and any `new.*.pending` markers.
- This is parent/VM work. It is not done and not claimed, and it does not block merging.

## Points I verified specifically
- **Repeated refusal across processes, on retained receipts.** The concurrent test sets the admitted hold's `expires_at` to the past. Then two fresh `--check` subprocesses run on the saved `billing.json`. Each one:
  - exits non-zero;
  - leaves the ledger deep-equal to the injected ledger (same status and amount, no new hold);
  - rewrites the refused record with `allowed:false`.

  The fake CLI's call log shows no `list` call anywhere in the test, which proves the query itself is gone (N6 from design review 2).
- **Normal finish.** `--finish` still succeeds, with `actual_spend_usd=None`, `attribution=account_observation` and the IDs recorded. After that, the previously refused admission succeeds. So the retained hold was the only thing blocking it.
- **Unknown create.** `test_unknown_creation_stays_pending_and_does_not_finish_reservation` is unchanged. With the expiry release gone, a `new.N.pending` launch keeps its full hold indefinitely, failing closed as designed.
- **Old-design supersession (N5).** All four passages in `isolation-timeouts.md` are updated: item 6, the status schema (now "historical only"), the TTL-backstop sentence and the implementation-clarifications paragraph. No contradicting text remains.
- **Murphy register.** It is untouched (empty diff), and no row cites the deleted path. This matches the design: no closure.

## Evidence check
- The result JSON names commit `6154653e6ce2f779f92c204524738d8e89b3ad52`, the exact suite command, `exit_code: 0` and `"157 test scripts run; 0 failed."`.
- The log's SHA256 is `4e3e8298badd400c6d0003f461efceb543211cf37fbee30abcdd0b2a56623de6`, which matches the JSON.
- The log has 157 `== ` script headers and no `FAILED` or `Traceback` lines. Its last line is `157 test scripts run; 0 failed.`
- `tests/run.py --list` at HEAD lists 157 scripts, so the count matches.
- The log's `test_isolation_timeouts.py` section shows `Ran 22 tests ... OK`. That is 21 tests at base plus the one new test.
- `6154653..cf1654b` adds only the log and the JSON, so the suite run covers the final code exactly.
- Limitation: I cannot independently confirm that the log came from a real run rather than being written by hand. I re-ran only `BoatTests`, not the whole suite.

## Remaining findings

None is blocking and none is major.

- **N1 (nit, test clarity).** The historical test proves "excluded from totals" only through the sizing (0.75 × balance per estimate). No assertion pins down that a counted hold would have refused `next.json`. A one-line comment would make the sizing dependence explicit. Optional.
- **N2 (bookkeeping).** Commit `6154653` carries `Reviewed-by:` trailers for the two design reviews only. The merge commit must list design reviews 1 and 2 plus this diff review.
- **N3 (carried over).** The follow-up register candidate from design review 1's N3 is still open and out of scope. The Boat-path collection-failure message in `boat-launch-guards.sh` still recommends Hetzner cleanup.

## Scope of this PASS
- **Proved, for local accounting only:**
  - admission no longer releases expired holds by clock or by idle inventory;
  - fresh processes keep refusing, with the hold unchanged;
  - historical `reconciled_expired` entries are handled as the design specifies;
  - ordinary finish still releases the hold;
  - the full suite passed at the reviewed code commit.
- **Not proved, and still blocked:**
  - live provider cleanup or stop-state billing;
  - the cumulative USD 5 bound;
  - the cleanup supervisor and intent journal;
  - the b275 legacy disposition (needs fresh VM provenance);
  - the pre-deployment inventory of historical releases and reserved holds (M5);
  - closure of Murphy rows 6, 27, 28, 35 and 51 or any batch-service row.
- **Both activation gates stay false.** The design notes that non-batch `boat-spend` callers are not behind the holder gate. After deployment, retained holds can permanently reduce their admission capacity. That is intended fail-closed behaviour and is subject to the M5 inventory.

## Elephant response and handoff

PASS accepted. No blocking or major findings; no findings rejected. Optional N1 remains a test-clarity nit. N2: parent merge must list both design reviews and this diff review; this branch does not merge into factory-simplify. N3 remains the documented follow-up candidate.

Full suite: 157 scripts, zero failures, exit 0 at implementation commit 6154653e6ce2f779f92c204524738d8e89b3ad52. Suite record is stream-b-delayed-creation-suite-20261031T110001Z-ebc1b534.json with its retained log. Later commits contain evidence only.

No Murphy rows closed. Remaining: provider/legacy qualification and delayed-creation cleanup with cumulative USD 5 proof; pre-deployment inventory of historical releases and stale reserved holds; router provisioning and cheap plumbing profile preserving role restrictions; reviewed release/policy pins; account-2 attribution qualification. Both activation gates remain false. No workers, paid factory calls, VM mutation, push, main changes or merge into factory-simplify occurred.
