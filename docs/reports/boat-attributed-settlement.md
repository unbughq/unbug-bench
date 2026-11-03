# Boat attributed settlement — offline implementation

Implements the two-round reviewed design in docs/designs/boat-attributed-settlement.md.
Bound launch reservations settle only from complete deletion/creation evidence plus
per-ID stopped lifetime usage, or a finished provably uncreated launch. Settled
machine charges remain permanent cumulative debits; later caps cannot reset them.
Ledger-first writes repair the spend mirror on replay without adding a charge.
Unknown evidence retains the hold. Account balance observations remain separate.

The independent practice cleanup loop retries settlement every 60 seconds, including
an uncreated launch whose inline settlement failed and whose monitor was never written.
No artificial exit code is recorded. The global holder and diagnosis gates stay off.
No practice state, pins or deployment were changed. No live calls, workers or paid
calls were made. No Murphy rows closed (17, 49 and 51 remain open).

Practice must be re-pinned after merge before admission. Old unbound reservations
cannot be silently migrated; Boat exam-launch/run-gate-smoke retain their old blocking
behavior on this home. Over-cap actual charges remain recorded and block further use.

## Evidence and limitations
The retained deletion receipts/spend record are real. Tests create state layouts
through real guards with authored provider/collection edges; usage, inventory and
second-worker receipts are authored. They prove validation, replay and arithmetic,
not deployed billing behavior. The saved historical balance delta is not used as
usage authority. No mutation tooling or writer assertion substitutes for diff review.

The first authorized live qualification must establish that pinned Boat can return
lifetime per-ID usage after deletion (including across month boundaries). A 404,
unsupported verb or incomplete result is a STOP; no balance-delta workaround exists.
Snapshot/proxy exclusions, credit and top-up checks remain live requirements.

## Targeted checks
New settlement script: 13 tests passed. Existing inventory: 10 passed; isolation
timeouts: 26 passed; practice readiness: 15 passed; batch launch integration: 8 passed.
A standalone control-resume invocation omitted BENCH and failed 8 tests because the
synthetic worker could not import processes. A diagnostic exposed ModuleNotFoundError;
no production fix or limit change was made for that invocation. Rerun uses the suite's
BENCH setting. Full-suite provenance and fresh diff review will follow below.
