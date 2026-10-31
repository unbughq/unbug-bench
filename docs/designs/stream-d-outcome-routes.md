# Stream D lane 1: diagnosis outcome routes

## Problem and scope

Item 7 currently dispatches diagnosis but stops a fresh close-to-passing decision
at extension_comparison_pending. Only an already admitted writer can continue.
Connect validated decisions to extension admission/execution, retain factory-bug
hold and retire routes, and prove that each route preserves B's authenticated
owner, cumulative money and ordinary checkpoint path. No activation flag changes,
new launch path, new allowance, or changes to ENGINEERING section 4.

This lane owns diagnosis_dispatch and a small diagnosis_outcomes module. Lane 2
owns extension_package and writer/stress/gate execution. This design is the
coordination contract; neither lane edits the other's checkout. run.py changes
only its existing extension dispatch/execute seam. Cross-batch resume remains
owned by t3/batch-carry-over (new-batch-service-4), using its ordinary verified
bind/install plus retained factory-bug-resumes.json. No duplicate resume counter
or fix-message service is introduced.

## Validated routing and restart

After immutable decision publication, apply persists completed diagnosis state.
For close_to_passing, both fresh and replayed validated decisions return an integer
when DIAGNOSIS_ENABLED is True: existing matching last extension ID (active or
completed), or 0 meaning admission required. Zero is internal control flow, never
persisted history or authority. Match exhaustion_id before routing any existing
row; a prior completed row with a different exhaustion permits fresh admission,
while a mismatched active row refuses. A completed same-exhaustion row requires
lane 2's completed_route validation. Disabled mode keeps today's stop.

Propagate returns through replay, _dispatch and invoke; invoke's finally still
removes the pilot and restores operation/exclusions before writer setup. Dispatch
releases its reconciliation lock before any package work. main retains its
nonordinary-mode refusals and ordinary Compose/model/driver preparation. Replace
its admitted writer-only stop with diagnosis_outcomes.run(c, runner, prev, number).
Skip build and validate_and_repair for this route. Successful package completion
flows to existing final sealing; all errors use existing final accounting and
checkpoint sealing. No route directly publishes to B or books a second ledger.

## Small lane-2 seam

The proposed public package surface is:

* extension_package.entry(c, runner) -> snapshot: code-produced current-version
  scientific entry proof over the current candidate; no writer or mutation of
  candidate bytes. For a first extension it captures the exhausted candidate's
  scientific frontier. For further extensions it verifies or reconstructs the
  preceding retained entry/outcome at a common current version in isolated roots,
  retains the comparison via extensions.retain_comparison, and returns the
  selected outcome with current authenticated source_generation. Invalid or
  incomplete evidence raises extension_comparison_pending; no authored/model
  verdict can serve as this snapshot. This function owns all scientific adapters.
* extension_package.run(c, runner, previous, extension_id): execute or replay the
  admitted single writer/stress/gate package, completing history before raising
  extension_incomplete on substantive failure; all pass returns for ordinary seal.
* extension_package.completed_route(c, row): authenticate committed outcome
  routing when its public card lags, without rerunning work.

Lane 1 never supplies a generic gate evaluator. Until lane 2 ships these entry
points the route fails closed at extension_comparison_pending before admission.
Tests may substitute the package boundary, explicitly not claiming scientific or
integrated qualification. The parent merges lane 2 before integrated activation.

## Admission and one writer

For number 0, authenticate job_authority.for_case, validate completed
close_to_passing diagnosis, read immutable history and reject five prior entries
before scientific work. Call package.entry then extensions.propose: the existing
same-version comparison/progress check enforces no regressions and strict frontier
advance for every further extension. No progress/regression retires; pending stays
pending. Do not reset rounds or history. The proposal chooses builder_rounds+1.

Create the existing writer-intent shape, with round_limit exactly proposal.round,
actor writer, current attack_binding, before_repair_sha256, input_problems from
the code-recorded failed gate/stress evidence, report round-N.json and the existing
release-rereview fields. No diagnosis prose grants execution or becomes feedback.
Call runner.pending_call(..., extension_proposal=proposal) with the ordinary
builder prompt and complete_writer callback. Use on_admitted to invalidate old
gate state only AFTER durable intent/history/receipt and money reservation.
The pending_call seam already obtains the lease, reserves against B's commitment,
retains the exact intent before admission, and publishes the attack receipt.
After completion call package.run on the admitted ID; it validates the completed
writer instead of calling it again. Interruption after admission resumes through
the existing positive-ID route; interruption before admission consumes no ID.
No fixed extension dollars, extra attempt counters or args.rounds mutation.

## Factory bug and retirement

Factory bug continues through diagnosis.persist_factory_bug: private immutable
finding, validated lifetime history, completed diagnosis and factory_bug_held.
Same-batch replay performs no model work. B's later-batch admission owns the
three-resume limit and durable counter increment; this lane does not debit it.
Retire continues to retired_not_converging; limit/progress refusal produces
retired_extension_limit or retired_no_progress. Completed states project no new
replacement or diagnosis. All stops preserve usage and enter the same finally
checkpoint/collection adapter. A held case reaching three resumes must retire
through B's carry-over refusal, not acquire a fourth invocation here.

Waste attribution is an explicit outstanding prerequisite: interfaces section 8
currently mandates empty eligible sets because no code-linked invalid-infra
operation producer exists. This route must not charge all historical case spend
or use model-supplied operation IDs. Existing operational waste stays in the
infra-waste line and total remains cumulative. A separately reviewed producer
and its B resume linkage are required to activate factory-bug reclassification;
this change cannot honestly claim that portion of item 7 closed. The user request
covers it, so completion reporting must identify it until supplied, rather than
silently claim all three routes are fully qualified.

## Deletions, tests and Murphy rows

Delete fresh diagnosis's unconditional close-to-passing stop and the main
writer-only terminal stub. Reuse admission, retained history, package and final
checkpoint. No new persistent schema or configuration.

Tests use saved practice case and 5813be ledger through real pending_call,
reservations, history and checkpoint routing. Model and package output are
substituted controls, not qualification. Prove fresh and replayed decisions route
identically; false activation starts nothing; pilot cleanup precedes extension;
first admission reserves once, restores interruption and never writes twice;
five entries refuse before entry/model; no-progress and regression retire;
version/pending comparison never admits; money/deadline/provider wait never
consume an ID; retire/hold replay never invokes or requeues; held history is
unchanged and all monetary totals survive. Include actual main routing and
checkpoint refusal so model work cannot bypass B. Existing held/extension suites
remain mandatory. Add missing-package refusal until lane 2 is merged.

Run full uv run --with numpy --with scipy python -B tests/run.py, log to a unique
path, wait, commit record; fresh diff goldfish verifies fixes. Supports row 9,
closes none until package + factory-bug attribution + B lifecycle real-artifact
exams prove the full route. new-batch-service-4 stays B-owned.
