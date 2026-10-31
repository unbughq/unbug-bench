**Goldfish diff review: stream D item 6, isolated extension comparison (`a4397ef..HEAD`, branch `t3/stream-d-gates`)**

Mode: REVIEW. Personas: zoom_out and implementation_readiness. Standard: implementation-readiness-standard.md. I reviewed the diff against the item 6 section at the end of `docs/designs/stream-d.md`, including the review resolutions and the implementation clarification, and against design reviews 1 and 2. I wrote no repo files. I did not rerun the suite. I ran one throwaway scratch test, built on the existing `CompareTests` fixtures, in `/tmp` and then deleted it.

**Verdict: FAIL.** One blocking finding.

### Checks requested

- **Common version vector stays fixed before and after.** Pass. `snapshot` checks the vector at the end (`extension_compare.py:196-197`). `compare` checks live configuration and versions again (`:262-264`, `:275-278`). Drift returns `pending` with no append. Tested in `test_configuration_mutation_and_version_drift_are_pending`.
- **An invalid execution becomes pending.** Pass. This covers `InvalidInfra` (with `InfrastructureExhausted` as a subclass), the in-band `classification:'invalid-infra'`, `error`, `invalid_infra`, `execution_valid:false`, missing or symlinked support, and `freshness_unresolved` from stress only. `CaseProblem` becomes a fail with a saved support file. Inconclusive becomes a G16 fail. All are tested.
- **A completed result cannot be rerolled.** Fails in one case; see blocker 1. The same-version, same-binding case does hold: `test_completed_pair_and_original_receipts_are_sticky` and the pending → scored → sticky test both make zero evaluator calls.
- **The next admission uses the retained comparison evidence.** Pass. `_entry_evidence_root` is used by both `verify_proposal` and `admit`, and a tampered retained support file is refused. Tested compare → propose → verify → admit, admit replay, a changed live case, and the opaque-original reconstruction.
- **The live candidate and card are not changed.** Pass. `compare` runs on a copy of the card (`owner`). Scratch space comes from `tempfile`, outside `c.work`. The test asserts the live case tree, the card, `gate-cache` and the absence of `c.work/comparison-receipts`.
- **Design review blockers.** All 5 from review 1 and all 3 from review 2 are implemented as written, with one exception: review-2 blocker 3 (no rerolls) is only partly met; see blocker 1.
- **Scope.** There is no default `run.gN` adapter, no diagnosis is enabled, no real or paid run happened, and `docs/murphy-register.md` is unchanged. "Supports row 9, closes none; row 39 stays open pending a live capped-submission artifact" matches the design and the report. The report records both runs, and the correction after the failed first run touched only `tests/tools/test_launch_manifest.py`. HEAD `7072159` changes only docs after the 6492fa5 suite pass.

### Blocking findings

**1. A plumbing-only change rerolls a scored comparison, and then `compare` and `propose` give different answers.**
- **Severity:** Blocker.
- **Scope:** `factory/extension_compare.py:100` (the binding check in `_load`), `:252-265` (the sticky selection), and `factory/extensions.py:255-266` (`propose` selection).
- **Cause:** Whether a pair is sticky depends on `_load`. `_load` requires `row['binding_sha256'] == gate_state.fingerprint(...)`. That fingerprint includes `bench_workers`, `concurrent_roles`, `slot` and `UNBUG_FACTORY_SLOT`. `scientific_version` deliberately strips those settings as plumbing.
- **`bench_workers` changes in real runs:**
  - the G3 memory allowance lowers it (`run.py:2208-2209`);
  - startup forces it to 1 (`run.py:2967`);
  - `bench_workers_effective` is VOLATILE on resume.
- **Reproduced:**
  - `prepare()` → `compare()` gave `progress`.
  - I then set `c.args.bench_workers = 2`; the version vector did not change.
  - A second `compare()` ran 12 fresh stages and appended a second pair. It returned `no_progress`.
  - `extensions.propose(c, comparisons[0]['outcome'])` was still **accepted**, because `propose` picks the first scored pair.
- **Effect:** The worker sees `no_progress` and would retire the case, but admission accepts progress from the earlier pair. The rerun also re-pays for every fresh stage. The design says "A completed same-version pair is sticky: return its result without evaluation". This breaks that rule and the "plumbing keeps pair" property. The existing plumbing test edits only `budget.py`, which is outside the fingerprint.
- **Fix:**
  - Decide stickiness and pass reuse at the version vector plus case digest plus verified receipt and support bytes. Either drop plumbing-only fields from the comparison binding, or bind it to `scientific_version` plus case, seed and calibration identity.
  - Make `compare` and `propose` share one pair-selection function, so they cannot diverge.
  - Add a test: after a scored compare, change `bench_workers` (and the slot env); the next compare makes zero evaluator calls, leaves the history unchanged and returns the same result as `propose`.

### Nits (non-blocking)

1. **Programming errors become pending.** `extension_compare.py:190` catches `ValueError`, `TypeError` and `FileNotFoundError` from inside `evaluate` itself. A bug in the adapter therefore becomes `pending` instead of propagating, which the design asks for ("other exceptions propagate"). It fails safe, never as a scored result. Consider narrowing the catch to `_save` and result-shape validation only.
2. **`propose` filters twice.** `extensions.py:257-264` filters `candidates` by version and then filters `matching` again. The second filter only matters for the original-pair fallback. One selection helper would remove this; see blocker 1.
3. **`propose` trusts an unverified original.** If `compare` is never called, `propose` still accepts a scored opaque original with current version labels. The design makes compare-before-propose item 7's job; say so in `propose`'s docstring so that lane 7 does not skip it.
4. **Weak isolation test.** `test_stage_support_is_copied...` checks overwrite isolation only by loading `stress` after later stages rewrote `same.json`. Assert one middle stage as well, for example G5, to cover the `support` namespace fully.

Murphy rows: no rows are closed, which is correct. The claims for rows 9 and 39 match the report.

## Elephant response

Blocker 1 accepted. Comparison receipts now separate scientific identity from execution provenance. Plumbing-only worker/concurrency/slot changes cannot invalidate a scored pair. Comparison and admission share one pair selector, retaining the first scored reconstruction. All four nits accepted: adapter programming errors propagate; duplicate selection filters are removed; propose documents the compare-before-propose requirement; support-copy checks include G5. Regression coverage changes worker count, concurrency, slot and slot environment after a scored pair, verifies zero evaluations and unchanged history, and checks admission uses that same outcome. No finding is rejected.

