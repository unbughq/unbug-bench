# Fresh-case observation publication recovery

## Change

Records.save_observation makes at most two filesystem-publication attempts using
one completed gate result. It validates a renamed record and syncs it again after
an acknowledgement failure; it never deletes that published proof or invokes a
gate. A missing target permits one retry of the copy. Existing save/load retain
the identity, version, digest and support checks. JSON-digest comparison accepts
normal tuple/list and integer-key JSON conversion, but rejects NaN.

Post-invoke observation catches ordinary Exception so a capture failure cannot
cause a paid gate retry. BaseException and invocation errors keep their ordinary
route. Verification copies args/card, so G3 does not restore live worker state.
The record card is the live post-invoke card on each save; the result and old_card
are frozen. Package capture and entry logic are unchanged.

## Validation

Focused entry run: 26 tests passed in 54.807s. The subsequent added verification
exam and strengthened real-artifact byte check both passed (2 tests, 8.192s).
The locked full suite remains pending. The tests use real
saved G4/G5 execution bytes with labelled external controls. New exams cover the
parent-approved one-shot ACK and persistent sync cases, pre-rename copy retry,
stress publication, RuntimeError boundaries, JSON normalization, copied G3 state,
corrupt/symlink/pre-existing targets, case/version drift and a kill after G4 rename.

## Review and scope

Design reviews 1 and 2 are saved in docs/reviews/stream-d-capture-recovery-design-{1,2}.md.
The parent approved B3 after round 2: narrow the success exam to a one-shot G1
post-rename failure, allow verification sync, assert closed.json; keep the
persistent failure separately pending. O1/O2 are applied and O3 accepted as scoped.
There is no design round 3. A fresh diff review remains required.

No Murphy rows close. Activation, money limits, scientific versions and snapshot
schema are unchanged. Retired/pre-schema adapters are excluded. Genuinely absent
or corrupt proof and permanent copy failures still hold; no result is invented.
Remaining item 7: final all-outcomes integration (4–6 engineering hours, plus
suite queue/provider time), which must explicitly assess those holds. No pilot
is started in this increment.
