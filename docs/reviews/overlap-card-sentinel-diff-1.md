# Goldfish review: overlap card sentinel (diff 1)

- Branch: fix/overlap-card-sentinel, commits 70933fe4 (fix) and 28a2f958 (verdict-code repin) on main f20115b1.
- Mode: REVIEW (zoom_out, implementation_readiness). No design doc (one-line fix, obvious cause); reviewed against the commit messages and the bug statement.
- Reviewer: fresh goldfish (Opus), read-only, given the diff and the bug statement only.
- Verdict: **PASS. No blocking finding.**

## Review (verbatim)

**Verdict: PASS**

1. **NIT. The fix is correct and stops the bug at its source.** At `factory/gate_pipeline.py:381` the snapshot now stores the module-level `_MISSING` itself (line 103) and deep-copies only keys that are on the card. That means the identity check `v is _MISSING` at line 419 holds again, so the put-back removes the key instead of writing a stray object onto the card. The one-line change fits the commit message. I looked for other places the bug could repeat:
   - `_MISSING` is used only at lines 381 and 419.
   - The only other bare sentinel in `factory/` is `UNDECODABLE` (`factory/durable/stop_registry.py:428`). It is never deep-copied and is only compared with `is` (line 486).
   - The other `deepcopy` of a card value (`gate_pipeline.py:240`) uses `None` as its default, which is safe.

   No other spot can copy or lose the sentinel. One existing quirk is outside this fix's scope: G13 and G15 share `strategy_reuse` (`factory/run.py:1056`).

2. **NIT. The test proves the bug through the real code path.** `tests/factory/test_gate_overlap.py:192-210` uses the shared `exercise` helper, which drives the real pipeline with the real `OVERLAP_CARD` (not patched). G6 raises `InfrastructureExhausted` while G13 holds a new `strategy_reuse`, which reproduces the 2a7b2a incident.
   - On the branch, all 20 tests pass.
   - With main's `gate_pipeline.py` swapped into a scratch copy, this test fails with `'strategy_reuse' unexpectedly found ... <object object at 0x...>`. That is the exact stray object, so the test is not a tautology.
   - Minor point: the final `json.dumps(c.card)` stands in for the checkpoint's write of scorecard.json rather than calling the real writer. It doesn't matter, because `assertNotIn` already fails first.

3. **NIT. The verdict-code repin is correct.** I computed the digests from git blobs the same way `factory/durable/checkpoints.py:145-155` does:

   | Commit | Bench raw digest | Model raw digest | Reported codes |
   |---|---|---|---|
   | origin/main (`f20115b1`, same as remote main and the merge-base) | `e50c8b74` | `01433a26` | `d4a7127a` / `802bfc8f` (old pins matched) |
   | fix commit alone (`70933fe4`) | `9511baae` | `c464ced1` | the raw digests (the pins went stale) |
   | HEAD | `9511baae` | `c464ced1` | `d4a7127a` / `802bfc8f` |

   - The new "to" values equal HEAD's raw digests, and the "from" values are unchanged.
   - Dropping the previous "to" values (`e50c8b74` / `01433a26`) is right: those are main's own raw digests and are no longer deployed. The predecessor's reported code is carried over in "from", as the comment at `checkpoints.py:135-141` requires.
   - The claim that no verdict changes holds. The changed branch only runs when an overlapped gate is never recorded and the key was absent. On the old code that path always ended in a TypeError at the next scorecard checkpoint, so it never produced a saved verdict for the new code to change.
   - The second commit's message is subject-only. A one-line body giving that reasoning would help the next reviewer.

4. **NIT. Process.** No Murphy row is cited or closed for the 2a7b2a incident. If the register tracks this failure class (corrupt card on overlap put-back), the new test is the real test that closes it.

No blocking issues.

## Disposition

1. No action needed.
2. No action needed.
3. The commit was already reviewed, so its message is left as is. The reasoning for "no verdict changes" goes in the PR body.
4. Not applicable. `docs/murphy-register.md` was removed from main in 33d45fc1, so there is no register to add the row to.
