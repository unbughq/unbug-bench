**Verdict: BLOCK** (design round 1 of 2). Two blocking fixes, both small. The partial-first split can stand on its own once they are fixed.

I reviewed `docs/designs/stream-d-partial-entry.md` at d70a205 against `extension_package`, `extension_compare`, `extensions`, `gate_pipeline`, `gate_state`, `run`, `ordinary_freshness`, `diagnosis_dispatch` and `tests/factory/test_stream_d_entry.py`. I made no edits.

## Blocking fixes

**B1. The freshness check would refuse real traversals, including complete ones that work today.** (Design: "For each existing record require the retained support/case file map equals the live full extensions.tree(case), including freshness.jsonl.")
- **Why it breaks:** In factory jobs the G2 gate itself rewrites `case/freshness.jsonl` partway through a traversal. The path is `run.g2` → `ensure_freshness` → `ordinary_freshness.ensure` → `freshness_topup`, plus `finish_freshness_repair`.
- `Records.sources` copies every case file each time a stage is saved. So the stress and G1 records hold the freshness file as it was before G2, and G2 onward hold the topped-up file.
- Under the proposed rule, any traversal where G2 topped up gets refused. That includes the closed complete captures, which contradicts the design's own claim that existing complete entries "produce the same snapshot as before". It also goes against the convention already in `extension_evaluator.py:388` ("Freshness is derived evidence").
- **Why tests won't catch it:** G2 is an authored control in the test file, so it never changes the freshness file.
- **Fix:**
  - Compare every record's case map to the live tree with `freshness.jsonl` left out.
  - Require the live `freshness.jsonl` to equal the copy in the last retained record, and in every retained stage that reads freshness. Per `gate_state.inputs` those are G2, G8 and G9.
  - Decide in the design whether stress also reads it; don't leave that to the implementer.
  - Add exams:
    - a G2 control that appends one freshness row mid-traversal, after which entry still succeeds for both a closed and a partial capture;
    - a freshness change after the stop, which leads to `extension_comparison_pending`.
  - State that a budget stop in the middle of a G2 topup stays held.

**B2. The design says which existing tests keep their assertions, and that list is wrong.** It says full-capture tests keep their hold assertions, but:
- `test_malformed_pointer_close_and_missing_g3_hold`: the `closed.unlink(); self.pending()` line must flip to "same snapshot".
- `test_infrastructure_has_no_close_marker`: will now return stress pass with frontier 1 instead of pending.
- `test_new_pointer_prevents_old_traversal_filling_interruption`: still ends pending, but only because the earlier `run_gates` left `card.gates` labels (G1–G4 pass) from a previous traversal. It no longer tests what its name says. Reset `gates` inside the test and state the new expected snapshots: crash at G1 gives frontier 1; crash at G4 gives G1–G3 observed with the frontier at G4.
- **Exact labels:** test 2 says a gate "status crashed", but `stop_infrastructure` writes `card.gates[gate] = 'invalid-infra'` and sets `infrastructure_gate.exhausted`. Name that real value, and state the rule plainly: only `'pass'` or `'fail'` at or after the hole refuses. Every refusal asserts `^extension_comparison_pending$`.

## Optional

1. **The `reached_stages` parameter isn't needed.** At a missing record, `Records.evidence` returns None, so `snapshot` already marks exactly that stage `pending` and everything after it `unreached`. `entry` already knows where the hole is, so it can assert that the hole is the only pending row and relabel it `unreached`. `validate_snapshot` accepts that and the frontier doesn't move. This leaves the shared `comparison.snapshot` untouched and removes test 6. Keeping the parameter is also fine: its default leaves current behaviour unchanged.
2. **Replace "no score is lost" with the real guarantee.** If a stage's capture failed and the last saved card is out of date (for example after a hard kill), that score is lost and the stage is treated as unreached. That is safe: `extensions.progress` treats an unreached frontier like a failed one, so the next round must pass that stage either way. Also, a scorecard left over from an older traversal leads to a permanent but safe hold. Say both explicitly.
3. **Define "pinned versions"** as `comparison._versions(workspace(owner))` computed after the G3 preload. Also note that when G3 has no record, the unreached later stages get versions from the live worker count. That matches how a failed-frontier entry behaves today.
4. **Plain-language objective.** The Problem paragraph is dense with jargon; the Heilmeier standard asks for none.

## Checks that pass
- **No invented score, no rerolls:** entry only reads records. Nothing is evaluated, no G3 setup runs, and a failed or corrupt record never becomes a hole.
- **Close marker vs genuine missing proof:** a marker that exists is still validated exactly as today. A hole refuses if any later record exists or the card marks that stage or a later one pass or fail.
- **Checkpoint-card labels:** checking `c.checkpoint_card` matches the admission path. `admit_extension` runs at resume start with `prev_card`.
- **Holds and unchanged areas:**
  - A missing or failed stress stays held, and so does a legacy run with no pointer.
  - Activation, limits, attribution and gate versions are unchanged.
  - No Murphy row is closed. The design only claims support for rows 9 and 13.
- **Progress can't be gamed:** an outcome that fails at the entry's unreached frontier counts as `no_progress`.
- **Split stands alone:** it only widens entry for recorded partial traversals. Legacy runs still return the existing pending hold until their own increment.
- **Land12 precondition:** c18edce is not yet in `factory-simplify`, so it still has to merge before implementation, as the design says.

The design fix needs one more round (round 2, the last). If B1 or B2 is still open after round 2, it goes to the parent.

## Writer disposition

B1 fixed with non-freshness tree equality for every record, explicit stress historical-evidence treatment, and equality to the last record plus G2/G8/G9 for current freshness. Mid-G2 topup interruptions stay held. B2 fixed with exact existing-test dispositions and invalid-infra label. Adopt optional simplification: leave comparison.snapshot unchanged, normalize only the prevalidated missing record's pending row to unreached. Record lost-score/stale-card limitations and exact version pinning. Fresh round 2 must verify the fixes.

