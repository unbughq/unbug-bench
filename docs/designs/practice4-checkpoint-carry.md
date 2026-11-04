# Continue the collected smoke under the repaired release

## Problem

The November 4 smoke was collected, published and positively deleted, but has no
stopped-usage capture. The repair and both conservative compute debits are merged
and passed the 197-script suite at `569acf5`. The old batch's reservation journal
is bound to its original release, so swapping its release pin would correctly
refuse in `batch_holder._operations`. Never rewrite that journal or reset spend.

The read-only control-VM snapshot check on November 4 found the source eligible
for the existing `batch_transfer` path. Source `b-plumbing-practice-3` has exactly
one acknowledged, retired smoke operation, no incident, model total $0 and held
commitment $0.01. Its snapshot digest is
`d0f19598d7c3924b36d1c8277a2d4496c0fd457b522a3e7f3585fb81d983856d`.
Its release is
`cde6dc9244df96a693dbe8e97e4a2cedccda6504731394c14b672718facda7f4`;
smoke generation is
`b615c37c3ff2c3103576a74d1175cad299dc3eaf1f3f28f7a3b56b06eab2d6d9`.

## Change

Prepare an inactive `b-plumbing-practice-4` manifest using the existing whole-batch
carry contract, not a new launch path. Import the smoke at that exact generation,
keeping its original case ID, arguments, $0.01 commitment and zero actual model
total. Leave the unreserved practice job fresh, with the same $19.98 allocation,
roles and limits. The full model cap stays $19.99. The existing infrastructure
ledger, including the two approved $0.036 debits, stays untouched under $5.

`carry_from` embeds the exact old public manifest and its batch/jobs policy
projection, pins the validated snapshot, and imports only smoke. The existing
transfer freezes the old batch on authorized admission and carries every omitted
source liability; this preparation performs no export or ledger mutation.

Replace only the practice opt-in's active identity/EXPECTED manifest, cleanup
unit environment and holder drop-in with -4, preserving the -3 manifest and
records. Keep a fixed independent EXPECTED literal for the exact -4 contract;
do not load EXPECTED from the same file being compared.
Keep -3's tests as retained controls and add focused -4 carry coverage. Keep the
three previously recorded founder decisions with their original attribution and
timestamps; they grant no new worker, token/account change or extra budget.

Update the runbook: source snapshot must still match; install compatible pinned
source/policy through the existing root-SSH deployment; obtain the existing
unlock and explicit authority for exactly one new no-model smoke continuation;
arm independent cleanup before dispatch. Continue from the collected checkpoint,
not an empty input. Normal 30-minute collection, 15-minute grace and 60-minute TTL
remain unchanged. No automatic retry or practice admission on failure.

This branch grants no live authority. No worker, deployment, transfer/export,
credential operation, provider or model call is part of implementation. Do not
activate the dormant practice job; its later model work needs its own go-ahead.
Claude cloud implementation credits do not change factory model routing.

## Tests and acceptance

Use the retained original -3 manifest, public policy/release pins, validated
source snapshot and real collected public smoke card. Preserve the source
bytes and state, and label authored variants. Test -4 manifest/case/commitment
bindings, matching snapshot acceptance, altered snapshot/release/generation
refusal, original caps, old-batch opt-in refusal (including a stale -3
unit/drop-in), and dormant practice. Smoke-before-practice is procedural, not
code-enforced: the runbook orders the smoke continuation first and practice needs
a separate later go-ahead. The test asserts only that no job of the batch can be
reserved without the -4 opt-in (diff review 1, finding 1, option b); once -4 is
opted in for the smoke continuation, practice dormancy is procedural only.

Fixture provenance note: `provenance.json` says "adaptations: None" for the
retained bytes, which are unchanged. Three of them are JSON projections that
combine original files, not byte copies of single files: `source-public.json` =
{snapshot, public_policy, manifest_json}; `collection-public.json` = {journal,
generation_manifest}; `publication-public.json` = {current, outbox}. The retained
public evidence location recorded in the Murphy register is
`results/infrastructure/2026-11-04-plumbing-practice3/` (not in the repo tree).
The non-derivation parts of `collection-public.json`'s journal are bound by no pin.
Use existing transfer and readiness tests; do not invent a new state machine.
Run focused checks, fresh final diff review, then one final full offline suite.

Implementation checklist:
- Add `factory/batches/b-plumbing-practice-4.json` and its `.decisions.json`,
  retaining the original decision text and transcription timestamps unchanged.
- Update `factory/practice.py` (fixed literal and active ID),
  `factory/practice_preflight.py` (drop-in),
  `control/unbug-practice-cleanup@.service`, and `docs/designs/practice-run.md`.
- Preserve the original -3 smoke regression as an explicit legacy fixture in
  `tests/factory/test_startup_smoke.py`; update current identity checks in
  `tests/factory/test_practice_readiness.py`; add
  `tests/factory/test_practice4_carry.py` using the existing transfer APIs.
- Retain unchanged public source snapshot, policy/release, and the actual smoke
  card, encrypted checkpoint and encrypted wrapped case key under
  `tests/factory/fixtures/practice3-transfer/`, with original SHA/provenance.
  No plaintext case, key or credential is an input.
- In an isolated copied source/target layout, call existing
  `batch_transfer.prepare` and `batch_transfer.source`; assert original case,
  generation, $0.01 commitment, $0 previous total and exact restore archive.
  Label path/release adaptations as authored; retain the original inputs.
  Negative controls alter one snapshot/release/generation binding at a time.

Estimate: 45–75 minutes for implementation, focused checks, review and the final
offline suite on the exact landing tree. One implementer plus one read-only
reviewer; four shared test slots; no live compute or inference is authorized.

Root must revalidate the exact source snapshot before any later live import;
snapshot drift refuses, never repins silently. Live acceptance requires the exact
collected card/ciphertext, publication ACK/pointer, fresh same-stop completed
meter and recheck, completed exact-worker deletion receipt, and settlement.
Missing stop/meter proof remains failure, regardless of a passing science gate.

## Deletes and Murphy scope

Delete the redundant old EXPECTED literal only if replaced by the exact current
tracked manifest; add no generic practice framework. No Murphy row closes from
this preparation. `new-boat-stop-capture-1`, the startup-smoke row and complete
Murphy42 recovery proof stay open until their respective real evidence exists.
