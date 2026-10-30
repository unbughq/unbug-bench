I ran the fresh goldfish review of the queued-input slice `9701f56..d0e4a02`. **Verdict: PASS for the unwired slice, with no blockers, no majors and 6 nits.** The implementation matches the passed design-6. The weak spot is test strength: 11 of the 14 guards I removed one at a time still left all tests passing. None of those survivors is a terminal false refusal, but nits 1–3 should land before dispatcher wiring. I wrote nothing to the worktree, and the review text below is ready to save as `docs/reviews/stream-d-diff-23.md`.

---

# Review: stream-d diff 23, queued diagnosis inputs. PASS (no blockers, no majors, 6 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I used the zoom_out and implementation_readiness personas, with `zoom-out-standard.md` and `implementation-readiness-standard.md`, under `docs/ENGINEERING.md`.

**Scope:** the cumulative diff `9701f56..d0e4a02` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, limited to:
- the queued-input helpers in `factory/diagnosis.py`: `_input_bytes`, `_input_inventory`, `_input_restore_receipt`, `_input_cache_resolves`, `_input_stop_evidence`, `_write_input_tree`, `_verify_input_records`, `queued_inputs`, and the `exhaustion` stop tuple;
- `tests/factory/test_stream_d_inputs.py`;
- the "Queued diagnosis inputs" design section and the "Queued input implementation boundary" section in `docs/designs/stream-d.md`.

**Read in full, with elephant responses:** `stream-d-diagnosis-input-design-{3,4,5,6}.md` and `stream-d-diff-22.md`. The worktree is clean at `d0e4a02` apart from `.stream-d-next/`, which I excluded.

**Supporting inspection only:** `gate_state.inventory/save/load`, `job_authority.for_case`, `job_config.FACTORY`, `extensions.read` (confirmed it does not write), `_factory_bug_history`, and `worker_release.source_files`.

## Verification run (offline, bounded)

- `uv run python -B -m unittest tests.factory.test_stream_d_inputs`: **18 tests, OK** (11.9s).
- **Mutation probes.** I ran them on a `git archive d0e4a02` copy in the scratchpad, not in the worktree. Each probe removed one guard, then ran `test_stream_d_inputs` and `test_stream_d_held`.
  - **Caught (tests failed):**
    - the `diagnosis_input_invalid` entry in `exhaustion` (20 failures);
    - `_input_stop_evidence` on replay (2 failures).
    - The receipt ledger binding, the corrected/carried-forward branches, current-bench precedence, the stale-cache omission and the late-defect checks are each exercised directly by named tests.
  - **Not caught (tests still pass):** the replay cache-resolution loop, the creation `active` check, the initial checkpoint-card state equality, the authenticated-vs-args release digest check, the no-resolution-through-cache guard, the empty-evidence check, the evidence-kind check, the `_input_bytes` ancestor-symlink check, the replay frozen-card `pending` and ledger-`active` checks, the `terminal_stop == diagnosis_input_invalid` entry guard, and the infrastructure-marker value check.
- Selecting the current worker manifest with the helper's rule picks 80 of 100 files, all under `factory/` or `bin/`. Nothing is selected from another directory.
- No full suite, launches, cloud work, models, decryption, writes or commits. The parent is running the full suite. No suite result is claimed here.

## Implementation against the passed design

- **Generation.**
  - The manifest generation is `job_authority.for_case(c).source_generation`, which is verified and must be non-null.
  - The frozen receipt must carry that same `generation`, and it is checked on both creation and replay through `_verify_input_records`.
  - The archived card's `sha256` is never consulted. The tests cover a card with that field absent and one where it names an older generation.
  - On replay, the frozen receipt is checked against the manifest generation, never the live receipt. `test_frozen_evidence_survives_live_usage_and_later_generation` rewrites the live receipt and the source binding, and replay stays unchanged.
- **Receipt checks.**
  - `type(version) is int`, `version == 1`, matching case, `accounting_authenticated is True`, and SHA-256 checks on `ledger_sha256` and `public_card_sha256`.
  - The card's `continuation_budget` must be present and a dict. Its `carry_over.digest` must equal `retained_ledger_sha256` when that field is present (a null value refuses), otherwise `ledger_sha256`.
  - The actual `restore_ledger.install` is run for three branches: no ruling, an explicit founder correction (public ledger differs from retained), and a carried-forward ruling. Removing or altering the correction field refuses.
