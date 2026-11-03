# Boat attributed settlement — independent scoped diff review

- Mode: REVIEW.
- Personas: `zoom_out`, `implementation_readiness`.
- Standards: `zoom-out-standard.md`, `implementation-readiness-standard.md`.
- Reviewed implementation: `2c174ba^..0292abc`, including both implementation commits.
- Reviewed against: `docs/designs/boat-attributed-settlement.md`, its two accepted design reviews, `docs/reports/boat-attributed-settlement.md`, and referenced implementation, tests, trusted inventory, and retained deletion evidence.
- This was a fresh, read-only review. No edits, delegates, test execution, live calls, provider calls, qualification actions, secrets access, or practice-state access.

## Verdict: PASS for the offline implementation

No blocking implementation finding identified in the scoped diff. This verdict does not establish live multiple-lifecycle readiness and does not replace required test runs.

## Implementation checks

The implementation follows the accepted design while retaining the existing ledger, admission lock, launcher and cleanup owner.

- **Ownership and attribution:** `bin/boat-spend:137` checks the ledger’s canonical state binding and spend envelope before settlement. `factory/boat_lifecycle.py:117` independently validates creation evidence, rejects pending/unknown creation names and duplicate identities, and requires every reserved creation slot to be accounted for.
- **Deletion and usage:** `factory/boat_lifecycle.py:141` requires matching deletion request/completion identity, complete inventory absence and stopped per-ID lifetime usage. Usage calls contain the worker ID and no date filters. Invalid usage, mismatched identities or any failed worker prevent the ledger write.
- **Permanent cumulative debit:** `bin/boat-spend:196` permits successors only after other liabilities settle. Admission adds settled actual charges to the new estimate and applies the minimum historical/current cap. Increasing a later cap cannot replenish headroom. Over-cap actual usage remains recorded.
- **Replay:** Settlement commits the ledger before mirroring the spend record. Settled replay repairs the mirror without querying usage again. `--finish` preserves settled authority and its debit.
- **Cleanup recovery:** `factory/practice_cleanup.py:73` persists the attempt timestamp before starting settlement, reads it again on subsequent iterations, enforces the 60-second interval and passes the control home explicitly. Cleanup calls `--settle` directly without inventing an exit code.
- **Reuse and deployment:** Inventory uses the shared settlement validator and reports `settled_usd`. The existing trusted-file inventory already includes `boat_lifecycle.py`; no additional runtime dependency or service was introduced.

## Accepted design-review regressions

Both mandatory regressions from design review round 2 are present:

1. `tests/factory/test_boat_settlement.py:223` exercises real guard initialization with an invalid TTL margin, causing an exit after admission and before `monitor.sh` exists. It asserts a settled zero-creation row.
2. `tests/factory/test_boat_settlement.py:238` makes inline zero-creation settlement fail, then exercises cleanup retry without a monitor, including suppression before 60 seconds and successful recovery afterward.

The tests also challenge malformed usage, duplicate JSON, ownership mismatch, uncertain creation, wrong deletion identity, incomplete inventory, partial two-worker success, malformed persisted settlement, cumulative boundaries, over-cap debits, concurrent successors and ledger-first mirror recovery. The fixtures clearly distinguish retained real deletion receipts from authored usage, inventory and lifecycle layouts.

## Verification and live boundary

The report within the reviewed range records targeted checks. Its saved full-suite attempt is explicitly cancelled and non-qualifying; successful exact-head/merged-tree suite provenance must be assessed separately. I did not execute tests.

The missing live proof remains exactly the accepted qualification gate: the pinned Boat CLI must return final lifetime per-ID usage **after verified deletion**, including across the month boundary. The retained contract describes stopped usage and lifetime queries but does not establish deleted-ID availability.

A 404, unsupported verb or incomplete response must retain the liability hold and STOP reuse. This review authorizes no live action and supplies no substitute for that proof. Snapshot/proxy exclusions, top-up status and sufficient credit remain live checks. Murphy rows 17, 49 and 51 remain open.
