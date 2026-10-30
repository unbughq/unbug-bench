# Stream D: first extension writer admission

## Problem and boundary

Worker-dispatch design review 1 B1 identifies a circular admission rule. The
ordinary writer limit is tested in `run.pending_call` before a reservation and
before extension admission. Its only bypass is the mutable, otherwise unused
`c.active_extension_id`. A legitimate first extension has no such attribute;
setting it without verified history would also bypass the ordinary limit.

This increment supplies the first-admission seam, without a production caller.
It removes that attribute bypass. It does not wire the writer loop, recover an
active extension, produce scientific stage receipts, or reconstruct comparisons.
B1's active-resume portion, B2 and extension M5/M6 remain open in
`stream-d-worker-dispatch.md`. The diagnosis dispatcher still stops a completed
close-to-passing result at `extension_comparison_pending`. B's existing
`DIAGNOSIS_ENABLED` stays false. No new launch path, money channel, configuration
field or runtime flag is introduced. The planned work is one implementation
increment followed by its full suite and fresh diff review.

The snapshot supplied here is code-owned data. The seam verifies its shape,
current case bytes, current evidence bytes and eligibility. It cannot certify
that authored stage receipts are real scientific verdicts. Before wiring, the
separate stage producer must establish that property; no model answer may be
passed straight to this interface. Tests explicitly retain that boundary.
Eligibility trusts `diagnosis_state` from B's authenticated restored card, or
the current `diagnosis_dispatch.apply` publication after verified replay. This
seam does not separately read `decision.json`; future callers must preserve that
producer boundary. Adding another producer of completed close-to-passing state
would therefore change the ordinary-budget bypass trust boundary.

The future stage producer must select scientific evidence, excluding admission
and accounting files such as `attack-state.json`, `extension-history.json` and
the live ledger. Those files can change during reservation/admission. This seam
retains the existing snapshot inventory rules; it does not broaden their meaning
into scientific authority or treat every work file as eligible stage evidence.

## Interface and ordering

Add optional keyword `extension_proposal=None` to `run.pending_call`. Existing
callers pass nothing and retain ordinary admission. No production caller is
added in this increment. A non-null value is permitted only for `role='writer'`,
with receipt actor `writer`, a dictionary `binding`, receipt round equal to the proposal round and name
exactly `builder-<round>`. Rounds must be positive strict integers. A first-admission
receipt must contain none of the admission-owned keys `schema_version`,
`operation_id`, `phase`, `lease_id`, `invocation_id`, `resumed_from_wait` or
`extension_id`, even with a null value. In particular, pending, completed and validated receipts refuse as
`extension_reservation_mismatch` before a lease. The seam always generates a
fresh writer operation UUID; it never adopts an earlier ordinary writer's
operation or spending. A preexisting active extension also refuses; continuation
must use the later reviewed path.

Add `extensions.verify_proposal(c, proposal)` as an eligibility check that writes
no files. The existing `read(c)` may normalize `c.card['extension_history']` to
the verified public projection, as it already does for `propose` and `admit`.
It requires the exact proposal key set returned by `propose`, strict integer
extension ID and round, and exact equality with a fresh
`extensions.propose(c, proposal['entry'])`. This invokes the existing independent
job-authority and history checks. In addition:

- `entry.source_generation` equals the current authenticated job source generation;
- `entry.case_sha256` equals `digest(tree(c.case))`;
- every named evidence file is read safely below `c.work` and its digest equals
  the entry's evidence map. Reuse `diagnosis._input_bytes` for no-follow regular
  reads and ancestor checks, rather than introducing another file reader.

Malformed proposal envelopes become `BudgetError('extension_reservation_mismatch')`;
an invalid entry snapshot retains the existing `extension_snapshot_invalid` label.
changed case/evidence bytes become `extension_snapshot_changed`. Existing
eligibility and authority errors retain their labels. For evidence reads,
`FileNotFoundError`, the `_input_bytes` unsafe-path/nonregular `ValueError`
cases and `OSError` with `errno.ELOOP`, `errno.ENOTDIR`, `errno.ENXIO` or
`errno.EISDIR` all become
`extension_snapshot_changed`. ENOTDIR covers an evidence parent replaced by a
file; ENXIO covers a socket/nonregular object rejected by open. EISDIR covers a
directory rejected by `fdopen` before the reader reaches its regular-file check,
as observed in the real-directory refusal control on Python 3.14/macOS.
ELOOP covers a leaf symlink appearing between the ancestor check and no-follow
open. Other filesystem failures, including permission denial and EIO, propagate
as infrastructure, as in the passed diagnosis correction; they are not converted
to sticky history or input errors. Keep the proposal-shape validation separate
from the evidence-read handler so a read's `ValueError` cannot be relabelled as
malformed proposal. This helper writes no snapshot, history or receipt.

