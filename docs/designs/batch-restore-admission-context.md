# Preserve batch restore context at candidate admission

## Problem and real evidence

The deployed -4 smoke continuation failed before allocation: operation
`3e6e2af8-73a9-5b51-9845-ab62dafcff7c`, launch
`d52b0a0ec9f24e298261b90c5afcc7e3`. `launch.sh` authenticated and selected the
collected generation using `batch_holder source`, then called
`statement_round.prepare_restore(root, ...)`. That helper looked under
`root/sealed`, producing `ValueError: missing collected restore scorecard`.
No creation marker or worker ID exists; empty-worker cleanup settled. The failed
operation, original source export/import, archive and all budgets are retained.
Evidence: original local results/infrastructure/2026-11-04-plumbing-practice3/
practice4-launch-failure.json and practice4-failed-before-worker-terminal.json.

## Smallest shared change

Extend `prepare_restore` with optional keyword arguments `source_sealed` and
`card_path`. Defaults retain the legacy `root/sealed/CASE.scorecard.json` lookup.
The launcher passes its authenticated immutable batch `source_dir` as
`source_sealed`, its already-frozen `restore-input-scorecard.json` as `card_path`,
and `admission_root` as the history root. Pass the parsed frozen card into
`prepare(..., candidate_cards={case: card})`; candidate rejection lists and
public-search metadata must use this same card, without reopening its mutable
source path. `candidate_cards=None` preserves other existing callers; an explicit
map must cover exactly the candidate IDs and contain dictionary values.
For legacy restores pass root/sealed
and the same frozen card. Do not change identity, digest, age header, symlink,
archive-membership or statement checks for candidate handoffs. Candidate files
come from the selected source; historical duplicate screening remains rooted in
the authoritative admission history. Non-candidate restores return None after
reading the selected frozen public card, as before. No host decryption.

The existing launcher remains the only launch path. This removes an implicit
assumption about where collected inputs live; it adds no copied shadow card,
case-specific bundle, environment bypass or weakened validation.

## Tests

Use the real retained practice3-transfer card and ciphertext in an isolated
layout whose root/sealed does not contain the case. Demonstrate the legacy
lookup reproduces the observed failure, then execute the actual launcher's
admission block with the selected source directory and frozen card and require
success/empty candidate snapshot for this paused smoke. This must exercise the
call-site argument propagation, not just the helper's new keywords.

Add candidate tests with separate selected source and authoritative history:
history statements must enter the exported snapshot, only the authoritative
registry may change, and replay keeps its existing reservation. Freeze a card
then change the source card's rejected-candidate/public-search metadata; verify
only the frozen values authorize reservation release or search attachment.

Retain legacy/candidate tests. Add negative checks for symlink/missing card,
wrong archive path and candidate digest mismatch using existing real statement
fixtures wherever available. Authored candidate/card changes must be labelled;
they do not establish a full real candidate lifecycle. Run touched tests, fresh
diff review, and exact-head full validation before landing.

## Rollout and recovery boundary

Do not hot-patch the installed source or repin the started -4 journal. This
change fixes future restored launches; it does not authorize a new launch or
reset the failed operation. Root must separately establish a reviewed way to
roll the preserved pre-allocation failure forward through existing transfer /
incident recovery before retrying. A failed attempt is not a lifecycle pass.
No extra model/compute budget, worker, route, gate or scoring change.

## Murphy

Records new-batch-restore-admission-1. Closure requires the retained-artifact
launcher-boundary regression plus review; full resumed collection/stop/meter /
delete/settlement qualification remains open independently. No closure claimed
by the design. Do not close the associated immutable-operation recovery gap.
