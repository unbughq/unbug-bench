# Durable execution: case-scoped inputs

Status: **rejected by design review**. This proposed amending the version-5 durable contract
and the approved durable-execution design only as described below. No code or
contract change may be made on the strength of this proposal until it passes a
fresh design review. The review found a smaller v5-compatible solution and a
potential expansion of confidential input access; see
`docs/reviews/durable-execution-case-inputs-design-1.md`. The proposal below is
retained as the reviewed artifact, not an approved change.

## Problem

The engine must supply the batch's encrypted inputs to every step. `INPUTS` is a
batch-scoped kind, and WP3's store correctly rejects it under a case scope. The
worker protocol sends the batch key only to ADMIT; later steps receive the case
key. WP1 currently reseals the inputs with the case key, but keeps the `INPUTS`
kind and tries to put it in a case scope. This is rejected by the real store.
Permissive test fakes hide the failure. The two original rules cannot both hold
for the current `INPUTS` kind.

## Change

Add one distinct kind, `CASE_INPUTS` (`case_inputs`). `INPUTS` remains batch-scoped
and is the sole kind accepted for `BatchSpec.inputs` and ADMIT `StepInput.inputs`.
Every non-ADMIT `StepInput.inputs` is a `CASE_INPUTS` ref. It is case-scoped by the
existing `BATCH_SCOPED` rule and can be opened only with that case's key.

After ADMIT, the control-side executor opens the original INPUTS with the batch
key and seals the same bytes as CASE_INPUTS with the case key, using WP3's
`open_from` and `seal_into` helpers. The case workflow records only the resulting
ref. The original INPUTS stays immutable; each case's copy has its own keyed
digest and ciphertext. Input values, keys and plaintext never enter a DBOS
argument, event, result, exception or log.

WP2's blob naming accepts the new enum value without a special case. `scope_for`
and the store's existing checks choose the case scope for it. WP5a must open
CASE_INPUTS with the case key if a step needs the input bytes, and must not expect
the batch key outside ADMIT. These steps already restore a case-scoped snapshot;
the new ref supplies explicit input provenance rather than changing the snapshot.
Other output refs continue to use their existing kinds and scopes.

The meaning and secrecy of existing kinds do not change, and the batch key is not
sent to any additional worker step. Bump the contract version to 6; the shape of
the JSON records is unchanged, but a non-ADMIT record naming the old INPUTS kind
is rejected. There is no automatic migration of earlier DBOS workflows: the
handoff says no durable engine has run on real infrastructure. Existing local
test databases are disposable and must be recreated; if an actual v5 engine
database is discovered, stop and design its migration rather than interpreting
its records under v6.

## What it deletes

Delete WP1's special-case `scope_of` rule that treats batch-scoped INPUTS as if it
were case-scoped. There is one kind-to-scope rule, `scope_for`; no bypass in the
store and no extra copy of the batch key on workers.

## Verification

1. Contract tests accept INPUTS exactly for ADMIT and CASE_INPUTS exactly for
   later steps, reject the converse and preserve strict serialization.
2. Use the real WP3 `AgeSealer` and `SealedStore` with a local backing store and
   two independent case keys. Reseal real test bytes from the batch into each
   case. Both refs must open only with their case key; neither must open with
   the other case or the batch key. The real store must reject each wrong scope.
3. Exercise the executor with the real store: a non-ADMIT frame contains the case
   key but no batch key, the named CASE_INPUTS blob opens under that key, and the
   control-side ref opens through `open_from` and `scope_for`.
4. Recheck WP2's real blob-name parser and WP5a's step-input parsing against v6.
   The broader worker integration and live test remain separate wave-1/WP9 work.

## Murphy rows

Targets the artifact/provenance portion of row 27 and
`new-batch-service-2`. This design and offline tests close no row: the existing
engineering rule requires proof with real lifecycle artifacts.
