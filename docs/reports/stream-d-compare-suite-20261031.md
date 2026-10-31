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


Run 2 tested `6492fa5`: **157 scripts, 0 failed, exit 0**. The full command
finished before this record was committed and before the fresh diff review.
Log: [stream-d-compare-suite-20261031-2.log.gz](stream-d-compare-suite-20261031-2.log.gz).
Original unique log: `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-d-compare-20261031-suite-2-v12pw8ia.log`.
Uncompressed SHA256: `022c9c97ef7210332dd7aedacb165960da955d760ec1e7e8bc7702cc1afb7e9e`.
The corrected manifest test also passed independently (2 tests).


Run 3 tested `eff8114009cb54289afecd974d5442785451e7e2`: **157 scripts, 0 failed,
exit 0**. This includes diff-review-1 fixes at `f5218fa` and the parent-authorized
merge of `c32e884` (E loaded cleanup and A account-2 routing). Comparison focused
coverage is now 16 tests; all passed, as did the 17 existing extension-state
tests. The full command completed before this record and the fresh re-review.

Log: [stream-d-compare-suite-20261031-3.log.gz](stream-d-compare-suite-20261031-3.log.gz).
Original unique log: `/var/folders/wy/9m9k8zxx55dbm7_s_xqfmc7c0000gn/T/stream-d-compare-20261031-suite-3-gsgdvxr4.log`.
Uncompressed SHA256: `57116de067b15263dc5fed70c1392cbad76b393fe94a744da28503bae571c404`.
The item-6 change still closes no Murphy row; register changes inherited from
`c32e884` belong to their original streams.
