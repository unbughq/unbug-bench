# Stream D item 6 full-suite validation

Command: `uv run --with numpy --with scipy python -B tests/run.py`.

Run 1 tested `5525893`: 157 scripts, 1 failed, exit 1. The only failure was
`tests/tools/test_launch_manifest.py`, whose independent expected upload inventory
needed the new `factory/extension_compare.py` module. Its explicit reviewed
additions now include that module. No production change was needed.

Log: [stream-d-compare-suite-20261031-1.log.gz](stream-d-compare-suite-20261031-1.log.gz).
Original unique log: `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-d-compare-20261031-suite-jm6v74gs.log`.
Uncompressed SHA256: `acafc7e1ec188919b521a44e971bfb13c1e612d1762b622dd57cb65f0cc0a1e8`.

Focused comparison tests: 14 passed. Existing extension-state tests: 17 passed.
The full run includes existing skips, retained in the log.

No Murphy rows close. Item 6 supports row 9; row 39 stays open because no saved
per-attempt capped-submission artifact exists in the retained fixtures. Item 8
needs an authorized ordinary G10 run that submits a guard before its existing
time/call cap, retaining results.json, the guard, execution.json, stop metadata
and bound usage/reservation settlement, then replay through G16/G17. No real
case or paid run was launched, and diagnosis remains disabled. The production
isolated process/evaluator adapter and admission/continuation routing remain
item 7 work.
