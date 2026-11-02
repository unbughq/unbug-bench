**NOT PASS.** One blocker is open: the test that is supposed to close the Murphy row can't be built from the fixtures the design names. This is final design round 2 of 2, so under the design's own rule it goes back in three lines.

Checked at 789f588 in t3-21bef30c, read-only. No tests, writes or network calls.

## What I confirmed independently (not taken from round 1)

- **Replaying the original decision works across batches.** `queued_inputs` with an existing manifest only checks the frozen inventory and the pending frozen card. `replay` and `validate_result` check against that manifest's own generation. `journal` checks against ledger reservations. None of them compares X against the new owner.
  - After X is restored, `apply` routes correctly: no matching history row goes to 0, an active row goes to `writer_receipt`, a committed row goes to `completed_route`. With diagnosis disabled it still stops at `extension_comparison_pending`.
- **The restore can be atomic with the clear.** `resume_factory_bug` builds `admitted_card` and publishes it with one `atomic_json`. Setting X there sits in the same write.
- **Crash after the clear needs nothing new.** `resume_factory_bug` returns False when the outcome is not `factory_bug`, and `_dispatch` already falls through to replay.
- **Rebasing `_dispatch` onto the restored card is safe.** Its local `previous` and `state` are only used for `card_total`, the pending check and the completed/invalid check. `c.checkpoint_card` has no later reader on this path; the remaining readers are `job_config` install and the factory-bug producers, none of which run here.
- **Retirement keeps its priority.** The `len(history) == 3` retirement runs before the proposed check on the new-admission branch. `FactoryBugHeldWait` is a `BudgetError`, which subclasses `RuntimeError`, so the outer `except (ValueError, …)` does not swallow it.
- **No new routing, counter or allowance is added.** B2's retry rule matches the code: `run_validity.retry` keys on `runtime_revision()`, which hashes `Path(__file__).parents[1]/factory/*.py` and is `lru_cache`d. So rebinding `__file__`, editing a copied file and calling `cache_clear()` is a workable way to change the runtime revision in a test.
- **A stale record is still routed correctly.** After N+1 completes, W is a factory bug and X validates again. `completed_route` replays N+1, the stop is `extension_incomplete`, and `record_exhaustion(new_exhaustion=True)` creates a fresh pending W2. That matches M4 and does not livelock.

## Blocker

**B1 — The row-closing final exam is not executable as pinned, and two pinned names are wrong** (implementation_readiness; design lines 127–137, 154–169)
- **`check_handoff` is not real comparison exhaustion.** `DiagnosisBoundaryTests.check_handoff` (test_stream_d_comparison.py:615):
  - writes the close_to_passing state by hand;
  - builds the evaluator with `Evaluator.__new__` and placeholder identity and versions (`'a'*64`, `'b'*64`);
  - retries an authored `failed()` against `infra-attempts.json`.

  It never runs `subsequent_entry`, so it never uses the `pair-attempts.json` journal keyed on `runtime_revision`. That is the exact path B2's changed-revision and unchanged-revision exams must prove.
- **The `ComparisonTests` X is hand-written too.** `ready()` calls `ExtensionTests.diagnosis()` (test_stream_d_extensions.py:45), which writes the X state directly. There is no `decision.json`, `attempts.json` or frozen manifest, so the real `_dispatch` replay would refuse it (`bound diagnosis lacks manifest`, ending in `diagnosis_input_invalid`).
- **The two fixture worlds don't fit together.** `ComparisonTests` is built on `CompareTests` and `RuntimeTests` (rehearse_only, its own source copy, patched `gate_state`). `DispatchTests`, `ResumeTests` and `DiagnosisBoundaryTests` are built on `InputTests`. No existing test combines:
  - a real X decision through queued_inputs/journal/decision/apply,
  - a real completed extension, and
  - a real `package.entry` comparison exhaustion

  in one tree. InputTests-based tests only use the hand-built `ExtensionTests.snapshot` (test_stream_d_dispatch.py:316, :523; test_stream_d_inputs.py:520). How to combine them is left to the implementer.
