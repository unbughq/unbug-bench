# Partial first-entry reconstruction

Implements the approved recorded-traversal slice in stream-d-partial-entry.md.
A missing close marker no longer discards a verified contiguous prefix. Only a
prevalidated missing record becomes unreached; corrupt proof, later records and
checkpoint pass/fail labels still hold. G3 versions are pinned after restoring
workers on the copied context. Case coverage excludes freshness for historical
records, while the last record and retained G2/G8/G9 must match live freshness.
No evaluator, setup, model call or new score is introduced.

Focused validation: tests/factory/test_stream_d_entry.py, 19 tests passed.
Tests run real saved G4/G5 executions and ordinary capture, cover infrastructure
proposal admission, stale checkpoint scores, optional/malformed close markers,
G3 absence/corruption, staging leftovers, and authored G2 freshness mutation.
The exact three prior hold expectations change as the approved design specifies;
other route, attribution and retry assertions are unchanged.

Parent explicitly waived waiting for land12: this branch contains its same
rejected-writer work. Full locked suite and fresh diff review remain required.
No Murphy rows close. Legacy evidence adapters (4–7h) and all-outcomes integration
(4–6h, including irrelevant-edit progress checks) remain separate increments.
No activation or three-case pilot is performed here.

First locked run was interrupted safely before its outer deadline after about
88 minutes in the shared-lock queue. Record adca5675 retains exit 70, null final
counts and the complete partial log; it is not claimed as a pass. The suite tree
was stopped before lock release, and a fresh full locked run follows.
