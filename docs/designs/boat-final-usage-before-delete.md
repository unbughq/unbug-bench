# Capture final Boat usage before permanent deletion

## Problem and real feedback loop

On 2026-11-04 root prepared b-plumbing-practice-3 from reviewed merged e62a5c4.
All six offline and six phase-A live preflight checks passed. No deployment,
worker allocation, model call or extra allowance occurred.

Before spending, root queried the known deleted worker bx_z4wktrbn through the
pinned control-VM CLI: `bin/boat-call usage bx_z4wktrbn --json` returned exit 1,
HTTP404/sandbox-not-found twice. The same query in the only accessible organization
also returned not-found. `usage --help` confirms the command exists. The failure
is not an unsupported command or an account-balance observation.

Public evidence remains in results/infrastructure/2026-11-04-plumbing-practice3/:
preflight-final-live.json, prior-operations.json, prior-liabilities-usage.json,
deleted-usage-diagnostic.json and usage-org-scope-check.json. No raw credentials
or private case content were read into these observations.

Official sources (read 2026-11-04):
- https://docs.boat.dev/billing : per-sandbox usage is available while running
  or stopped; deleted resources contribute to aggregate deletedCost. Stopped
  time is not counted. Omit since/until for lifetime usage.
- https://docs.boat.dev/data-retention/delete : deletion is permanent and there
  is no deleted-sandbox list; deleting ends billing and erases sandbox data.
- https://docs.boat.dev/api/reference/sandboxes/get-sandbox-usage : same per-ID
  endpoint used by the pinned CLI. No alternative historical per-ID endpoint
  was identified.

Our accepted settlement design made an unsupported assumption: asking for a
per-ID receipt after deletion. Current code correctly holds on404 but therefore
cannot qualify this ordinary lifecycle. This is a plumbing bug, not case feedback.

## Change and deletion of the wrong assumption

Retain the existing launcher, cleanup owner, ledger and deletion receipts.
Normal owned cleanup becomes: verified collection (or existing deadline cleanup
path), stop the exact worker, verify a completed stopped state, capture stopped
lifetime usage for that ID, durably retain it, delete the exact worker, verify
the existing deletion operation/inventory proof, then settle the ledger from the
retained receipt. No post-deletion per-ID request is required for new generations.
No new launcher, provider, ledger, budget authority or per-case rescue path.

Reuse the existing per-worker spend.deletions/WORKER directory for stop/usage
receipts. Inspect pinned `stop --help` and actual public stop contract before
implementation; do not assume newer flags or fabricate provider operation fields.
A receipt must bind to exact worker, launch/state and completed stop evidence.
A usage response must match the ID if supplied, have running=false, nonnegative
integer seconds and finite nonnegative dollar amount, and represent lifetime
usage (no time window). Persist raw public response/hash and query/stop identity
atomically before any deletion request. Use existing filesystem/proof primitives.
A locally invented running=false flag or timestamps cannot substitute for a
provider response. running=false alone is insufficient: a refused stop may
pause billing; require the completed stopped state as well.

The current exclusive launch/cleanup ownership remains required. From completed
stop through deletion, no resume or resize can be admitted for this owned worker.
On restart, revalidate stopped state and refresh final usage before deletion if
the worker still exists; never trust an earlier running meter after an uncertain
restart. Once deletion starts, retain that receipt and the existing deletion
operation across replay rather than querying an erased ID. Completed deletion
plus retained final meter is the new settlement proof.

Deadline safety wins: missing/refused stop or usage must never keep a disposable
worker running beyond the existing deletion deadline. Preserve unknown accounting
and the reservation hold, delete through the existing exact-owner safety path,
and report a nonqualifying run. Never fabricate a receipt or delay teardown to
await billing. Stop/usage retries use existing overall remaining-time bounds,
not a fresh per-retry lifetime. Provider TTL remains unchanged.

Keep validating previously accepted deleted_lifetime_usage settlements for replay;
introduce only the minimum explicit new basis/schema needed for stop-usage-delete
proof. Permanent cumulative debits, ledger-first writes, mirror repair, no_creation
proof and ordinary Hetzner behavior remain. Never overwrite real prior receipts.

## Historical evidence and explicit limit

The control home has one old unbound legacy reservation: status=finished, usd=0.036,
no state_path or envelope fields, and no final actual_spend_usd. This record is
preserved. It is not zero and not newly settled. The already-deleted worker's
exact usage cannot be reconstructed from a monthly aggregate or wallet delta.
No migration/write-off, deletion of the ledger row, credit release, new control
home or new allowance is authorized by this change. Determine exact binding from
retained public spend/creation/deletion evidence; if it cannot be proved, report
the remaining owner disposition required with the specific amount and evidence.
Future cleanup correctness does not silently repair historical evidence.

## Tests and rollout

First capture a minimal PUBLIC projection of the actual usage404 response and
retain source provenance. Replay existing deletion/create evidence plus authored
stop/usage transport edges through the real lifecycle functions. Assertions:
1. Stop-complete -> exact lifetime usage -> durable receipt -> deletion request.
2. Running meter, wrong ID, partial/negative/nonfinite usage and incomplete stop
   never settle; teardown still honors existing deadline and leaves the hold.
3. Crash before/after receipt write and after deletion acceptance reuse exact
   authority/operation and never resume, double-delete or reset budget.
4. New proof settles after deletion without a per-ID post-delete query; captured
   real404 never becomes a zero-cost settlement. Old accepted settlement and
   no_creation fixtures continue to replay.
5. Receipt tampering, later resume/resize uncertainty, missing stop/meter receipt,
   wrong deletion ID and incomplete inventory refuse settlement.
6. Existing bounded retirement/deletion paths and Hetzner compatibility hold.

Run touched tests, fresh diff review and exactly one final complete offline suite.
Re-pin corrected public release after merge. Existing prepared e62a5c4 pins are
not suitable for a modified runtime. No new spending or model roles. Qualify the
new stop/meter/delete receipt sequence on the already-authorized no-model smoke
only after historical liabilities, existing unlock and remaining prerequisites
are honestly resolved. Practice follows only after smoke passes. No fleet.

## Murphy rows and closure limits

This addresses rows17/49/51's missing live per-ID settlement path and the
no-human-pit-stop target. Add this real failure evidence to row49 before fixing.
No row closes on design or offline transport doubles; real normal-path meter,
collection, deletion, settlement and publication evidence are still required.
