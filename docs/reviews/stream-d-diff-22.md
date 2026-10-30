I'm returning the review below. It passes this unwired slice with no blockers. One major finding has to be fixed before the dispatcher is wired, and there are two nits.

I made no writes or commits in the worktree; `git status` still shows only the excluded `.stream-d-next/` drafts. I ran the 13 input tests and four probes of my own offline, and all of them passed. I did not run the full suite.

---

# Stream D diff review 22: queued diagnosis inputs

**Reviewer:** fresh goldfish (Opus 5.5), personas `zoom_out` and `implementation_readiness`, Mode: REVIEW, against `implementation-readiness-standard.md`.
**Scope:** commit `ebf3b1a9ead685237f80283dc34a56c8da95ea9f` against `d424af6`. The review covers the new queued-input code in `factory/diagnosis.py`, `tests/factory/test_stream_d_inputs.py`, and the "Queued input implementation boundary" section of `docs/designs/stream-d.md`.
**Read:** `docs/ENGINEERING.md`, persona files, the readiness standard, `docs/reviews/stream-d-diagnosis-input-design-3.md`, the queued-inputs section of `docs/designs/stream-d.md` (lines 1268–1455 at ebf3b1a), `docs/reviews/stream-d-diff-17.md` and `docs/reviews/stream-d-diff-19.md` with their responses, and the helpers the code reuses (`gate_state.inventory/save/load`, `extensions.read`, `job_config.read_file`, `registry.atomic_json`, `budget` reservations). I excluded the `.stream-d-next/` drafts.

## Verdict

**PASS for the unwired slice. There is no blocking finding.** Ma1 below must be fixed before the dispatcher calls `queued_inputs`. That is the same condition review 17 set for its Ma2. The slice claims no dispatcher wiring, no isolation, no money admission and no Murphy closure, and the diff matches that boundary: `queued_inputs` has no caller outside the tests.

## What was verified

- **Boundary.** The only production change outside the new helpers adds `diagnosis_input_invalid` to the excluded stops in `exhaustion()`. With that stop set, `exhaustion` is false and `pending_projection` returns None, even when an infrastructure marker remains. `record_exhaustion(new_exhaustion=True)` keeps the state and ID. `assert_invalid` checks all four of these on every refusal path.
- **Manifest.** The key set is exact, `schema_version` must be the int 1, and case and exhaustion ID must match the current pending state. The generation is the authenticated `source_generation` from the first creation. `files` must equal a fresh re-hash of `inputs/`, so missing, changed or extra files all refuse. A manifest that agrees with a damaged tree still has to pass `_verify_input_records`, which needs nonempty `case/` and `source/`, a pending frozen card bound to the generation and exhaustion ID, a settled ledger, stop evidence, and resolved gate-cache references. The test `test_self_consistent_manifest_cannot_drop_required_input_records` covers this.
- **Replay across generations.** `test_frozen_evidence_survives_live_usage_and_later_generation` interrupts the write of `scorecard.json`, appends to the live ledger, and advances the source generation to `'c'*64`. After that, the manifest is unchanged, the same `finding.json` replays without a model, and the case ends `factory_bug_held`. Review 17's Ma2 required replay from the immutable snapshot rather than the live ledger. This test shows the snapshot behaviour that requirement asks for.
- **Orphan semantics.** A missing manifest is re-staged only while the state is still pending and nothing has bound to the exhaustion. Any of these counts as bound and makes the case `diagnosis_input_invalid`: a `finding.json`, any `raw-result-*.json`, or a ledger reservation named `diagnosis-<id>` or `diagnosis-<id>-repair-N`. Reservation rows stay in the ledger after settlement (`budget.py:156–175` never removes them), so the check still sees them later. On re-staging, existing `inputs/` and staging directories are removed and current bytes are copied. The manifest is written last, after every file is fsynced, all staged directories are fsynced deepest first, the `os.replace` runs, and the parent, `diagnosis/` and `work/` are fsynced. `atomic_json` fsyncs both the file and its directory.
- **Source selection.** The release digest must match between the authenticated config and `args`. The code then follows batch-release, then worker-release manifest, then the selected file list (`factory/*.py`, `factory/prompts/*.md`, and the `bin/` files in `WORKER_BENCH`). Each file is read through `job_config.read_file` (`O_NOFOLLOW`) and must match its digest. An empty selection refuses.
- **Stop evidence.** For a late defect, the copied `late-defect.json` must match both the stop's gate and the marker's gate and digest. For `extension_incomplete`, `extensions.read` runs on the frozen work and ledger, and requires a non-null last outcome and a matching public history. For `infrastructure_exhausted`, the marker must say `exhausted is True` with a gate in `GATES`. My probe confirmed that a missing marker raises `KeyError` and refuses.
- **Refusal surface.** One `except` covers `OSError, ValueError, KeyError, TypeError, AttributeError, BudgetError`. It sets `status: stopped` and `terminal_stop: diagnosis_input_invalid`, sets `c.stopped`, and leaves `diagnosis_state` as it was. A failure inside `job_authority.for_case` sits outside the `try`, so it surfaces as its own `BudgetError` (`money_wait` in my probe) with no terminal stop. That fits the design, because authority is B's channel and not an input defect.
- **Required tests from input design 3.** Every item has a test:
  - freeze, interrupt, append, then replay;
  - corrupt frozen input, including with an infrastructure marker;
  - manifest removed after a finding and after a completed hold;
  - raw-result-only and reservation-only binding;
  - pre-manifest orphan re-staging after settlement, with the manifest written last;
  - initial generation missing or mismatched;
  - G4/G6 late-defect receipts with no gate-details file, plus missing, wrong-gate and wrong-digest cases;
  - completed extension outcome bindings and snapshots;
  - the infrastructure marker;
  - gate-cache references and agreement of restored `bench-results`;
  - release digest mismatch and selected-file symlinks, with exclusions kept out;
  - budget and stress minimum inputs, and the quiescence flag;
  - unchanged replay across a later generation.

  `test_stream_d_held.py` already asserts None projections for invalid history.
