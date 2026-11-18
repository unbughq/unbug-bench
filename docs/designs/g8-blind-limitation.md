# G8: blind-step routes the contestant controls are a known limitation

## Problem

On 2026-11-18 G8 and the new pre-review rejected fairness on several hand-built cases (22e434,
04d417, 1108c, 1110a) for the same bench-wide points about blind steps:

1. The bench's blind switch (`UNBUG_MONITOR_BLIND` env in `bin/bench.py`, `/data/monitor-blind` written
   by `bin/land`, read by bench-supplied services such as `projects/marketplace/service.py`) is
   visible on the contestant's box before the blind step, which reviewers call an advance hint.
2. A blind step does not blind "every contestant monitoring route" (`reviewer.md`), because the
   contestant can still read orders as `medusa_app`, through the admin API with the seeded login,
   or through the nested Docker engine.

A case author cannot fix either: the switch is bench code, and the contestant has root on the box.

## Decision (founder, 2026-11-18: "Yes, known limitation")

`reviewer-keys.md` gains a "Known bench limitations" section: G8 does not fail fairness for those
routes or for the bench's own switch. It still fails a blind step that leaves open a monitoring
route the case or bench hands the contestant (`arm_monitor`, a `/monitor` view, and the box's own
checker `bench_checker`, which `bin/bench.py` creates with BYPASSRLS), and still fails a case whose
own material hints at the blind step. `builder.md` tells builders to blind `bench_checker` too.

## Not changed

- No bench code. Hiding the switch or the routes would change the contestant box and every sealed
  case's calibration; that is a later bench change, if ever.
- `reviewer.md` is unchanged (its text is in release-manifest fixtures). The keys file is appended
  after it in the one panel prompt for G8 and G9 (`factory/run.py` `review()`), so the new section
  qualifies its "every contestant monitor route". `gate_state.py` hashes the keys file into both
  gates' identities, so each new launch reruns that panel once (expected); `calibration.py` does not,
  so sealed cases are untouched.
- The live sampler probing only generic paths stays a separate open issue.

## Rollout

Deploy for new launches only (scratchpad `deploy-newonly.sh`), as with the G8 scoring contract.
Running batches keep their plumbing.

## Test

`tests/bench/test_reviewer_limits.py` asserts the section, the routes it names, the
`bench_checker` rule and the builder line. It also checks that the bench code it describes is real
(`bench_checker` created BYPASSRLS, the switch in `bin/bench.py` and `bin/land`). It fails without
the change.