All checks and admission stay under the existing `model_runtime.dispatch` lock.
The concrete order in `pending_call` is:

1. Resume/settle old provider work and obtain current `job_authority.for_case`.
2. If a proposal is supplied, check the caller role/name/receipt contract and
   `verify_proposal` before requesting a lease. Keep a deep local copy, so a
   callback cannot mutate the caller's proposal into different admitted data.
3. Request the existing writer lease. Generate a fresh operation UUID for this
   first-admission branch, and scope/restore it with the same existing `finally`
   used by ordinary calls. Ordinary calls retain their existing receipt-based
   operation reuse. Calculate the route maximum.
4. For an ordinary writer, always check the ordinary budget. Ignore any
   `active_extension_id` attribute. For an extension writer, re-run
   `verify_proposal` on the local copy immediately before reservation, because
   the lease wait may have allowed the source bytes or state to change.
5. Call unchanged `budget.reserve_invocation` with the authenticated owner,
   operation UUID and exact builder call name. It enforces known spending,
   outstanding reservations, the committed cumulative total and deadline.
   No per-extension allowance is created.
6. Call `extensions.admit` using that proposal, lease and operation, before any
   callback or writer invocation. Its existing reservation check and immutable
   snapshot copy remain in force. It retains the history before public projection.
7. Add `extension_id` to the local attack receipt. Existing `operation_id` and
   `round` fields name the admitted history's operation and round. Write the
   existing schema-2 pending attack receipt and update `builder_rounds` through
   `admitted()` before calling `on_admitted`. This ordering change applies only
   to the extension branch; ordinary/stress callback ordering stays unchanged.
8. Run the extension branch's optional `on_admitted` only after history and
   attack receipt are durable. A later writer-loop integration must place gate
   invalidation here, never before this function. Then call the unchanged
   `opencode` wrapper, with its existing `before_attempt=admitted` journal hook.

There is no active-extension context attribute to set or restore. The existing
operation UUID is restored in `finally`. The wrapper's fallback leases retain
the same operation and call name and use B's existing money boundary. They do
not call `extensions.admit` again or consume another extension ID. The new
receipt field is private and inert until the separately reviewed continuation
reader consumes it; current production calls do not write it.

## Interruptions and refusals

A provider wait, invalid/stale proposal, expired authority or money refusal
before `admit` leaves no extension history, entry snapshot, attack receipt or
round increment. The ordinary error cleanup still releases a demonstrably
uninvoked lease. A process death after reservation is different: existing
reconciliation may conservatively book the full reservation maximum.

A failure while snapshotting or publishing admission starts no writer and runs
no invalidation callback. Durable history may already exist if publication was
interrupted. The count is not rolled back. A repeat through this first-admission
seam refuses the active extension instead of allocating another ID. The future
continuation path must recover the stored round/operation and repair a lagging
attack receipt, including the history-before-receipt crash window. This increment
does not silently retry first admission on that state.

A handled failure after history publication releases the demonstrably uninvoked
reservation to `state='settled'` with zero estimated gap; it does not leave a
pending reservation just because the history exists. That settled row still
binds the retained operation, and future continuation may reserve a new lease.
A failure after the attack receipt or callback likewise keeps the admitted ID.
Infrastructure failures propagate to existing runner handling. No new stop or
automatic reset is added. Fallback retries within a successfully entered
`opencode` call are its existing logical-call semantics, not active-extension
re-entry.

## Tests and evidence

Extend `tests/factory/test_stream_d_extensions.py` and, where appropriate, the
existing runtime harness. Use the gzip-verified practice case and saved 5813be
continuation ledger already used there. Release/money envelopes, stage receipts,
route maxima and provider output remain explicitly authored test controls. The
router/ledger, snapshot copy, receipt writes and reconciliation run for real;
only the CLI/transport is substituted. No live qualification is claimed.

