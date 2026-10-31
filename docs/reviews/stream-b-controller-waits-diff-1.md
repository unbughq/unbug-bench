# Goldfish Diff Review — `stream-b-controller-waits` (02f7495..2127f62)

## Verdict: **PASS** — no blocking findings.

Reviewed `docs/designs/stream-b-controller-waits.md` against `docs/designs/stream-b-controller-waits.md`, `implementation-readiness-standard.md`, and the code diff in `factory/batch_holder.py`, `factory/key_holder.py`, `tests/factory/test_batch_holder.py`. I independently verified every finding and response in `docs/reviews/stream-b-controller-waits-design-1.md`.

## Independent verification of the three Majors

1. **`unbounded_route` exclusion (design-review #1) — CONFIRMED FIXED.** `_wait_due` (batch_holder.py:405) requires `wait['reason'] not in REASONS - {'unbounded_route'}`. `REASONS` includes `unbounded_route` (model_router.py:40), so it is excluded. Test `test_invalid_waits_never_reserve` variant `dict(reason='unbounded_route')` proves refusal.

2. **Per-tick full-collection re-hash (design-review #2) — CONFIRMED FIXED.** `schedule_waits` (batch_holder.py:424-426) reads only the frozen scorecard via `service._json` (no `_snapshot`, no hash) and calls `_wait_due` as a skip-only filter *before* `reserve`. `reserve`→`_source`→`_entry`→`_snapshot` runs the full proof only for due candidates, under the lock. Test `test_tick_future_due_restart_and_single_successor` asserts `snapshot.assert_not_called()` across two future ticks, and `test_filter_cannot_authorize_tampered_card_or_changed_predicate` proves the filter never admits (tampered reason still refused by `_source`).

3. **Reserve predicate interface (design-review #3) — CONFIRMED FIXED.** Signature is `reserve(..., *, provider_wait=False)`. Check order specified: `identity in ops` branch refuses (not repairs, batch_holder.py:190-191), null source refused before lock (line 184), predecessor incident re-checked under lock (line 203), `_wait_due` after `_source` before `advance_locked` (line 204). Exception set `(OSError, ValueError, KeyError, TypeError, AttributeError)` matches `reconcile`'s set; scan-level failure raises to `batch_tick`'s existing `'batch scan refused'` handler (no new label added).

## Crash/replay safety — verified sound

`reserve` persists `money.json` (with the `advance_locked` mutation) before `configuration`, `reservations.json`, and `journal.json`. On replay after such a crash, `identity not in ops` (no reservation), then line 205 sees `row['authority']['source_generation'] == source_generation` (already advanced) and skips `advance_locked`; line 207's `elif` guard passes because `ack['authority']['source_generation']` is the predecessor's `None` (first generation). `authorize_locked` returns the *same* authority, so the successor is recreated with the same `operation_id`, `reservation_id` and hold, with no second money advance. `advance_locked` itself is additionally guarded by `source_generation in row['sources']` (batch_money.py:296). Test `test_money_advance_reservation_journal_and_lost_reply_crashes` exercises four boundaries (`configuration`, `reservations.json`, `journal.json`, `reply`) and asserts `sources == [None, card['sha256']]` the money is not double-advanced, and journal operations reconcile.

## Due-time and proof checks — verified

- `_wait_due`: canonical v4 UUID (`version != 4 or str(identity) != wait['wait_id']`), `reason` enum minus `unbounded_route`, `evidence in ('denied_before_work','interrupted')`, both times parsed with `money.deadline` (enforces UTC offset 0), `batch_deadline` equals the frozen manifest deadline, and `retry <= now < end`.
- Projection shape matches `run.py:write_provider_wait` exactly (`wait_id`, `reason`, `retry_after`, `role`, `route`, `account`, `evidence`, `batch_deadline`) via `model_router.utc` → UTC `Z` strings. Confirmed readable by `money.deadline`.
- `_source` (batch_holder.py:140-158) re-verifies ACK, predecessor output/authority/retirement, current pointer, acknowledged outbox, and the verified immutable collection (`_snapshot` hashes every member) before admission.

## Tick integration — verified

`batch_tick` (key_holder.py:448-449) inserts `(None, batch_holder.schedule_waits)` between `reconcile` and `orphaned`. `schedule_waits` returns `[]`, so it never spawns a child; the newly reserved pending operation is discovered and dispatched by the next tick's `reconcile`. Test `test_tick_future_due_restart_and_single_successor` proves the full wire-up with empty process maps (modelling a holder restart) and only process spawning faked.

## Gate-off scope and Murphy no-closure — verified

- `HOLDER_ENABLED = False` (batch_holder.py:26) and `DIAGNOSIS_ENABLED = False` (batch_service.py:21); both gates untouched by the diff.
- `docs/murphy-register.md` not modified; rows 2, 11, 47 remain `open`, matching the "advance but do not close" claim.

## Suite result

`docs/reviews/stream-b-controller-waits-suite-20261031T100822Z-8ca7b263.json` records head `8ba8d83`, exit 0, "156 test scripts run; 0 failed" — consistent with the log tail. Only documentation was committed after `8ba8d83` (design + review + suite records); the implementation SHA tested is the one reviewed. The single uncommitted removal of a trailing blank line in the design-review report is cosmetic and harmless.

## Nits (optional)

- **Nit** — `batch_holder.py:408`: the predicate contains the redundant clause `or retry >= end` (already implied by the preceding `not retry <= ... < end`). Remove for clarity; no behavioral change.
- **Nit** — `batch_holder.py:411-430` `schedule_waits` loops `ops.values()` including operations it will immediately `continue` on (state/incident/retirement/successor checks), which is a full scan per tick. Acceptable at current scale; revisit only if operation counts grow.

No edits, tests, worker launches, secret access, paid model probes, pushes, merges, or delegation were performed.

---

Skipped/not checked: I did not re-run the suite (the committed result is authoritative) nor trace the `credential_expiring` re-admission path live (offline tests only, as the design states). Risk to note: the scheduler does not bound cumulative infrastructure cost across successors — this is an explicitly deferred activation blocker, not a defect in this increment.

## Elephant response

PASS accepted. No blocking findings and none rejected. The optional redundant deadline comparison remains as an explicit bound; the simple operation scan remains appropriate for this gated increment. No runtime edits after tested implementation 8ba8d83. The review's opening reason wording describes the rejection branch: admission requires membership in REASONS minus unbounded_route. Projection validation checks the scheduling fields, not exact equality of all transport-hint fields.

Reviewer: OpenCode openrouter/~deepseek/deepseek-pro-latest, fresh T3 delegate. Requested Claude claude-opus-5-5 diff review failed before a report with: API Error: Can't reach the API server — check your internet or DNS (ENOTFOUND). The user-authorized fallback supplied this final report. Only the final report and this response are retained.

Full suite: 156 scripts, 0 failed; log and SHA256 in stream-b-controller-waits-suite-20261031T100822Z-8ca7b263.json. No Murphy rows closed. Controller scheduling is implemented but remains gated. Launch still requires delayed-creation cleanup and cumulative infrastructure cost proof, legacy launch ownership resolution, router provisioning, a cheap plumbing profile compatible with production role restrictions, fresh reviewed policy/release pins and the separate account-2 attribution check. Expect about three further increments (cleanup/legacy ownership; router/profile; final release/policy and deployment qualification), potentially one more if provider creation semantics cannot establish the required bound. No workers launched, paid factory calls, push or merge into factory-simplify.
