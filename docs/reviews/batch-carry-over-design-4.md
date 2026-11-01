**Verdict: PASS.** No blocking finding is open in `docs/designs/batch-carry-over.md`, including the "Design 4 exact integration decisions" section (lines 360–418). D3-B1 is fixed, and each of M1–M4 now has a concrete decision that matches the code. Below are two Majors and five Nits. None of them blocks; they can be fixed during implementation and checked at diff review.

This was a read-only review at baseline 0d6d737 plus the working-tree docs. I made no writes and started no workers or subagents. I made no paid calls. I read:
- the three personas and the three standards;
- ENGINEERING.md;
- interfaces §8 (lines 505–525);
- review 3;
- the code: `batch_money.py`, `batch.py:bind`, `batch_holder.py`, `batch_service.py`, `key_holder.py` (policy_load, orphan resume, legacy launch at 637/705), `diagnosis_dispatch._dispatch`, and `job_config.py`.

## Review 3 findings against the code

| Finding | Status | What I checked |
|---|---|---|
| **D3-B1** (legacy path with the holder disabled) | **Resolved** | The legacy launch calls `bind` (`key_holder.py:637`) and then `authorize` (`:705`). Both now refuse `carry_from` and derived names before any money is read or created. The non-holder branch of `bind` keeps its same-release check (`batch.py:163-167`). `HOLDER_ENABLED` is unchanged. Schema-1 money sources refuse, with no migration. Each refusal has a test. With both refusals in place, no legacy route can give fresh money or start a case twice. |
| **D3-M1** (reading the frozen source) | **Resolved** | `batch_transfer.source()` checks that `export.json` and `import.json` are identical bytes before reading. It takes no lock while it reads the immutable source files. The callers (`_post`, `reserve`, `source_directory`) hold only the target lock, so lock order cannot invert. The only code that takes two locks is the prepare/repair path, and it takes them in name order. I grepped every writer of `current/`, `outbox/` and `generations/`: all are in the holder or service, under `money.locked`. With the freeze, none can run after export. The `sources[-2]` exception is limited to the imported base, which matches `batch_holder.py:174/219`. The `load_locked` rule `sources[0] is None` is replaced by the import.json-proof rule (lines 171–177). |
| **D3-M2** (queue for an imported queued child) | **Resolved** | The queue row has the exact eight fields that `_load` requires (`batch_service.py:131-140`). `_load` checks replacement rows against the union of local derivations and `imported_derivations`. Replaying the import keeps the existing sequences. The imported child goes through `reserve(child, None)`. That call finds its imported money row with `sources == [None]` and returns the imported authority without creating new money. `_post` then accepts `sources == [None]`. |
| **D3-M3** (re-exporting an import that never launched) | **Resolved** | The design now explicitly refuses this. It records the result as a liveness limit, with accounting still intact. |
| **D3-M4** (full resolver swap) | **Resolved** | Every path that interfaces §8 lists is in scope: the root-count caps (`batch_money.py:43-44`, `key_holder.py:126`), the orphan-resume `policy_job` check (`key_holder.py:606`), `account_handoff`, `coordinator_inventory`, `channel`, `bind` and `install`. Legacy `authorize` still refuses derived names. That fits §8's rule that only the holder's verified journal can admit a derived job. |
| Review 3 Nits | Resolved | Status is `running`, which existing cards already use (e.g. `run.py:2242`). The test file is `test_stream_d_held.py`, which exists. Dispatch order now matches `_dispatch` lines 287–292. The `restore_recipient` pin also lines up with the check in `manifest()` (`batch_money.py:80`). |

These constraints hold:
- The same continuing case gets a new reservation.
- Causal sets stay empty and nothing invents attribution.
- At most 3 lifetime admissions; the fourth becomes `retired_factory_bug_limit`.
- Murphy row `new-batch-service-4` stays open; it is still open in `murphy-register.md:67`.
- Activation and real-artifact closure stay separate gates.

## Majors (non-blocking)

**F1. The design gives two conditions for moving a queued (null-generation) child again, and they disagree.** Line 155 versus lines 399–400.
- Line 155 allows a null generation only with "no ever-created operation".
- D3-M3 allows a move when the reservation "has never created a worker".
- Here is where they differ. Say B ran `reserve(child, None)`, so an operation exists in `reservations.json`, and that operation then positively failed before creation. One rule refuses the move; the other allows it.
- Money is safe either way: the commitment is carried and no work was done. But the implementer has to choose, which breaks the zero-decision rule.
- **Fix:** pick one rule. The simplest is to refuse whenever B has any operation for that child, which matches the non-null refusal in D3-M3. Add one test.

**F2. Importing a derived job depends on the target's `replacement_policy` setting, and the design doesn't say so.**
- `resolve_job` raises `replacement disabled` for any name ending in `-rN` unless `replacement_policy.enabled` is set (`batch_service.py:31-33`).
- Line 100 says imported names take their case and commitment from the pinned `carry_from.jobs`. It does not say whether the enabled check still applies.
- **Fix:** state that a target whose `carry_from.jobs` includes derived names must set `replacement_policy.enabled = true`, or refuse. Refusing is the safe default.

## Nits

- Line 3 still says "Design 3". It should say Design 4.
- Lines 330 and 334 still carry the old "or discovered" wording for the test file and the old "omit status" option. The Design 4 section overrides both, but replacing the original text would remove two contradictions a reader could trip on.
- D3-M2 says "holder.reserve consumes that child". In practice the queue is only ordering data (`ordered_queue`), and nothing removes a row when it launches. The coordinator still has to request `reserve(child, None)`. Reword it, and have the test assert that the row stays and that a second reserve replays the same operation.
- Every `reserve` on a carried target goes through `prepare`, which takes both locks each time, even when the import is already in place. That is correct, but say it is intended so nobody adds a fast path that skips the check that export and import match.
- On altitude: the body (lines 30–358) still mixes architecture with field-level detail. The Design 4 section is the clearest part. If any of this text moves into the interfaces addendum, lead with the Design 4 decisions.

**Next:** implementation can go ahead. Fix F1 and F2 in the design or the code; the diff review checks both. Per ENGINEERING §1, save this review verbatim as `docs/reviews/batch-carry-over-design-4.md`. I did not save it, because this review was read-only.
