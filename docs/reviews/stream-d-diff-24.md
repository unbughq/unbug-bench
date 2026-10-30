**PASS. No blockers, no majors, 1 nit.** The diff closes all six diff‑23 nits in ways you can see when the code runs. The 24 focused tests pass, and probes that removed 14 guards one at a time were caught by the tests in 11 cases. The three that slipped through all fail closed or have no effect.

---

# Review: stream-d diff 24, queued-input nit follow-up. PASS (no blockers, no majors, 1 nit)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I used the zoom_out and implementation_readiness personas, with `zoom-out-standard.md` and `implementation-readiness-standard.md`, under `docs/ENGINEERING.md`.

**Scope:** `c7c5ca4..210eb39` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`, HEAD `210eb396`. It changes three files:
- `factory/diagnosis.py`: +5/−3;
- `tests/factory/test_stream_d_inputs.py`: +88/−1;
- `docs/reviews/stream-d-diff-23.md`: +17, the nit follow-up record.

I reviewed it against the "Queued diagnosis inputs" and "Queued input implementation boundary" sections of `docs/designs/stream-d.md`, the passed design‑6, and `docs/reviews/stream-d-diff-23.md`, which I read in full including its responses. `.stream-d-next/` is untracked and I excluded it. Neither the design nor the Murphy register changed in this range.

## Validation run (offline, bounded)

**Focused tests.** I ran them on a `git archive 210eb39` copy in my scratchpad, not in the worktree. `uv run python -B -m unittest tests.factory.test_stream_d_inputs` ran **24 tests, OK** (14.8s).

**Mutation probes.** Each probe removed one guard in a fresh scratch copy, then ran `test_stream_d_inputs` and `test_stream_d_held`.

| Guard | Diff-23 nit | Result |
|---|---|---|
| `terminal_stop == diagnosis_input_invalid` entry guard (stop stays set) | N2 | **Killed** |
| `factory_bug_history_invalid` entry guard | N4 | **Killed** |
| Authenticated-vs-`args` release digest check | N1 | **Killed** |
| `work/gate-cache/` resolution guard | N1 | **Killed** |
| Empty evidence list | N3 | **Killed** |
| Replay frozen-card `pending` check | N3 | **Killed** |
| Replay frozen-ledger `active` check | N3 | **Killed** |
| Infrastructure marker `exhausted is not True` | N3 | **Killed** |
| Replay cache-resolution loop | N3 | **Killed** |
| `_input_bytes` ancestor-symlink check | N3 | **Killed** |
| Release selection reverted to right-anchored `match` | N6 | **Killed** |
| Evidence `kind` allow-list | N3 | Survived. See nit 1. |
| Creation `ledger.active` check | N3 | Survived. Redundant with `_verify_input_records`; refusal still observed. |
| Creation `checkpoint_card` state equality | N3 | Survived. Redundant with `_verify_input_records`; refusal still observed. |

The brief says not to demand tests that kill individually redundant guards. Both creation survivors still refuse end to end, with `diagnosis_input_invalid`, a stopped card and no `input.json`, because the same property is checked again before the manifest is published. That meets the observable-behaviour bar.

I did not run the full suite, any launch, cloud work, models or decryption, and I made no writes or commits in the worktree. This review claims no full-suite result at `210eb39`; the parent is running it.

## Diff-23 nits, as addressed

- **N1, cache-through-cache:** done. `bad-2` now carries the real digest of the copied `gate-cache/G4.json`, so only the guard can drop it. The probe confirms this.
- **N1, release mismatch:** done. A direct test changes `c.args.batch_release_sha256`. Killed.
- **N2, the refusal stays stopped:** done. `test_terminal_refusal_stays_stopped_after_input_is_repaired` restores the original receipt bytes without calling `reset_stop`. It asserts a second refusal and that no `input.json` exists. This matches the design rule that recovery is never an automatic reset.
- **N3, guards that had no killing test:**
  - The four self-consistent manifest rewrites each kill their target:
    - card no longer pending;
    - marker `exhausted=False`;
    - ledger `active`;
    - a retained cache record pointing at a missing file.
  - The final assertion checks that the original manifest still replays unchanged afterwards.
  - The symlinked selected base (`bench/results` pointing at another directory) refuses.
  - The active-ledger and initial-state controls are observable and pass, but they are not individually necessary. See the table.
- **N4, a history-invalid stop could be relabelled:** done. The `factory_bug_history_invalid` check now runs before the `try`, so the `diagnosis_input_invalid` handler never sees it. The test covers both before and after publication. It asserts the card is byte-identical, the error is `BudgetError('factory_bug_history_invalid')`, and the projection is None. This is consistent with stream-d.md §1469, which makes that stop terminal and keeps its original label.
- **N5, the comment:** done. It now reads "Current inventory wins, as current gates read it." The withdrawn seal-equivalence claim is gone.
- **N6, anchored source selection:** done. Selection now requires the exact parent `factory` or `factory/prompts`. The test's nested names (`elsewhere/factory/a.py`, `elsewhere/factory/prompts/a.md`, `factory/nested/factory/a.py`) are deliberately absent on disk:
  - if any were selected, the freeze would refuse;
  - so the freeze succeeding proves they were excluded;
  - and the right-anchored revert is killed.

  The real shipped manifest names select exactly as before, so legitimate source is not narrowed.

## Zoom-out

The change is minimal: three production lines, and test additions only. No new abstraction, path or configuration is added. Placing the history-invalid check before the `try` is the simplest correct ordering. The helper is still unwired: `queued_inputs` has no runner caller, and no dispatcher, model, process isolation or money admission is activated. That matches the boundary section.

## Findings

### Blockers
None.

### Majors
None.

### Nits

**N1. The bad-kind cache control does not tell the outcomes apart.**
- **Where:** `tests/factory/test_stream_d_inputs.py`, the `bad-kind.json` record in `test_cache_path_controls_and_published_cache_damage`.
- **Problem:** the record uses `kind: 'unknown'` with `path: 'test.json'`. With the kind check removed, it maps to `work/test.json`, which is not in the frozen files, so it is still omitted. The kind guard survives mutation.
- **Impact: none.** `gate_state` (line ~230) reads any non-`bench` kind as a `work` path. So even a guard-less acceptance would resolve the same bytes the gate reader uses.
- **Fix (optional):** point the bad-kind record at `gate-details/G4.json` with its real digest, so only the kind guard can omit it.

## Prior findings carried

- **Diff-22 N1** (reconcile before the snapshot): still a dispatcher obligation. Not claimed.
- **Diff-23 readiness boundary.** The dispatcher wiring must still:
  - reconcile first;
  - call `queued_inputs` before any finding replay, reservation or model invocation;
  - enforce read-only isolation on the inputs root.

  The obligation to avoid history-invalid cards is now enforced inside the helper.

## Validation boundary

PASS means this increment correctly implements the six accepted diff-23 nits for the unwired helper, and that the passed design‑6 behaviour is unchanged. My evidence is:
- 24 focused tests passing on a scratch copy of `210eb39`;
- the 14 single-guard mutation probes above.

It does not claim:
- a full-suite result at `210eb39`;
- dispatcher readiness;
- process isolation, model, money or runtime activation;
- live qualification.

The tests use authored release and lifecycle envelopes over real practice bytes and the saved ledger, as the test module's docstring states.

**No Murphy row closes.**

## Elephant response

Accepted the optional N1 test refinement; it will use the existing gate-details path and digest in the next implementation increment. All diff-23 nits are resolved by this passing review. Source/tests remain pinned at 210eb39 while its full suite runs. No Murphy row closes. The separate worker-dispatch design at df69412 is under a fresh design goldfish; no dispatcher code is implemented or enabled.

