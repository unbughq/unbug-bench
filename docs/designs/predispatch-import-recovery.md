# Carry a terminal refusal before dispatch, preserving original checkpoint ownership

## Problem and evidence

Live practice-5 operation b80f8f3b-0801-5b5e-8658-c2fd5cd0cecb refused before
dispatch_started. The collected original practice-3 generation remained intact;
source authentication passed, but batch.bind expected immediate predecessor-4's
release. The small reviewed ancestor binding correction fixes that check.
No worker, controller, compute reservation or model call was created. The exact
ledger hash stayed 1f9bb4de...d00d. Cleanup retained not_dispatched/workers=[];
holder and cleanup are now inactive. Never reset or retry this failed operation.

The existing certificate covers started launches settled as no_creation. It
intentionally does not cover this earlier failure. We need one generic proof for
terminal pre-dispatch refusal, on the same transfer path; no extra launcher.

## Change

Extend practice_cleanup.preallocation_settlement with a separate strict
not_dispatched branch. Keep the started/no_creation branch byte behavior and
certificate format unchanged. Shared predicates: state failed, incident
preflight_refused, worker/output/retirement None, dispatch_started strictly bool.

For the new branch require dispatch_started is False and launch is None. Under
the existing nonblocking operation lock:

1. Require the exact launch path absent, rejecting symlinks (even dangling) and
   any existing directory or file. Do not create a path to make it qualify.
2. Use existing no_reservation under the existing nonblocking shared compute
   ledger lock. It fully validates the retained ledger and must find no spend
   row for that exact launch path. Missing ledger/lock is unknown and refuses.
3. Load the regular exact-operation cleanup status. Require schema integer1,
   operation ID exact, state not_dispatched, workers [], settlement not_attempted,
   deadline None and settlement_attempted_at None.
4. Return the existing schema1 certificate with operation/launch IDs, the cleanup
   raw-byte SHA and settlement_sha256 of a stable public basis object containing
   basis not_dispatched, operation ID, launch ID and exact state path. The source
   snapshot already includes the immutable full operation. No whole-ledger hash,
   fake finished marker or claim of provider final metering.

The durable dispatch_started-before-Popen invariant plus operation lock and
terminal state fences any legitimate spawn for this operation. Missing worker
inventory never provides this proof. Future operations have distinct IDs/paths.
The model commitment, conservative old compute debits, holds and failures remain.

Reuse batch_transfer.snapshot/prepare/source without a new path: the new branch
produces the same certificate envelope consumed by existing imported-base guards.
Pair this with the independently reviewed producing-release binding correction,
which authenticates the recursive source card before choosing its release.

Prepare inactive b-plumbing-practice-6 only after independently observing the
exact certified -5 snapshot. Carry the unchanged b615c37c...d6d9 smoke generation,
.01 held model authority, zero prior model total, 19.98 dormant practice allocation,
19.99 model cap, $5 cumulative compute cap, Nov7 deadline and 30m/15m/60m timing.
Preserve all -3/-4/-5 exports, imports, operations, ledger bytes and release pins.
Never enable practice, fleet, a replacement or automatic retry. Deployment and
one no-model worker continuation use the prior unspent authority, independently
rechecked before reserve/arm/dispatch through the existing holder.

## Tests and acceptance

Retain actual public -5 operation, cleanup status, ledger and absence observation;
no keys, case text or logs. Reuse retained original -3 and -4 source artifacts.
Authored temp relocation/activation and host adapters remain explicitly labelled.

Prove absent-launch certificate without source/ledger mutation; strict rejection
of launch/path/symlink presence, any bound reservation (including settled), missing
or malformed ledger, foreign/incomplete cleanup, wrong types, non-None launch,
active operation/ledger locks using another process. Check original settled-zero
certificate and snapshot digests remain unchanged. Real source chain test must
cover export/import replay -> reserve -> batch.bind, exact original producer
release, target release args and original ciphertext hash; producer tampering
must fail. Extend the retained path through prepare_restore's public source and
frozen-card selection seam if possible without private decryption. Run focused
checks, fresh design/diff review and one exact-head full suite on final combined
source. After merge verify identical tree or validate integration once.

Live smoke pass remains collection/ciphertext/publication ACK plus fresh same-stop
meter, exact-worker completed deletion and settlement, never controller exit or
startup alone. No new Murphy closure on offline tests.

## Deletes and Murphy

Remove only the unsupported immediate-predecessor release assumption and the
unconditional refusal of a proven never-dispatched failed import. Add no journal
reset, mutable pointer, invented zero-spend settlement, launch path or budget.
Record new-ancestor-release-binding-1 and new-predispatch-import-recovery-1; leave
both open until required real evidence exists. No engineering design rule or
case-scoring standard changes.
