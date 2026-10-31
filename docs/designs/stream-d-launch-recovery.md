# Stream D item 7: recover admitted writer intent at launcher entry

## Problem and scope

The ordinary launcher dispatches authenticated diagnosis resumes before Compose,
model selection, build and gate repair. Its verified close-to-passing replay
always stops without calling the durable writer selector. Admission interrupted
between history and attack receipt publication is recoverable by a helper but
not by an actual checkpoint launch.

This bounded launcher-routing increment wires recovery into that existing path.
It does not execute extensions, admit new ones, complete round-limit routing,
change stress handling, or turn diagnosis on. Package execution and final outcome
routing remain subsequent work. No section 4 or security rule changes.

## Change and deletion

In diagnosis_dispatch.apply, after verifying the retained result and applying
its completed state, for close_to_passing call extensions.writer_receipt if
extensions.active returns an active row. Do this before publishing scorecard so
repaired builder_rounds is durable with the stop. The existing dispatcher holds
the reconciliation lock and has verified job authority, settled provider waits
and reservations, history, frozen inputs, journal and decision/raw answer. Never
recover intent before those checks. Public diagnosis labels cannot trigger it.

The selector verifies exact writer identity and reservation binding, restores
missing/predecessor receipts, preserves pending/completed/validated phases, and
never invokes a writer. Same-round stress returns None: leave bytes untouched
and stop, granting no stress or gate authority. No active row means keep the
comparison-pending stop without consulting intent. Other outcomes keep existing
routes. All extension paths stop extension_comparison_pending before ordinary
build/repair. The disabled activation flag remains unchanged; recovery is
model-free.

Missing or invalid intent refuses extension_reservation_mismatch. Permission/EIO
propagates as infrastructure. No legacy migration guesses intent. No new config,
module, file format, public marker, launch mode or budget bypass. Delete the
launcher's unconditional bypass of recoverable intent; reuse the selector.
Cost is bounded history/receipt reads, no inference.

## Tests

Extend tests/factory/test_stream_d_dispatch.py over its saved practice tree and
5813be ledger. Release/model controls and stage judgments are authored; real
snapshots, reservations and receipt producers run. Update active-admission
controls to retain intent before history, matching pending_call, never create
intent on replay. Explicitly test older active history with missing intent.

Exercise dispatch and run.main subprocess with Compose, build, gate repair,
model selection and role setup forbidden. After verified close-to-passing and
real admission, leave attack receipt unpublished. Launch must recover the exact
intent and round, stop comparison-pending, keep reservations/history/snapshots
unchanged. Repeat to prove idempotence. Existing selector tests cover predecessor
and provider-wait details; new tests establish production call ordering.

Preserve completed/validated receipts byte-for-byte and same-round stress bytes
without interpretation. Missing intent refuses. Corrupt retained diagnosis must
refuse before receipt repair. Inject selector PermissionError: it propagates,
not diagnosis_input_invalid. No-active close-to-passing, factory bug and retire
keep existing routes. No live qualification claimed.

Run the full suite to a unique log, wait for exit and commit the record. Fresh
design/diff reviews and fresh re-review after blocker fixes are required.

## Murphy rows and remaining work

No row closes; row 9 still needs exactly one writer/stress/gate package, freshness,
unfinished stress, comparisons and automatic lifecycle qualification. Lane 1
owns row 13. Before item 8 finish launcher execution/round-limit routing, package,
all diagnosis outcomes and qualified-path legacy allowance removal. Item 8 needs
retained-artifact and authorized live A/B/E qualification before activation.
This increment does not complete item 7 or authorize live cases.

## Design review clarifications

Nothing is deleted in code. Insert after the stopped-card update, immediately
before scorecard publication. The dispatch stress-publication drain remains an
intended invariant: if a marker is pending it may checkpoint before receipt
selection. No inference starts. Receipt bytes themselves remain untouched on
the stress branch. No production path admits extensions yet; missing old intent
therefore fails closed rather than being a supported live migration.

Use real pending_call interrupted at attack receipt publication to retain intent
and admit history. The main harness gets an active fault mode expecting
extension_comparison_pending and the admitted round. First replay may settle
a pending reservation conservatively; assert no new reservation identities and
then unchanged reservations on replay, rather than asserting no reservations.

This increment takes one implementation/full-suite/review cycle. Principal risks
are repairing before diagnosis verification, silently rewriting completed work,
and relabeling I/O as invalid diagnosis; the negative controls target each. Its
impact is a tested launcher recovery seam for later integrated qualification,
not a live operational fix. The saved ledger is from historical case 5813be;
lane 1 is the ordinary retry/stress worker; A/B/E qualification means the router,
batch-money/launcher, and isolation/control dependencies.
