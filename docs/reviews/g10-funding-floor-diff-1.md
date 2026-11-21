# Diff review 1: g10-funding-floor (goldfish)

Reviewer: fresh general-purpose subagent, personas `zoom_out` and `implementation_readiness`, Mode: REVIEW, against
the commit message and PR description (no design doc: one-line fix). Reviewed `origin/main...HEAD` at d624a023.

**Verdict: PASS.** The change fixes what actually stopped attempts 4 and 5. It is one line in the place every caller goes through. Real spend still cannot pass the limit, and an attempt that truly has no money still stops.

## Blocking findings

None.

## Does the fix address the actual failure?

- **The run's own records match the PR.** The fixture shows both try-3 owner leases (bfa4c2fa, 47042c3f) requested at `funding_usd '1.710490600'`, which is the whole owner window, and both ended `denied`. A `denied` outcome after a lease was issued is the path where `reserve_invocation` raises (`factory/model_runtime.py` around line 600). The earlier gate-hold check runs before any lease exists, so it cannot have caused this.
- **The money mechanism is real.** A helper try runs on a fresh ledger whose limit is exactly the per-try authority, 14.2104906 (`factory/durable/helper_link.py:216-219`). The test copies that setup.
  - `invocation_headroom` subtracts the nine-place spend total, `usd(total)`, plus pending holds valued at the exact booked sum. When the total rounds up, headroom lands a sub-nanodollar below the owner window.
  - On main, `format(available, '.9f')` (`factory/budget.py:307`) rounded that back up to 1.710490600. `funded_maximum` passed it through unchanged, because a neuralwatt route is not a Claude or Codex profile.
  - `reserve_invocation` (`budget.py:179`) then refused it.
- **Rounding the quote down is the correct root fix, not a patch.**
  - A quote should never round up, and every caller goes through `available_invocation_funding`: model_runtime's admission and `run.helper_try_authority`.
  - A floored quote is always at or below the headroom that `reserve_invocation` computes from the same ledger, so the exact-fit refusal can no longer happen whatever the size of the residue.
  - The reservation check itself is unchanged, so money safety holds. A headroom of zero or less, including a sub-nanodollar positive one, now stops cleanly with `grant_insufficient` instead of hitting the router's `empty invocation funding` ValueError.
- **The PR's story of how the stop surfaced fits the code.** The owner's failure sets the tester's `role_cancel`. The helper returns `pack_stop` as a normal result, so the job counts as "completed ok". The case then raises it. So the diagnosis' "helper job completed ok" means a stop result came back, not a solved try.

## The diagnosis' three suggestions: none is an open bug this change should cover

1. **Interrupted windows booked as spend.** This did not happen in this run: total spend was $6.57 with $0 waste. The fixture's tester row is `estimated` with `estimated_gap_usd '0.000000000'`. Not this failure.
2. **G10 authority subtracted twice.** I found no double count. `call_limit` gives G10 calls the full limit, and `g10_money_headroom` and `holds_fit` pass `call_name=None`, which also gets the full limit.
3. **Measure need against limit minus actual spend.** This would be unsafe. Pending holds are committed money, and ignoring them would let concurrent calls go over the limit. I would reject it.

## Not verifiable from here (no VM access)

- That attempts 2 and 3 had grants of $28.50 and $27.15 in DBOS, and that `helper-tries/8533edbd…` is the early probe's try 1. Both fit the code and the fixture, and the later grant raises match the 11-21 lift-bounds approval, but I could not check the records. Worth one look on the VM if "a solved try was lost" still matters.

## Nits

- `g10_money_headroom` (`factory/run.py:1054`) and `holds_fit` (`run.py:2637`) still compare unrounded headroom with `>=` or `<`. A grant that fits exactly, less a sub-nanodollar, would still stop or fall back to serial. That outcome is conservative, a real shortfall, and very unlikely on case-side grants, so I would not block on it.
- `helper_try_authority`'s `available // per_try` can now count one try fewer when the headroom is exactly k tries less a sub-nanodollar. That is the honest count.
- `test_a_try_without_an_owner_window_still_stops` also passes on main. It is a guard, not a regression test, which is fine.

## What I read and ran

- **Read:**
  - Persona files and both standards.
  - The PR body and the diagnosis JSON, plus the fixture's structure and records.
  - `factory/budget.py` lines 100-315: `usd`, `reserve_invocation`, `attempt_limit`, `_g10_used`, `call_limit`, `reservation_booked`, `outstanding_reservations`, `invocation_headroom`, `available_invocation_funding`.
  - `model_runtime.py` admission (lines 520-620), `model_router.funded_maximum`, `model_call_gate.request_hold` (neuralwatt hold is 0.4846, far below the window).
  - `run.py`: `_author_try`, `helper_try_authority`, `hosted_try`, `g10_money_headroom`, `holds_fit`.
  - `exam_responder` owner failure path, `helper_link._try_context` and `_run_try`, `helpers.pack_stop`, `calibration.interruption_label`.
- **Protected files:** the diff touches only `factory/budget.py`, the new test and its fixture. `calibration.py`, `gate_state.py` and `bin/claims.py` are untouched.
- **Ran:**
  - The new test on the branch: 3 tests OK.
  - The same test in a scratch copy with main's `budget.py`: 16 errors on `grant_insufficient`, which is the PR's exact count. So it fails before the fix and passes after.
  - Eight related suites on the branch, all passing: budget, model_runtime, reservation_double_count, g10_authority_scope, calibration_owner_path, helper_g10_and_checks, router_cheap_maxima, case_budget.

## Author's response

- No blocking findings to fix.
- The "not verifiable" point was checked by the author on the control VM, read-only:
  - DBOS step inputs give `money_ceiling_usd_micros` 28504628 (attempt 2) and 27148658 (attempt 3), then 192970603 (attempts 4 and 5).
  - `helper-tries/8533edbd...` has mtime 09:14 and matches helper-ledger `L1 job 1 g10-early_probe` at 09:14:48.
  - `strong_calibrator/results.json` try 1 is the probe's solved try.
- Nits left as is. The case-side `>=` checks are conservative, and changing them is not needed for this failure.
