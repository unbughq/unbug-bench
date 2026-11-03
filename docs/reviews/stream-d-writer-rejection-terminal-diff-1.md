**PASS.** I found no blocking findings in diff `ff31d87..108e65f` when checked against the design, its round-2 and boundary clarifications, and both design reviews. `19a4d8c` changes only docs and the suite record.

**Verified**
- **Suite record:** the JSON gives head `108e65f`, tree `a81978f2a099aee2fdbc77cca1d769155e30a928` (matches `git rev-parse 108e65f^{tree}`), exit 0, 181 scripts and 0 failures, under the `lockf -t 7000` command. The log's SHA-256 recomputes to `ebe416c8…ce435`. I did not rerun the full suite.
- **Focused tests:** I ran three single files offline, without the lock: the new rejection tests (10), the G1 tests (11) and the early tests (11). All passed. With the 2 launch-manifest tests that makes 34.
- **Nothing out of bounds changed:** the diff doesn't touch `diagnosis_dispatch`, `diagnosis`, the Murphy register, activation, limits, attribution, the snapshot schema or normal gate versions. No Murphy rows close. `factory/extension_writer_rejection.py` is added to `expected_worker` in the worker manifest test.
- **Outcome:** every stage is `unreached` with null hashes and `frontier=0`. No stress, G6 or pass score is invented. An entry where every stage already passed is refused. The marker's key set matches the design exactly and binds the entry, the record file bytes and the full case tree.
- **Receipt windows:** before `writer_receipt` runs, the code checks the actor, a strict-int round equal to `row.round`, phase completed/validated and `repair_pending is False`. This blocks the recovery write. After authentication:
  - The completed window requires `next_phase` G1 and no validation problems, `exhausted` or `stop_reason`.
  - The validated window requires the problems to equal the retained feedback, and `exhausted`/`stop_reason` to be either both absent or exactly `True`/`rounds_exhausted`. A mixed pair is refused.
  - Tests cover each refusal and confirm the `attack-state.json` bytes are unchanged.
- **Full tree:** the retained case tree must equal the live case tree, including `freshness.jsonl`, before and after staging. `_save_case` checks it once more. The freshness-only drift test refuses.
- **Leftovers and conflicts:** the selector only looks at the six named stage directories, so `.stage-x/record.json` is ignored. A conflicting published-stage directory (G8 in the test) is refused.
- **Card cleanup:** `stop` clears the gate and early state exactly as the design lists. It sets `failed_detail` to a deep copy of the retained info. It leaves `failed_gate` absent for saved-cheats, which diagnosis reads as `unknown`, so it is never labelled G6. Tests check this on both fresh completion and replay.
- **Replay never re-evaluates:** `verified` runs in `completed_route` (before the stress load), at the top of `package.run` (with the live-tree check), and in `subsequent_entry` before `current_pair` or `Evaluator`. On replay it rebuilds the expected outcome from the retained bytes and the stored generation, with no live `writer_receipt` call.
- **Rename-before-history crash:** after a generation change the outcome bytes are identical and only `source_generation` takes the new value.
- **Close-to-passing is retired:** the test runs real `apply(comparison_route=True)` then `admit_extension`, with a changed slot. Writer request, pending call, `current_pair`, `Evaluator` and `scientific_version` are all set to fail if called, and the case retires as `retired_no_progress`. The G5 and saved-cheat paths go through `finalize_accounting` → `queued_inputs` → `validate_result`. Replay does not queue a duplicate exhaustion.
- **Existing tests:** only the package-boundary expectations changed (`held`/`rejected`/`observation` and the renamed version-drift test). The legacy receipt and the pending/infra controls still assert `extension_execution_pending` explicitly. The direct `replay_writer_early` helper contracts are still asserted. No route, attribution or retry assertion was weakened.

**Optional, not blocking**
1. `factory/extension_writer_rejection.py:70`: no test covers two candidate records at once, or a stress record next to a candidate. Fix: add one subtest each, for example a G1 and a G5 `record.json` together.
2. `factory/extension_writer_rejection.py:104`: the catch-all also turns `writer_receipt`, dispatch-gate and disk errors into `extension_snapshot_changed`. This matches the existing pattern in `extension_public_match.py:196`, so I'm only noting it.
3. `factory/extension_writer_rejection.py:63`: the check that refuses an all-pass entry runs after evidence is staged to a temp directory. Moving it to the start of `complete` would be clearer. Nothing persists before it runs, so this is cosmetic.

## Writer disposition

PASS accepted; no blockers. Per parent instruction, hand back immediately after the passing review. Optional additional conflict subtests and earlier all-pass check are deferred; the existing conflict/refusal logic is unchanged. Evidence-error mapping follows the reviewed public-match precedent. No production change after tested/reviewed 108e65f. No Murphy rows close. factory-simplify remains ff31d87, already merged.

