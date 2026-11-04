# Carry a proven pre-allocation failure without resetting its history

## Evidence and need

The real public -4 smoke operation 3e6e2af8-73a9-5b51-9845-ab62dafcff7c failed
before allocation. Its launch is complete, has no new.* markers and empty ids;
its compute row is settled with basis no_creation, workers [], actual spend 0.
Its imported base is the unchanged -3 checkpoint b615c37c...d6d9. Both prior
exports/imports and the failed operation must stay preserved. The restore fix is
merged separately; no live hot-patch or retry of that immutable operation.

Current transfer refuses the incident in snapshot(), refuses imported bases
without a local ACK in prepare(), and returns an immediate-parent generation
path even when _source resolves an older ancestor. A narrow recovery must address
all three on the same existing transfer/launch path. It does not enable unknown
creation, active workers, failed case gates, paid-budget reset or arbitrary retries.

## Reuse the existing proof and transaction boundaries

Add practice_cleanup.preallocation_settlement(home, op), a read-only certificate
helper. It raises/refuses unless all of these hold:

- op is failed/preflight_refused, dispatch_started true, worker/output/retirement
  all None. The operation and controller locks are acquired nonblocking.
- The exact owned launch directory is regular, launch.json equals op.launch;
  complete and spend-finished are regular markers; ids is regular and empty;
  no new.* exists (including unknown pending creations).
- Under the existing shared nonblocking boat-reservations.lock, reuse
  bound_spend and read_ledger. Exactly one row binds this state directory; it is
  settled, settlement basis is no_creation, workers [], actual_spend_usd zero.
  Validate the existing settlement_amount grammar and require its total zero.
- The bound spend file is regular, finished, allowed Boat envelope matching the
  row (vms/TTL/max spend), empty ids, zero actual spend, and identical settlement.
  The existing cleanup status is exact-op complete/settled with workers [].

Return a schema-1 public certificate with operation_id, launch_id and SHA256 of
launch.json, ids, complete, spend-finished, spend JSON, cleanup status and stable
settlement/envelope fields. Do not hash the whole changing compute ledger. Do not
mutate the row, ignore a hold, infer zero from missing data or query a provider.
This helper stays separate from preflight_clear's no-reservation rule.

## Existing transfer changes

1. snapshot() keeps its current money and operation checks. For a failed
   preflight_refused operation only, require the certificate instead of refusing
   the incident. Include certificates in a new optional snapshot member
   preallocation_settlements keyed by operation ID. Omit the member when empty,
   preserving all existing snapshot hashes. The original incident stays present.
2. prepare() retains the existing local-ACK path. Additionally allow an imported
   base only when its selected generation equals imported.generation, sources is
   exactly [generation], authority/previous/known_floor equal imported values,
   there are no ACKs, and at least one operation exists for this job and every
   such operation has the validated certificate. Require _source authentication
   against the existing recursive predecessor receipts. The original ancestor
   ACK keeps its original authority; do not relabel it as the immediate imported
   parent's authority. That chain is checked by read_import/imported_row and the
   exact unchanged imported-base predicates. Keep the local-ACK authority equality
   on the original local-successor path. Keep case/template,
   commitment, aggregate money, allocation and deadline checks unchanged.
3. source() revalidates each immediate predecessor snapshot as today. When that
   predecessor row imports this same generation, recursively return the original
   ancestor's verified source tuple, including its actual directory. Otherwise
   retain the local path. The existing checked maximum-64 acyclic manifest chain
   remains mandatory; no new mutable pointer or copied checkpoint is added.

Export-first atomic commit/replay and money locks remain. All proof locks are
nonblocking, so taking them while holding source money locks cannot deadlock a
controller taking those locks in the other order. Pending/active/unknown cases
refuse, preserving liability. Old receipts and settled rows are never rewritten.
This is a generic no-allocation plumbing-recovery path, not a ruling for one case.

## Inactive successor preparation

After review/tests, prepare b-plumbing-practice-5 from the exact retained -4
manifest and certified source snapshot. Import smoke at the same original case
and checkpoint; keep the same .01 held commitment, zero previous model total,
19.98 unreserved practice allocation, 19.99 model cap, original $5 compute cap,
roles, counts, Nov7 deadline and 30m/15m/60m timing. Carry every omitted liability.
Prior .036 + .036 debits and this settled-zero attempt remain in the same ledger.
No automatic retry, practice dispatch, top-up or extra worker authority. Fresh
pins and ordinary reviewed deployment are required; never edit started journals.

## Tests and evidence

Retain actual public -4 operational JSONs and its deployed fbc96881... release in
tests/factory/fixtures/preallocation-recovery with SHA provenance. Reuse the
existing real -3 generation/release fixtures. Label temporary path adaptations
and any target-host verification double as authored; do not call them live proof.

First reproduce snapshot refusal and imported-base refusal using this corpus.
Then prove certificate validation, snapshot compatibility, preserved incidents,
recursive source identity/path, exact commitments/debits, and export/import replay
without a changed reservation or extra debit. Mutations must refuse: any creation
or pending marker, IDs/worker, missing/incomplete/unknown settlement, nonzero spend,
foreign launch/envelope/cleanup proof, held controller/operation/ledger lock,
advanced generation or local money changes, bad ancestor snapshot/pointer,
cycle/overlong chain. Exercise locks with a second process. Run touched tests,
fresh reviews, and one full suite on the final source before landing.

## Deletes and Murphy

Remove only the unconditional refusal of this proven empty lifecycle and the
wrong immediate-parent path assumption. Keep all records and all case-quality
checks. Record new-preallocation-import-recovery-1; do not close it or any live
lifecycle row on authored adaptations alone. Live acceptance still requires the
same-stop meter, collection/publication, exact deletion and settlement.
