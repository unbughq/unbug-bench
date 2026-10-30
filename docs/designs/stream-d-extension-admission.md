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
field or runtime flag is introduced.

The snapshot supplied here is code-owned data. The seam verifies its shape,
current case bytes, current evidence bytes and eligibility. It cannot certify
that authored stage receipts are real scientific verdicts. Before wiring, the
separate stage producer must establish that property; no model answer may be
passed straight to this interface. Tests explicitly retain that boundary.

## Interface and ordering

Add optional keyword `extension_proposal=None` to `run.pending_call`. Existing
callers pass nothing and retain ordinary admission. No production caller is
added in this increment. A non-null value is permitted only for `role='writer'`,
with receipt actor `writer`, receipt round equal to the proposal round and name
exactly `builder-<round>`. Rounds must be positive strict integers. A receipt
marked `completed` or `validated` refuses this first-admission path. A preexisting
active extension also refuses; continuation must use the later reviewed path.

Add `extensions.verify_proposal(c, proposal)` as a read-only eligibility check.
It requires the exact proposal key set returned by `propose`, strict integer
extension ID and round, and exact equality with a fresh
`extensions.propose(c, proposal['entry'])`. This invokes the existing independent
job-authority and history checks. In addition:

- `entry.source_generation` equals the current authenticated job source generation;
- `entry.case_sha256` equals `digest(tree(c.case))`;
- every named evidence file is read safely below `c.work` and its digest equals
  the entry's evidence map. Reuse `diagnosis._input_bytes` for no-follow regular
  reads and ancestor checks, rather than introducing another file reader.

Malformed proposals become `BudgetError('extension_reservation_mismatch')`;
changed case/evidence bytes become `extension_snapshot_changed`. Existing
eligibility and authority errors retain their labels. Missing evidence is
changed evidence. Non-missing filesystem failures propagate as infrastructure,
as in the passed diagnosis correction; they are not converted to sticky history
or input errors. This helper writes no snapshot, history or receipt.

All checks and admission stay under the existing `model_runtime.dispatch` lock.
The concrete order in `pending_call` is:

1. Resume/settle old provider work and obtain current `job_authority.for_case`.
2. If a proposal is supplied, check the caller role/name/receipt contract and
   `verify_proposal` before requesting a lease. Keep a deep local copy, so a
   callback cannot mutate the caller's proposal into different admitted data.
3. Request the existing writer lease. Scope the existing operation UUID exactly
   as today. Calculate the route maximum.
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
  generation, completed receipt, active history, changed case, missing/changed
  evidence and symlinked evidence refuse before any new lease or reservation.
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
  Assert no writer/callback, at most one retained ID and no ordinal reuse. A fresh
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
admission, plus the existing immutable copy after reservation.
