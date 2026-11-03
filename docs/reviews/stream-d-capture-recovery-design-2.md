**Verdict: BLOCK.** There is one blocker. It is in the exam spec, not the mechanism, and it takes one sentence to fix. All round-1 fixes hold. This was the last permitted round, so the parent decides what happens next.

I reviewed `docs/designs/stream-d-capture-recovery.md` at 80d6433 on `t3/stream-d-gates` against `factory/extension_package.py`, `factory/extensions.py`, `factory/gate_attempt.py` and `tests/factory/test_stream_d_entry.py`. I used the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. I made no repo edits and started no workers, model calls or subagents. I ran one offline probe, a scratch script at `/tmp/gf2/probe.py` that reuses the `EntryTests` setup.

## Blocker

**B3. The replacement exam for `test_capture_failure_after_rename_does_not_retry` cannot pass as written** (design lines 77–81). This came from round-1 nit N2, which was itself wrong, and the design adopted it.

- The test's sync patch raises whenever `(path / 'G1/record.json').exists()`.
- `save` calls `extensions._sync_tree(temporary)` before the rename. `_sync_tree` then calls `_sync_directory(root.parent)` (`extensions.py:207`), and `root.parent` is `self.root`.
- So once G1 exists, every later stage fails before its rename, not after. There is no target, the staging directory is removed, and the retry fails the same way.
- I confirmed this with the probe: current `observe_gate`, minus the `rmtree`, under the existing patch. Results:
  - G1 fails after rename, with the target present.
  - G2–G5 fail with **no target**.
- Under the design, that means:
  - G1 is intact but unacknowledged.
  - G2 onward each get two `save` calls and publish nothing.
  - `c.card` has G2 marked pass, so `entry_prefix` refuses.
  - Entry stays **pending**.
- The design instead says: "snapshot equal to an uninterrupted traversal", "save called once per stage", and "all their intact records remain available". All three are false, so the implementer would have to pick the intended behaviour themselves.
- **Fix: pick one and write it down.**
  - (a) Keep the persistent patch and expect: one invocation per gate, G1 bytes retained, two `save` attempts for each of G2+, `closed.json` absent, entry pending.
  - (b) Narrow the patch so it fails only the post-rename `_sync_directory(self.root)`. For example, raise on `path == records.root` only when the current stage's target already exists and has not failed yet. Then also state whether the verify step's `_sync_tree(target)` is allowed to succeed. If it does, `observed` becomes true and `closed.json` will appear, which contradicts "closed.json absent".
  - (b) is the one that actually tests "intact record available despite a missing ACK".

## Round-1 dispositions

- **B1 (fixed):** Lines 58–63 put everything after `invoke` (the helper, tuple unpacking, the pending and case checks) under `except Exception`. `invoke` stays outside that block, and `BaseException` is not caught. The exam at lines 90–91 covers it.
- **B2 (fixed):** Line 46 compares `extensions.digest` of both results. `digest` uses `allow_nan=False` and `sort_keys`, so NaN and mixed key types raise, and line 49 turns that into `return False`.
- **M1 (fixed):** The crash exam names the point (`_sync_directory(self.root)` after G4's rename) and the frontier (G5). It is the same shape as the existing `test_real_partial_prefix_never_evaluates_and_preserves_caller`, and `entry_prefix` only checks the card from the hole onwards, so the missing G4 card entry is harmless.
- **M2 (fixed):** Lines 43–45 build the probe the same way `replay_writer_early` does. `_sync_tree` does sync `target.parent`.
- **N1 (fixed):** Lines 30–33.
- **N2:** Adopted, but the premise was wrong. That is B3.
- **N3 (fixed):** Lines 63 and 68–71.

## Optional (non-blocking)

- **O1.** Lines 96–97: "Kill after a complete rename … then raise at …" reads as two events, but it is one. Also note that `_sync_directory(self.root)` already runs before the rename, inside `_sync_tree(temporary)`. The patch therefore has to check that G4's record exists, or it fires before the rename. This is the same trap as B3.
- **O2.** A retried `save` re-reads the live `c.card` through `project(c.card)`; only `old_card` is frozen. For G10, which runs on a worker thread, the second attempt's card could differ from the first. Every error from this is caught, so it is safe. It is still worth one line saying the record card is the live post-invoke card, not a frozen one.
- **O3.** A pre-invoke `RuntimeError` (for example from `project` during the G10 race) still escapes into ordinary retry. The gate does not run twice, because `invoke` has not run yet, so this is acceptable as scoped.

## What holds up

- The scope matches the parent's: fresh cases only, no card-only inference, never evaluated again, at most two copy attempts.
- It removes the two destructive `rmtree` paths.
- Corrupt proof is never replaced.
- G3 checking happens on copied args and card.
- It supports Murphy rows 9 and 13 and closes none, which is consistent.
- Every Heilmeier question is answered.

## Writer disposition

B3 remains open for parent decision under the two-round cap. Recommend option (b): fail only once at the post-rename parent sync for G1, allow verification sync to succeed, and assert the unchanged snapshot, one save per stage and closed.json present. Retain the persistent-failure scenario separately with pending entry as in option (a). No implementation or round 3 started. Optional O1–O3 are recorded for the parent-approved design disposition.

