# Stream B blocker resolution

This increment implements offline safety changes. It does not qualify deployment
or establish a hard infrastructure spending guarantee. No workers, paid calls,
VM mutations, push or activation were performed. Both activation gates stay off.
The newest local factory-simplify was merged at 9b9e5e0.

## Four blocker dispositions

| Blocker | Disposition | Reason and remaining exam |
|---|---|---|
| Cleanup cost guarantees | Deferred to the live practice run, with entry prerequisites | A live worker is needed to bind creation, delayed visibility, completed deletion and actual charges. One successful run cannot prove a universal ceiling. Existing public Boat contracts do not bound exceptional billable seconds or the opaque CLI's creation multiplicity. Obtain that contract/bounded request path first, or explicit founder approval of changed financial risk. USD 5 is not relaxed here. |
| Cumulative infrastructure accounting | Deferred to the live practice run after a reviewed Boat attributed settlement increment | Code no longer releases unknown liability at finish or admits another reservation alongside it. This is single-admission safety, not completed cumulative accounting. No saved attributed charges exist. A first finish blocks all further Boat admission on the same home, including non-batch callers. Relaunch, settlement and multi-worker exams require the named settlement increment first; this patch cannot run them. Practice must account for every start, billed lifetime, storage, proxy and egress charge and prove total preservation across restart/relaunch. |
| Legacy provenance | Resolved for case eligibility by retirement | Founder decision 2026-10-30 is recorded. All saved pre-new-schema inventory cases are retire-only, without reconstructing provenance. Planning retires legacy generations even with diagnosis disabled; holder source verification records retirement and refuses before money advance or transport. Original artifacts remain unchanged. |
| Deployment qualification | Deferred to the live practice run after the preceding prerequisites and B2/B3 | Qualify exact release/input/policy hashes, authenticated real VM/R2 bindings, router and account identity, Mac-off holder restart, delayed creation/deletion and terminal finish. The old practice-6ac450e staging is obsolete. Neither offline tests nor a retired case qualifies deployed infrastructure. |

Legacy launch b275ffccd6134a33833853ad1d31ed16 is retire-only as case work.
Its unknown provider debt is a cleanup/accounting entry prerequisite BEFORE any
new admission: provider-bound non-creation evidence, or a positively linked
worker plus completed deletion and charges. Empty inventory and timestamps do
not prove either. The observed ledger was missing and cannot account for this
debt. This is an operator entry condition: the holder gate is disabled, but
manual non-batch launches against a missing ledger are not fenced by this patch.
No completion/deletion/spend-finished marker was fabricated; no record removed.

## Implemented behavior

boat-spend validates ledger shape and nonnegative finite amounts before check or
finish. Any other reserved, finished or historical reconciled_expired row refuses
without querying billing or writing the ledger. Same-key replay counts once and
preserves its existing spend record. Refusal preserves existing target records;
a new refusal record says allowed=false with null balances when no query occurred.
Finish keeps actual cost unknown; account balance changes remain unattributed.
All commits fsync the file and its directory. Provider error text is not emitted
or persisted by boat-spend. There is no settlement-import or reset bypass.
Hetzner's separate path is outside this Boat liability change.

Legacy planning returns retired/legacy_retire and persists an idempotent public
record under batches/<batch>/retirements/<case>/<generation>.json after snapshot
verification. Conflicts, links and nonregular records refuse unchanged. Holder
_source authenticates the predecessor then uses the same terminal case record.
That record is distinct from worker-deletion proof and does not release money.
It is a durable file only: batch_status UI remains unchanged. The planning
function currently has no production caller; holder source rejection is the
runtime enforcement for collected legacy sources with job_money but no
new-schema diagnosis_state. Inventory-only historical cases have no journal/ACK;
the frozen disposition records their exclusion, not a live catalog rewrite.

The frozen disposition is stream-b-legacy-retirements-20261031.json, derived from
the retained 2026-10-30 inventory with its digest. It covers all 43 Mac and 46 VM
entries, retaining both stores' card/archive/file and case-key metadata. No
credentials or case contents were added. Conflicting and missing-bound archive
variants remain historical evidence, never practice inputs.

## Verification and reviews

Focused regressions exercise real saved billing/creation/card/inventory artifacts
through local transport doubles, plus explicitly authored failure injections.
They prove exclusion, replay and refusal semantics, not a real cloud lifecycle.
Independent launch-guard scenarios use distinct synthetic homes; production has
no reset path. The full-suite result record and fresh diff review are recorded
below after completion.

Design reviews: docs/reviews/stream-b-blocker-resolution-design-1.md (FAIL,
all findings accepted) and -design-2.md (PASS, precision findings accepted).
Rows closed: none. Rows 6,17,27,28,29,35,49,51 and the open batch-service and
single-path rows retain their existing statuses; the wider lifecycle proof is
not present. No new observed live failure was claimed.


First full suite: 162 scripts, 3 failed, exit 1; retained in
stream-b-blocker-resolution-suite-20261031T154203Z-bcf0c723.json and .log.gz.
The failures were stale expectations: launch-guard diagnostic text, gate-smoke
second admission, and the integration test's second job/restore launches after
unknown liability. Updated tests require refusal without a second provider
creation and retain first-worker collection/deletion and model-ledger checks.
Gate-smoke's independent remote-failure scenario uses a separate synthetic home.
The removed successful multi-worker integration expectation is now a deferred
settlement/practice exam, not a claimed pass under the new safety rule.


Second full suite passed: **162 scripts, 0 failed, exit 0**, source
31ec2d9621f1ceca3ad0eb594f35c652d0bbc57b; started 2026-10-31T16:12:40Z,
finished 2026-10-31T16:40:16Z. Result:
stream-b-blocker-resolution-suite-20261031T161240Z-b655fad9.json;
compressed log: same basename .log.gz. Uncompressed log SHA256:
88b5b83f4c5b0d310848cfa0c7b033fabdef7420a705cb997a74d0e5c7166017.
Source/tests were unchanged during this full run. The log retains all reported
skips and limitations; this is offline validation, not live qualification.
Fresh diff review follows this committed record.