- **`DispatchTests.main_stop` does not exist.** The subprocess harness is `main_resume`. Its `admit-comparison` fault replaces `extension_package.entry`, and its `held:` fault replaces `dispatch` entirely, so it can't reach the real restore path as written.
- **Requested fix:**
  1. Name one base fixture and the exact sequence in one tree: real extension 1 admit/complete; X produced through the labelled CLI control and the real decide/apply flow; real `package.entry` exhaustion using the `ComparisonTests` transport failure control (the pattern in `test_two_child_deaths_queue_stress_diagnosis` / `test_gate_exhaustion_has_valid_owner_marker`, not `check_handoff`); Y frozen.
  2. Correct the harness name to `main_resume` and say which faults the new main test adds.
  3. If combining the fixtures is not feasible, say so now and drop the row closure from this increment, rather than relying on the "leave it open" fallback.

## Major

**M1 — The `extension_resume_previous` override isn't needed and can drop real writer feedback** (zoom_out; design lines 81–91)
- `writer_feedback` (run.py:1138) reads only `failed_gate` and `failed_detail`. `write_and_attack` reads only candidate and model fields from `prev`. Neither reads `infrastructure_gate`.
- `subsequent_entry` sets `failed_gate=None` and pops `failed_detail` and `infrastructure_gate` before any comparison attempt (extension_package.py:610–611). So a Y that comes from comparison exhaustion already gives no feedback through the original `prev_card`.
- When the pair already exists (no reset), Y can carry X's legitimate science `failed_gate`. The uninterrupted path would pass that to the writer; `admitted_card` drops it.
- **Fix:** delete the attribute and the `getattr` in main. Keep `prev_card`, and assert in the main test that it has no infrastructure-derived feedback.

**M2 — The "actual release carry" claim is only proven in place** (design lines 150, 178–179)
- `ResumeTests.transition` rewrites the authenticated config, money history and batch manifest in the same work dir. There is no checkpoint archive or restore, and no ledger re-import through `restore_ledger.authenticate`.
- So surviving the X journal, decision and reservations is proven only in place. A real carry failure would refuse safely (journal → `invalid`), not mis-route.
- **Fix:** either add a real archive and restore round trip on the saved 5813be bytes, or reword line 150 and the risk paragraph to say "in place" and leave real carry as a named, unproven limit.

## Nits

- **Record read errors.** The private record's read and parse errors (`OSError` from `_input_bytes`) must be caught inside `_extension_resume_state` and turned into `extension_resume_target_invalid`. Otherwise the outer handler relabels them `factory_bug_resume_io_wait`.
- **Permanent holds.** An invalid or missing record leaves a permanent `factory_bug_held` with that wait reason, so every later batch retries it at no cost and never succeeds. Say so in the design.
- **Heilmeier.** The text after the objective still uses undefined shorthand (B, X, Y, "admission", "lane"). "Who cares" is only implied.

## Scope

- **Scope is honest:** only the return after a completed extension, no active-extension diagnosis production, diagnosis stays disabled, no lane 2 or legacy reconstruction.
- **Process is correctly stated:** merge factory-simplify after land10 and before handback, run the full suite under `lockf`, fresh diff review.

## Elephant disposition

Accept B1, M1 and M2; reject no finding. The named fixtures do not yet specify one executable decision/extension/comparison chain, and the main harness was misnamed. The proposed previous-card override must be removed because it can discard legitimate feedback; the existing comparison path already clears infrastructure feedback. In-place owner transitions must not be described as an archive/restore proof. Record-read error mapping and permanent held-state limits also need explicit treatment. No implementation or test work begins. Final design round 2 did not pass; stop and hand the remaining blocker back to the parent under its two-round cap. Murphy new-stream-d-current-comparison-1 remains open. No suite was run for this design-only increment.


## Parent decision: parent-approved after round 2

The parent approves the design logic, with no third design review. B1's combined
fixture and row-closing exam is deferred, not rejected as solved. Implement with
focused existing-fixture unit tests and label authored states/seams honestly.
Keep new-stream-d-current-comparison-1 OPEN; add the exact retained-artifact chain
to item 8. Accept M1 (remove previous-card override) and M2 (in-place transition is
not archive/restore evidence). Map target read errors explicitly and document
permanent held-state limits. Full suite under shared lock and max two fresh diff
reviews remain required. This supersedes the prior stop disposition.
