# G11 side by side

**Problem.** G11 checks every tester pass one after another: one `fake-pass-check` over all passes (a
baseline, then per pass 5 stress runs and 1 normal run), then per pass a 5-run case re-run. A bench run
is about 4.5 minutes, so each pass costs about 32 minutes (8acb5c: 33) and a case with 4 passes about
2 h 15, while G3's extra bench slots sit idle after G10 joins.

**Change.** `run.evaluate_gate` (placement only, not in any fingerprint) gives G11 `g11_side_by_side`
when `g11_slots` finds two or more usable slots: slot 0 plus the extra slots prepared now
(`bench.factory_slot_ready`, not the card's high-water mark), capped by `bench.factory_memory_fits`, and
only for isolated inventory services. It runs the guardless baseline once on slot 0 (as the serial
command does), then each pass's one-guard `fake-pass-check` with the baseline's table list
(`--traffic-tables`, new; it skips the baseline traffic runs) and each pass's `g11-rerun`, every job
whole on one slot (G5's key pattern: own ports, database, results and lock). All jobs join before
anything is read; the report keeps the serial shape and results and errors are taken in serial order.
Otherwise the serial path is unchanged. **Deletes:** nothing; the serial path stays as the fallback.

**Tests.** `tests/factory/test_g11_side_by_side.py`: stub bench with a different baseline per slot;
jobs overlap within the slot cap; gate record and retained report byte-equal to serial; one baseline;
a shrunk slot set (high-water 4, 2 ready) uses slots 0 and 1 only; first failure in guard order raised;
slot choice absent from `gate_state.runner_inputs("G11")`. `tests/bench/test_fake_pass_baseline.py`:
`--traffic-tables` skips the baseline runs and is reported. **Murphy rows:** none (a speed change; no
known failure row; `docs/murphy-register.md` is not on this branch).

**Verdict risks.** Re-runs and scans run whole on one slot instead of spread over `bench_workers`
(the G5 precedent; same seeds and counts). Extra slots have their own seed IDs. A failed job does not
cancel the others, so later re-runs that the serial path would not have reached may charge their
infra-retry rows. G11's identity changes once (`g11`, `fake_pass_report`, `bin/fake-pass-check`).