- **Live ledger growth.** `ledger.json` is frozen from `c.ledger` and is not hashed against the receipt (tested).
- **Selection.**
  - The `gate_state.inventory` files are added first. Current `bench/results` files go under `work/bench-results/`.
  - The restored `work/bench-results` tree then fills only names that are not already present.
  - Unsafe restored files still refuse even when superseded, because they are read before the precedence check.
  - `gate-cache` is dropped from the list of directories copied whole. Cache records are filtered after all evidence is copied.
  - An unsafe cache file refuses before its JSON is parsed. A malformed or stale record is skipped, and its live bytes are left untouched.
  - The test with the saved `invalid-runs-real.json.gz` `plain`/`reference` receipts proves that the current bytes win, restored-only files are kept, the stale cache is dropped, both live copies are preserved, and replay never re-selects files.
- **Source chain.**
  - The authenticated release digest must equal `args`.
  - `batch-release.json` and the worker manifest are read through `job_config.read_file`.
  - Selected files must match their manifest digests, and an empty selection refuses.
- **Required stop evidence.**
  - G4/G6 late defects use `late-defect.json` bound to the stop gate and the card marker (missing, wrong-gate and wrong-digest cases are tested).
  - Extension stops use `extensions.read` on the frozen tree, with outcome and projection agreement checked.
  - Infrastructure stops use the marker. Budget and stress stops need only the minimum inputs.
- **Orphans.**
  - With the manifest missing, any of these refuses before cleanup: a non-pending state, `finding.json`, `raw-result-*`, or a reservation named `diagnosis-<id>` or `diagnosis-<id>-repair-N`.
  - A genuinely unbound attempt re-stages from current bytes.
  - Symlinks at the manifest, inputs or staging paths, or on the diagnosis parent, refuse.
- **Durability.** Each file is fsynced, then directories deepest first, then `os.replace`, then the parent, `diagnosis` and `work` directories. Records are verified before `atomic_json(input.json)`. `test_unbound_orphan_restages_after_settlement_and_manifest_is_last` proves the manifest is written last.
- **Immutable replay.**
  - The manifest must have exactly five keys, a strict schema int, and matching case and exhaustion ID.
  - Its files must equal the recomputed `_input_inventory` (missing, extra and changed files refuse, all tested).
  - The frozen card must be pending with the same exhaustion ID, and the frozen ledger must not be active.
  - A self-consistent manifest that drops a required record refuses (tested for `card.json`).
- **Terminal stops.**
  - Every caught failure sets `stopped` / `diagnosis_input_invalid` and preserves `diagnosis_state`.
  - `exhaustion` returns false, the projection is None, and `record_exhaustion(new_exhaustion=True)` mints no new ID. `assert_invalid` checks all of these on every refusal.
  - History-invalid projections remain covered by `test_stream_d_held`.
- **Boundary.** `queued_inputs` has no runner caller. No model, process isolation, money admission or dispatcher is activated. Diff-22 N1 (reconcile before the snapshot) remains a dispatcher obligation and is not claimed done. That matches the boundary section.

## Findings

### Blockers
None.

### Majors
None.

### Nits

**N1. Two named design tests do not actually test their guard.**
- **"References through another cache file"** (design-6 test list). In `test_cache_path_controls_and_published_cache_damage`, `bad-2.json` names `gate-cache/G4.json` but with the digest of `gate-details/G4.json`. It is omitted because of the digest mismatch, not because of the `work/gate-cache/` guard, and the guard mutant survives.
  - *Fix:* give `bad-2` the real digest of `gate-cache/G4.json`. `G4.json` sorts first and is already copied, so only the guard can then omit `bad-2`.
- **"Release digest mismatch"** is covered only by changing source bytes. The authenticated-config vs `c.args.batch_release_sha256` refusal is never reached.
  - *Fix:* add one subTest that changes `c.args.batch_release_sha256`.

**N2. The terminal stop is not proven to be sticky.** The `terminal_stop == 'diagnosis_input_invalid'` entry guard survives mutation. No test calls `queued_inputs` again after a refusal without first calling `reset_stop`. Without the guard, a case whose damage was later reversed (for example, the receipt bytes restored) would return a manifest. The design requires that recovery is never an automatic reset.
- *Fix:* in `assert_invalid` or one focused test, call `freeze()` again with the original bytes restored and assert it still refuses.

**N3. Fail-open guards with no killing test.** Each of these is correct as written, but removing it leaves the suite green:
- the creation `ledger.active` refusal;
- the empty evidence list and invalid `kind` in `_input_cache_resolves`;
- the replay cache-resolution loop and the frozen-card `pending` / ledger-`active` checks, which are reachable only through a self-consistent manifest rewrite. The `card.json` drop test shows the pattern to follow;
- the infrastructure marker `exhausted is not True` refusal;
- the `_input_bytes` ancestor-symlink check, which is reachable when a base such as `sealed/` or `bench/results` is itself a symlink.