- **Real artifacts.** The tests use the gzip-verified practice case bytes and the saved 5813be `continuation_budget` ledger. The release and lifecycle envelopes are authored, and the module docstring and the design's boundary section both say so. Shipped source bytes are copied from the repo and checked against `worker_release.source_files`. Nothing claims live qualification.
- **Run:** `uv run --with numpy --with scipy python -B -m unittest tests.factory.test_stream_d_inputs -v` ran 13 tests, all OK. I also ran four probes subclassing `InputTests`, with all 16 tests OK. The probes are in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/c6b1a458-d920-4e6f-8615-90b5e57760d5/scratchpad/probe22.py`.

## Findings

### Blockers

None.

### Majors

**Ma1. A stale gate-cache record makes ordinary exhausted cases unfreezable. Required before dispatcher wiring.**

`_verify_input_records` refuses when any reference in any copied `work/gate-cache/*.json` points to a file that was not copied with the stated hash. The design asks for exactly that ("Every evidence reference in a copied gate-cache record must resolve…"). The code matches the design, so the problem starts in the design.

Cache records are never invalidated, though:
- `gate_state.save` writes only when a reusable gate passes and its fingerprint is unchanged (`gate_pipeline.py:42–60`).
- When the gate later re-runs and fails, `gate-details/<gate>.json` and its bench results are overwritten, but the old record stays.
- `gate_state.load` handles this by returning None (`gate_state.py:225–237`).

The case that passes in an early round and fails after a later builder round is exactly the population that reaches `budget_exhausted`, `stress_review_unresolved:rounds_exhausted` or `extension_incomplete`. All of those cases would stop as terminal `diagnosis_input_invalid`, and repairing them needs an operator correction. That stalls the batch, which the target properties forbid.

- **Probe:** `test_stale_cache_after_failed_rerun` in the probe file. A G4 cache records `gate-details/G4.json`, the file is then rewritten as a failed re-run would, and `freeze()` raises `diagnosis_input_invalid`.
- **Why the tests miss it:** none of them has a multi-round work directory in which a cached gate later failed.
- **Fix (amend the design, then a small code change):** apply the same rule as `gate_state.load`, so that a record whose evidence no longer verifies against live work is not authority. There are two options:
  - leave stale records out of the frozen copy;
  - copy them but verify only the records whose evidence resolves.

  Either way, the strict check stays in place for the frozen-versus-manifest comparison, which already catches tampering with the tree. Add a control test that reproduces the pass-then-fail-then-exhaust sequence.

### Nits

- **N1. Settlement is checked only through `ledger.active`.** A reservation row still in `state: 'pending'` freezes without complaint (probe `test_pending_reservation_not_refused`). The design says the ledger must be "reconciled before reserving". Today that rests on the caller's `quiescent=True`. The dispatcher slice should either refuse pending non-diagnosis reservations here or document that the caller guarantees it.
- **N2. `_input_bytes` checks for symlinks with `is_symlink`/`stat`, then calls `read_bytes()`, so it can race.** `job_config.read_file` already does the same job with `O_NOFOLLOW`, `fstat` and `S_ISREG` on a single descriptor. Reusing it, or a small `fd`-based read, would remove the race and drop the hand-rolled stat logic. Under the quiescent precondition this cannot happen in practice, so it is optional.

## Claims check

- No dispatcher, model invocation, process isolation or money admission is enabled. That matches the boundary section and `queued_inputs` has no production caller.
- No Murphy row closes. This matches the commit and the design.
- Review 17 Ma1 stays resolved by review 19. Review 17 Ma2 now has its producer, the immutable snapshot creator and verifier. The dispatcher still has to call `queued_inputs` before it replays a finding, reserves money or invokes a model. Ma1 above must be fixed first.

## Elephant resolution

PASS accepted only for the unwired ebf3b1a slice. Ma1 accepted: stale gate-cache
records are optional reuse hints, not required diagnosis authority. Amend and
review the input design before omitting unverifiable cache records at creation;
keep frozen inventory verification strict. N1 remains a dispatcher obligation:
reconcile before snapshot creation and prove it with integration tests. N2 will
use a descriptor-based regular-file/no-follow read. No finding is rejected.

The parent separately identified the archived-card generation mismatch; the
accepted correction is proposed in 17cd006 and needs focused design review before
implementation. Thus this review does not qualify ebf3b1a for dispatcher wiring.

Verification discrepancy: the verbatim reviewer text reports 13 input tests;
the pinned file contains 12 test methods, and the writer's run reports 12 passed.
The four independent probes are reviewer-reported evidence. The writer does not
claim a 13-test run. Full-suite evidence remains pending. No Murphy row closes.