- Lower the ordinary limit below the saved ledger's known spending. Ordinary
  `pending_call` refuses `budget_exhausted`, including when
  `c.active_extension_id=1` is forged. A valid first proposal with enough existing
  B commitment reaches one writer invocation, one reserved operation, one retained
  immutable entry and one extension ID. Assert history and attack receipt are
  present before the callback and CLI, and contain the same round/operation/ID.
- Wrong role, name, round, extra proposal keys, wrong exhaustion, changed source
  generation, active history, changed case and missing/changed evidence refuse
  before any new lease or reservation. Receipts containing any admission-owned
  key listed above refuse `extension_reservation_mismatch`, including a pending ordinary
  writer operation already bound to a settled reservation and null-valued keys.
  A malformed entry keeps `extension_snapshot_invalid`. Symlinked/nonregular
  evidence, a parent replaced by a file, and injected open ELOOP/ENXIO refuse
  specifically `extension_snapshot_changed`. Inject ELOOP only at the read
  boundary, while exercising the real reader for actual symlink/FIFO controls.
  Assert unchanged case/evidence/history/round/attack receipt and zero callbacks.
- Mutate the case, evidence or diagnosis during a substituted `await_lease` return.
  The second verification refuses before reservation and releases that lease.
  This must kill deletion of the post-wait verification.
- With a valid proposal but insufficient committed total or unknown spending,
  B's reservation refuses `money_wait`; no extension is created. Expired or absent
  current authority refuses before router admission. The provider-wait control
  also creates no extension. None of these tests replaces `reserve_invocation`.
- Interrupt after the real reservation but before `admit` without executing the
  normal exception unwind (a separate child process or a direct captured durable
  ledger image at that boundary). Run the existing reconciler. Assert no history,
  no writer, and conservative accounting, not zero cost.
- Interrupt history publication and attack-receipt publication independently.
  Assert no writer/callback, at most one retained ID and no ordinal reuse. After
  handled publication failure, assert the uninvoked reservation is settled with
  zero estimated gap. A fresh
  first-admission attempt refuses the active row. The tests explicitly do not
  claim continuation recovery.
- Force one admitted provider fallback through the existing runtime harness.
  Both reservation rows use the same operation and builder name, and history
  still has one row. Assert operation scoping restores on success and failure.
- Inject `PermissionError` while preflight reads valid evidence and `OSError`
  while saving the admitted entry/attack receipt. These propagate as infrastructure
  with no writer, rather than being reclassified as malformed proposals.
- Keep the existing diagnosis gate-false main-entry test: close-to-passing still
  stops without reaching `pending_call`. Add an assertion that there is no
  production caller supplying `extension_proposal` in this increment.

Run the full suite and obtain a fresh goldfish diff review before reporting the
increment passing. No Murphy row closes: the stage receipts are authored and the
extension dispatcher, real Unix isolation, live provider and B runtime remain
unqualified. This deletes the attribute-based bypass and adds no module or
dependency. Cost is two bounded reads of the current case/evidence per first
admission, plus the existing immutable copy after reservation. Each `propose`
and `admit` also verifies retained history snapshots: at most five prior rows,
plus their retained comparison pairs. These are existing verification reads,
not a new history cache or trust shortcut.

## Implementation boundary

The first-admission seam is implemented in `extensions.verify_proposal` and the
optional `run.pending_call(..., extension_proposal=...)` branch. There is still
no production caller. The old context-attribute bypass is removed; ordinary
writer calls always enforce the ordinary limit. The existing stress callback
order, reservation wrapper and continuation paths are unchanged.

`tests/factory/test_stream_d_admission.py` adds 18 offline controls using the
fixtures and substitutions described above. The combined admission, extension,
runtime and diagnosis-dispatch run passed 100 tests. The first focused run
exposed the directory EISDIR behavior documented above; its real-reader control
now passes without changing the shared reader. Full-suite and fresh diff-review
results belong in the review record. No Murphy row closes and no live extension
or money activation is claimed.

Diff-29 N1 follow-up checks `binding` before the lease, so a missing/non-dictionary
binding cannot consume an extension ID before the attack receipt fails. Its
regression control requires `extension_reservation_mismatch` with no lease,
reservation, history, receipt, callback or writer. This obvious one-line guard
uses ENGINEERING's small-fix exception to a separate design review; it still
requires the full suite and a fresh diff review.
