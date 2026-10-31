# Stream D item 7: durable extension writer receipt routing

## Problem and scope

First admission publishes extension history before attack-state.json. A crash
between these writes loses writer intent or leaves the prior completed receipt.
The active writer admission seam correctly refuses either. This increment retains
intent and supplies a receipt selector before launcher/package integration. Keep
run.py edits inside pending_call to avoid lane 1's stress/ordinary retry work.
Diagnosis stays disabled. No Murphy row closes; row 9 remains open. No section 4,
money authority, history schema, launch mode or runtime flag changes.

## Change

Before extensions.admit publishes history, pending_call constructs the complete
schema-2 pending writer receipt including operation, extension, round, binding
hash and first lease/invocation. A helper retains it at
work/extension-writers/<operation UUID>.json. The private envelope has exactly
`receipt` and `previous`; previous is parsed attack-state.json or null if absent.
Use diagnosis._input_bytes for no-follow reads. Missing differs from malformed;
permission/EIO errors propagate. Existing intent files must equal the proposed
envelope or refuse extension_reservation_mismatch. Write atomically before
history, then publish attack-state after history through existing admitted().
No callback or writer runs before both history and attack receipt. Orphan intents
have fresh operation UUIDs and cannot authorize anything without active history.
Only encrypted private work checkpoints retain these files, never public cards.

Add extensions.writer_receipt(c), without a production caller in this increment.
Read and verify active history; no active row returns None. Load its retained
intent. Require writer_intent_valid, matching binding hash, dictionary binding,
deterministic report name, and writer_continuation to bind the pending intent to
the active row and its original reservation. Previous must be null or a dictionary
whose strict integer round is less than the active round. Admission rejects bad
predecessors before history publication. Retain exact intent, never reconstruct
feedback from current case files or a prior writer.

If current attack-state is absent and previous is null, or current equals
previous exactly, atomically publish the retained pending receipt and set
builder_rounds to the active round. If previous was present but current is
missing, refuse. Foreign or damaged receipts refuse without overwriting.
Recovery changes no reservation, history, snapshot, invocation or extension count.
A settled first reservation still binds the operation. Replaying after file
publication but before builder_rounds update repairs the public count.

For a current receipt of the active operation, preserve it byte-for-byte. Require
matching actor, extension, round, operation, valid writer intent, binding hash
and report name, and phase pending/completed/validated. Pending must pass
writer_continuation, including archived wait proof. Completed/validated must
bind their lease/invocation to a reservation of the same operation and builder
name. The only mutable fields are phase, lease_id, invocation_id, resumed_from_wait,
binding, binding_sha256, output_sha256, repair_pending, next_phase,
validation_problems, awaiting_stress, stop_reason and exhausted. All other keys
and values must equal the retained intent. Binding hash always means SHA256 of
that receipt's own json.dumps(binding, sort_keys=True). Binding must be a dict;
this selector does not require current attack_binding keys, since that belongs
to release migration/package routing and the admission seam accepts any dict.
A pending receipt with the original lease/invocation must retain the original
binding. Later leases and completed/validated writers may have changed binding.
The existing validation producer changes binding without updating its hash;
this increment does not accept such inconsistent receipts or change that producer.
Package wiring must update the producer's hash before consuming this selector.
Use real complete_writer followed by validated phase updates with unchanged
binding in tests; separately assert inconsistent binding refuses. Return the
receipt without certifying a scientific pass, executing a writer or changing a
finished phase back to pending. Missing intent on old active histories refuses;
there is no guessing migration. A later package router must call this helper
before the ordinary resume receipt code can rewrite attack-state.

Before validating the writer intent, if the current receipt is a dictionary
with actor stress_tester and strict integer round equal to the active round,
return None without modifying any file or builder_rounds. None means no writer
receipt to route, not stress authorization or successful writer validation.
The future package router must separately validate the stress operation,
reservation and evidence. Foreign-round stress receipts still refuse.
This branch requires verified active history but does not require a writer-intent
file, since it is not recovering or authorizing a writer. Test all three stress
phases plus wrong-round and boolean-round controls.

Fsync work after creating extension-writers. Keep immutable create-and-verify
for deterministic helper replay under the existing case dispatch lock, although
normal first admissions use distinct UUIDs. Both retention and recovery require
the existing model dispatch lock; helpers acquire it using model_runtime.dispatch
(the lock is reentrant). Retention takes the complete pending receipt as input;
its caller supplies the already-reserved operation/lease before admit. Recovery
has no money or model side effect. Use semantic extension_reservation_mismatch
for malformed/missing/unsafe receipt data, while real permission/EIO propagate.

## Deletions and costs

No legacy allowance is deleted yet. Replace the unrecoverable publication window
with retained intent and deterministic selection. One small private JSON per
admitted operation; no new module, dependency or authority mechanism.

## Tests and Murphy rows

Extend tests/factory/test_stream_d_admission.py with the saved practice case and
5813be ledger. Stage/money envelopes and model execution are authored controls;
this is offline durability evidence, not live qualification or row closure.
Exercise history/attack publication failures with absent and prior completed
receipts; recover exact original intent and invoke existing writer continuation
without allocating another extension. Replay recovery twice, asserting unchanged
history, intent and reservation count. Preserve pending provider-wait and
completed/validated receipts. Refuse missing/malformed intent, altered identity,
intent or binding hash, foreign current receipt, deleted predecessor, invalid
predecessor round, mismatched reservation and symlinks. Permission/EIO propagate.
Intent-write failure creates no history, writer or callback. Keep ordinary and
existing continuation controls. Run the full suite at a unique log path, wait
for exit and commit the record. Get fresh design and diff reviews; save final
reports and responses only.

Remaining item 7: launcher routing, exactly one writer/stress/gate package with
freshness and unfinished stress, all three diagnosis outcome routes, and removal
of qualified-path legacy allowances. Merge lane 1 item 4 before package
integration. Item 8 needs integrated retained-artifact and authorized live A/B/E
qualification before diagnosis switch-on.

## Completion criterion and target files

A stopped case can recover the exact admitted writer request after either
publication interruption, without another extension or lost completed work.
This is one implementation/review increment. Changes are confined to
factory/extensions.py, pending_call in factory/run.py, the existing admission
tests, and this design/review/suite record. No launch qualification is claimed.

Design-2 nits: predecessor equality takes priority over foreign stress refusal.
The preserve path repairs builder_rounds but never rewrites the receipt file.
Dispatch call names are extension-writer-intent and extension-writer-receipt;
held work intentionally refuses through require_model_work. These are factory
job helpers (the existing dispatch lock policy is unchanged). Future package
routing must preserve round_limit/release_* on pending continuation rather than
overwriting them through the ordinary writer loop's receipt merge.