All of these regress toward accepting more input, not toward a terminal false refusal. One subTest each would pin them before dispatcher wiring.

**N4. A history-invalid stop can be relabelled.** `queued_inputs` refuses entry only for `diagnosis_input_invalid`.
- If it is called on a card already stopped as `factory_bug_history_invalid`, a refusal overwrites that stop with `diagnosis_input_invalid`, and a successful replay returns a manifest.
- Both stops project None and both mean "check case", but the operator loses which reviewed repair is needed.
- The design does not cover this ordering, so I am not treating it as a defect. Record it as a dispatcher obligation (do not call the helper on a history-invalid card), or add that stop to the entry guard.

**N5. A code comment repeats a claim the design withdrew.** `add_tree` says "The current bench copy wins, exactly as the next seal does." Design-6 N1, accepted, dropped the exact seal-equivalence claim: the seal moves only files written since `c.t0`.
- *Fix:* change the comment to "current inventory copy wins, as current gates read it."

**N6. Source selection uses right-anchored matching.** `PurePosixPath(name).match('factory/*.py')` also matches `x/factory/a.py`. Such a file would be read from `bench/x/factory/a.py` and frozen as source. The current manifest has no such names (80/100 selected, all under `factory/` and `bin/`), so this is latent only.
- *Fix:* use `full_match` (the Python 3.14 runtime has it), or check the first path component.

## Prior findings

- **Design-4 Ma1** (real-install corrected and carried-forward branches): implemented and tested.
- **Design-5 Ma1 / design-6** (current-copy precedence without exact seal equivalence, named fixture): implemented and tested. N5 is wording only.
- **Diff-22 Ma1** (stale-cache pass then fail): records are omitted only at creation and stay strict on replay. Tested with a real `gate_state.save` record.
- **Diff-22 N2** (no-follow regular-file descriptor read): implemented, with an ancestor check on top. A race between that check and the open remains, which is acceptable under the quiescence precondition.
- **Diff-22 N1** (reconcile before the snapshot): still a dispatcher obligation. Not claimed.
- **Archived card cannot name itself:** resolved through the receipt route.
- **Differing current and restored bench copies:** the live inventory copy wins.

## Readiness boundary

PASS means the implementation conforms to the passed design for the **unwired** helper. It does not mean the dispatcher is ready.
- Dispatcher wiring must still reconcile before calling the helper, call it before any finding replay, reservation or model invocation, enforce read-only isolation on the inputs root, and avoid calling it on history-invalid cards (N4).
- Nits N1–N3 should land before that wiring.
- No Murphy row closes. No dispatcher, process isolation, model, money or runtime activation is claimed. No suite result is claimed by this review.

## Elephant response

Accepted all six nits. N1–N3 will gain focused refusal and replay controls before dispatcher wiring. N4 will preserve history-invalid at helper entry, N5 will correct the comment, and N6 will anchor release selection to the allowed root. The full suite is running against d0e4a02; no passing full-suite claim or Murphy closure is made here. Reconciliation and worker isolation remain dispatcher obligations.

## Full-suite result

After the review, the full required command on d0e4a02 completed:
`uv run --with numpy --with scipy python -B tests/run.py` — **150 scripts, 0 failed**.
Source and test bytes remained unchanged throughout. `tests/bench/test-launch-guards.py`
passed in that run; no isolated rerun was needed. Log:
`/tmp/stream-d-inputs-corrected-suite.log`, SHA-256
`204e7d70a2eea536ba09aa3c4a3b725eed494fa662a891fc28be3ba0ac460869`.
The earlier ebf3b1a run's failure and isolated passing rerun remain recorded in
diff review 22; this result does not replace that history. No Murphy row closes.

## Nit follow-up

Implemented N1–N6 in the next increment. Cache-through-cache now names the actual
copied cache digest. Added direct authenticated/argument release mismatch,
sticky refusal after bytes are repaired, active-ledger and initial-state controls,
self-consistent manifest mutations (pending state, active ledger, infrastructure
marker and retained cache), empty/bad-kind cache hints, and a symlinked selected
base. History-invalid now refuses before the input error handler and keeps its
original stop, with controls both before publication and on replay. The bench
comment describes current-reader precedence. Release selection requires the exact
factory or factory/prompts parent, with nested-path manifest controls.

These pin semantic refusals; redundant checks at creation and replay need not each
be independently necessary for the end-to-end refusal test to pass. No tests
are claimed as proof of a source line rather than observable behavior. No dispatcher
or Murphy closure is included. A fresh diff review and full suite follow.

