**Verdict: BLOCK.** The design is the right size and aimed at the right problem, but two gaps need fixing before implementation. Both are fixes of a sentence or two in the design.

I reviewed `docs/designs/stream-d-capture-recovery.md` at f0a483a on t3/stream-d-gates against `factory/extension_package.py`, `factory/gate_pipeline.py`, `factory/gate_attempt.py`, `factory/extensions.py` and `tests/factory/test_stream_d_entry.py`. I used the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW, against the Heilmeier and implementation-readiness standards. I made no edits and spawned no subagents. The only test I ran was a baseline check: `test_capture_failure_after_rename_does_not_retry` and `test_pending_shape_and_capture_errors_do_not_retry_or_change_gate_result` both pass on the current code.

## Blockers

**B1. Any capture error outside `CAPTURE_ERRORS` reruns the gate, which contradicts the "executes exactly once" claim.** (design_critic; design lines 25–28, 47–52)
- `observe_gate` runs inside `gate_attempt.execute(..., attempts=2, interruption=BudgetError)` (`gate_pipeline.py:153-156`). Any ordinary `Exception` that leaves `observe_gate` is retried by calling `around_gate` again, which runs the gate a second time and may spend money.
- The design only catches `CAPTURE_ERRORS` (BudgetError, InvalidInfra, OSError, ValueError, KeyError, TypeError). The new helper adds deep copies, a probe `Records`, extra loads and comparisons. A RuntimeError, AttributeError or RecursionError from any of them escapes.
- A concrete path already exists: G10 runs `around_gate` on a worker thread (`gate_pipeline.py:197`) while the main thread writes `c.card["gates"]` and `gate_results`. `project(c.card)` in `save`, and the new deep copies of the card, can raise `RuntimeError: dictionary changed size during iteration`. That reruns G10.
- On that retry, the target written by the first attempt now exists. The design then refuses, so the case pays for a second G10 run and still ends up with no recorded result.
- **Fix:** say that everything the helper does after `invoke()` returns is inside `except Exception` (not BaseException). That covers taking the pins, the pre-existing target check, both attempts and verification. Any such error returns False. Add one exam: a RuntimeError from save or verification gives one invocation, the original gate tuple and a pending entry.

**B2. "require its ok/info to equal the frozen result" doesn't say what kind of equality.** (implementation_readiness; line 43)
- The stored record has been through JSON (`atomic_json` → `json.dump`), so tuples come back as lists and non-string keys come back as strings. A plain `==` against the deep-copied `info` fails on a correctly published record.
- That failure is safe, because the entry just stays pending. But recovery would silently not work for those gates, and tests that only use authored dict results would not catch it.
- **Fix:** name the comparison, for example `extensions.digest({'ok': ok, 'info': info}) == extensions.digest({'ok': data['ok'], 'info': data['info']})`. Also say that if the frozen info can't be digested (NaN or something not JSON-serialisable), the helper returns False.

## Major (should fix)

**M1. The kill-after-rename exam says "same snapshot" without saying what it is compared to** (lines 81–83). After a kill once G_k is renamed, entry shows G_k as scored and G_k+1 as unreached. That cannot equal an uninterrupted traversal. Name the stage to kill at, the expected frontier, and the expected status rows (for example: kill after G4's rename, frontier = index of G5, G4 pass, the rest unreached). Also name the point where the BaseException is raised: `_sync_directory(self.root)` inside `save`.

**M2. Verification needs a named construction** (lines 41–43). `load('G3')` writes to `self.c.args.bench_workers`. State that verification uses `probe = copy.copy(c)` with deep-copied `args` and `card`, and `Records(probe, r, observation_id=self.root.name, round_number=self.round_number)`. That is the same pattern as `replay_writer_early` (`extension_package.py:285-287`), and gives the G3 exam an exact target. Also note that `_sync_tree(target)` already syncs `target.parent`, so no separate parent sync is needed.

## Nits

- **N1.** Line 30: say that a pre-existing or symlinked target returns False without calling `save` and leaves `observed[stage]` False. That is implied but not stated.
- **N2.** Once the post-rename `rmtree` is removed, the existing test's sync patch fails every later `_sync_directory(root)` call too, because `G1/record.json` keeps existing. So every later stage takes the verify-and-fail path and ends unacknowledged but intact. The design's expected outcome still holds, but the exam should assert that `save` is called once per stage and that `closed.json` is absent.
- **N3.** Line 51: "capture-side failures do not escape" is only true after B1 is fixed. Capture errors that happen before `invoke` (the inventory step) keep their current behaviour, as the design already says.

## What holds up

- **Scope:** it covers fresh cases only. It does no card-only reconstruction, migration or version change, and no paid reroll.
- **Simplicity:** it removes two destructive `rmtree` paths instead of adding guards, reuses `save` and `load`, and adds one helper with two attempts. Nothing speculative.
- **Ordinary result:** the gate tuple is returned unchanged, and the existing check that the case didn't change across `invoke` is kept.
- **Corrupt proof:** a corrupt or mismatched record is never deleted or replaced.
- **Crash safety:** a partial `.stage-*` directory never becomes a scored record. A record whose sync was never acknowledged is still checked by `load`. If a power loss erases it, entry shows a hole and stays pending, which is safe.
- **Standards:** every Heilmeier question is answered, including cost, a 2–4 hour estimate, and the midterm and final exams.
- **Murphy rows:** the design says it supports rows 9 and 13 and closes none. That is consistent.
- **Persistent-failure test:** the existing exam still holds with two save attempts. It asserts one G1 execution, the original result, no `closed.json` and a pending entry.

## Writer disposition

B1 and B2 accepted: post-invoke capture catches Exception, with invoke outside; result equality uses JSON digests and rejects non-finite/non-serializable inputs. M1 and M2 accepted: exact crash frontier and copied-context construction specified. N1–N3 clarified in the design. No implementation yet; request round 2.

