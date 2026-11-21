# G11 side by side on an older bench

**What broke (f46dac-h9, 2026-11-21 01:40 UTC).** The case passed every gate except G11, and then G11 crashed
`InvalidInfra` at `fake_pass_report`.
- A release installs the case's own bench bundle, `063b54db`. Its `bin/fake-pass-check` predates `--traffic-tables`.
- The plumbing's `g11_side_by_side` sends that flag on every per-guard scan.
- The bench rejected all three scans (`unrecognized arguments`), so no verdict was scored.

**Fix.** `g11_slots` returns 1 (serial) unless the installed `fake-pass-check` mentions `--traffic-tables`.
- The serial path never sends the flag and has always worked on this bench.
- `g11_slots` is outside G11's fingerprint (the existing test asserts this), so no gate identity changes.
- The fingerprint includes the bench file but not the slot choice; that is why the version skew could not show up in the hash.
- Cost on an old bench: G11 runs serially again (pre-11-19 speed).

## Murphy rows

The register is not on main. The new row, to be numbered at merge:
- `new-g11-bench-skew-1`: G11's side-by-side path sends a flag the installed bench lacks, so every case on an older
  bench crashes at G11 after passing everything else. Closed by `tests/factory/test_g11_side_by_side.py`
  ("runs serially on a bench whose fake-pass-check lacks --traffic-tables"; it fails on the old code).
