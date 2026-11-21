# A calibrator guard that rewrites the seeded data fails its own try

**What broke (2a7b2a-h4 and 5813be-h5, G10, 2026-11-21 ~04:30-05:00 UTC).** The strong calibrator's guard `db.sql`
inserted `reservation_item` rows and set `inventory_level.reserved_quantity` at install. contestant.md forbids
rewriting data. bench.py's baseline check after app start then failed every run with
`reset: Baseline changed during application startup`, plus `installation: Frozen installation identity changed` (twice
under the factory pool). `read_completed` called the batch "no valid verdict" (InvalidInfra), `run_validity.retry`
ran the identical batch again, then raised `InfrastructureExhausted`. The journal held 2 invalid attempts for that
guard, so the next engine attempt was refused before it ran. One bad submission stopped the case for good.
G6 already treats this exact reset error as a designed rejection: its raise-stock, change-kit and delete-x probes
get it and are recorded `rejected` (real evidence: `negative-controls` in `invalid-runs-real.json.gz`).

**Founder decision (2026-11-21).** Such a try counts as that try failing, not as infrastructure, and must not lock out
later G10 attempts.

**Change.**
- `run.seed_tampered(records)`: true only when every run's errors are drawn from that exact pair and include the reset
  one. Any other error in any run (a box fault, a timeout, an unrelated reset failure) keeps the batch infra.
- `run.try_checkpoint`: `checkpoint()` for a calibrator try. It builds the same command and identity. Its `read`
  returns a complete batch whose runs are all `seed_tampered` as evidence instead of raising, so the retry is not spent
  and the journal is cleared. `checkpoint()` is not edited, because every bench gate's identity hashes it.
- `calibrate` and `hosted_try` score with `try_checkpoint`. A tampered try is committed as a judged failure:
  `solved False, errors 0, checked_runs = runs, solved_runs 0, seed_data_changed True`. That gives
  `fix_failed_all_runs` / `demonstrated_failure`, and the series moves on to the next try.
- `fairness.review_attempts` (G16/G17) does not rerun such a try. A rerun would hit the same stop through `checkpoint()`.

**Why the guard, not the box.** The baseline check runs after the guard and the case's base `admin.sql` are installed.
G4 runs that same base scenario with the reference guard and passed before G10. The only new input is the guard.

**Not changed.** `calibration.py` (protected), `gate_state.py`, `bin/claims.py`, `bin/*` (bench files), and `checkpoint()`.

**Gate identity.** The runner hashes of G10, G16 and G17 change, and so does `calibration_identity` (it hashes
`calibrate`). G1-G9, G11 and G13-G15 are unchanged, checked by `gate_state.runner_inputs` before and after.
fairness.py is a dependency of G16/G17 only. `sealed_audit.delivery_contract()["run.py"]` changes, and its pin in
`tests/factory/test_sealed_audit.py` is updated. No case is sealed yet. A case between G10 and G11 at deploy time loses
its tries to the calibration-identity change (see the release-breaks-calibration-identity note), so deploy when no
case sits there.

**Deletes.** Nothing. The alternative, an edit to `checkpoint()` or `run_validity.retry`, would change every bench
gate's identity.

## Tests
- `test_invalid_runs.test_2a7b2a_seed_tamper_fails_the_try_and_the_next_try_runs`: the real reset-failed S13 record with
  G6's real raise-stock reset error and the installation error twice, through the real `read_completed` and retry
  journal. Try 1 is scored failed, there is one bench batch per try, try 2 runs and solves, the journal shows 0 invalid
  attempts, and the same guard is not refused again. On the old `checkpoint()` path it raises InfrastructureExhausted.
- `test_invalid_runs.test_unrelated_reset_failure_in_a_try_is_still_infrastructure`: the real `reset-invalid` batch
  is retried once, then exhausted and refused. A tamper run that also carries a traffic error stays infra.
- `test_invalid_runs.test_seed_tamper_is_bench_and_g6_evidence`: the matched strings are bench.py's own, G6's rejected
  probes match, and mixed or empty batches do not.
- `test_fairness.test_a_seed_tamper_try_is_reviewed_as_failed_and_not_rerun`: G17 reviews the try without a rerun.
  It fails on the old fairness.py.

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-g10-tamper-try-1`: a calibrator guard that rewrites seeded data at install makes every run invalid. G10 books it
  as `InfrastructureExhausted(InvalidInfra)`, and the retry journal refuses every later attempt on that guard, so the
  case stops for good (2a7b2a-h4, 5813be-h5). Closed by
  `tests/factory/test_invalid_runs.py::InvalidRunsTests::test_2a7b2a_seed_tamper_fails_the_try_and_the_next_try_runs`.
