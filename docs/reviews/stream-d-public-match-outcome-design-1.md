**Verdict: NOT PASSING.** There are 4 blockers. Each one makes the implementer decide something the design should have decided, and some of those decisions would mean paid re-runs or permanent stops.

I reviewed `docs/designs/stream-d-public-match-outcome.md` at `6108fa0` against base `3a50896` and against `184e81c` (`factory/extension_package.py` and `factory/extensions.py`, both read-only). Mode REVIEW, with the zoom_out, design_critic and implementation_readiness personas and the Heilmeier and implementation-readiness standards. I ran nothing and wrote nothing.

## Blockers

**B1. The G2-only outcome makes the next comparison re-run paid work.**
- **Where:** design lines 81–89 and 72.
- **Evidence:** the stage order is `('stress', G1, G2, …)` (`extensions.stages`).
  - `extensions.progress` (`factory/extensions.py:75-86`) returns `'pending'` as soon as the entry had a stage that passed and the outcome has that stage as anything other than pass or fail. Entries need stress to pass (`propose`: `stages[0]['status'] != 'pass'` means retire). So a stress-unreached plus G2-fail outcome is always `'pending'`.
  - In `184e81c`, `subsequent_entry` goes `current_pair`, then `compare`, then `Evaluator`. That re-evaluates stress and G2 on the retained outcome: a new retrieval and a new reviewer call. That is exactly what this slice says must never repeat.
  - `diagnosis_dispatch.py:243` stops on `extension_comparison_pending` (a pit stop), and `propose` raises the same.
  - Unchanged-writer avoids this with an explicit `if unchanged_outcome(...): refuse('retired_no_progress')` in `subsequent_entry`. This design has no equivalent.
  - Precedent already exists: `extension_evaluator.py:211` maps `freshness_public_match` to a **stress fail** with detail `{'confirmed_public_match': True, 'freshness': …}`.
- **Fix:** decide the outcome shape and how the next diagnosis treats it. Either:
  - record it the way the evaluator already does (stress fail, so `progress` gives `regression` and the case retires with no paid comparison); or
  - keep G2-only, and add a verified public-match check in `subsequent_entry` that refuses `retired_no_progress`, plus define what `diagnosis_dispatch`/`propose` do so it doesn't stop as pending.

  Either way, add a test that the next diagnosis makes no evaluator, fetch or reviewer call. "Comparison at a later diagnosis owns policy" (line 72) is not enough.

**B2. Retrying after a crash can't rebuild byte-identical evidence, so the case stops for good.**
- **Where:** lines 74–95, and the line 118 exam.
- **Evidence:** in `184e81c`, `_save_case` renames `extension-snapshots/<id>/outcome` into place before `_write(history)`. On retry, the existing target goes through `_verify_case`, which needs `tree(evidence) == snapshot['evidence']` exactly. The proposed evidence isn't deterministic:
  - The `Records.save` record embeds `project(c.card)`. Card keys that aren't excluded (`loop_freshness`, `freshness_confirmation`, `stress_review`, `resume_rereview`…) differ after a restart.
  - `comparison._save` embeds `_execution(w)`: seed, slot and the `UNBUG_FACTORY_SLOT` environment variable. These change after relaunching on another slot.

  So the line-118 exam ("kill between outcome case/evidence and history") would hit `extension_snapshot_changed`.
- **Fix:** name exactly which bytes make up the evidence, and make them a pure function of the retained proof. That means a fixed execution identity (or one taken from the receipt) and no card projection. Alternatively, define a rule to adopt an already-retained outcome directory after validating it. The test must compare a second completion attempt byte for byte, including a different slot.

**B3. The rules for when a sidecar is absent, stale or tampered aren't defined, and drift destroys finished proof.**
- **Where:** lines 29–31, 54–58 and 63–68.
- **Evidence:**
  - Re-review renames `round-N.json` to `-superseded-…` (`run.py:~1583`) but leaves `round-N.match.json` in place. After that, the sidecar's `source_sha256` no longer matches. The design calls a mismatch "tampered" and refuses `extension_snapshot_changed`, which is a permanent stop.
  - `complete` needs `scientific_binding(receipt.binding) == scientific_binding(r.attack_binding(c))`. `scientific_binding` drops only seed and bench workers/roles, so a plumbing or source roll at a checkpoint between the stop and the resume fails this check.
  - The design doesn't say whether that returns False (fall through to `write_and_attack`: the binding has changed, so a paid re-review, and the finished proof is thrown away, against salvage-runs) or refuses.
  - Lines 69–71 apply retained-version validity only *after* completion.
- **Fix:** add an explicit decision table for:
  - no sidecar;
  - sidecar for a superseded or different report;
  - current-version drift with intact retained proof;
  - mixed confirmed and unresolved rows (no `freshness-verdict.json` gets written, `run.py:2381`);
  - bytes that are really corrupt or are symlinks.

  For each, give the result: return False, refuse, or complete using the retained binding. Also say whether the sidecar is deleted or ignored when its report is superseded. I recommend completing from the receipt's own retained binding (as replay does), so source drift can't cause a paid re-review.

**B4. The proof-copy, `Records` and snapshot pipeline can't be built as written.**
- **Where:** lines 74–80 and 96–98.
- **Evidence:**
  - `Records.save` doesn't take "exact validated facts and support". It collects support itself through `self.sources()`, which globs `c.work` for `g2-confirm-*`, `freshness-verdict.json` and `confirmation-retrieval-*` (`184e81c` `extension_package.py:~160`). Copies under `public-match-proof/` aren't matched. On a live `c.work` it would pick up *every* `g2-confirm-*` directory.
  - `Records.root` sits in `c.work/extension-package/<id>`. If it's written live and the process crashes, the retry hits `if target.exists(): refuse()`.
  - "Private temporary workspace" vs live `Records` root is never resolved.
  - `freshness_proof(c, attack, report, proof)` resolves `c.work/<verdict_path>` and `case_hash(c)`, but `verified` has to check *copied* proof against the retained outcome case. The design gives no root parameter or rebasing rule.
- **Fix:** specify the exact pipeline. I recommend dropping `Records.save` here: copy the proof into the temporary work root under its original relative names, then call `snapshot(w, …, observations={stage: (ok, detail, [those paths])})` so `comparison._save` owns support. State `Workspace.case`/`work` for completion and for `verified`, and give `freshness_proof` an explicit root/case argument (or say it is called on a `SimpleNamespace(work=copied_root, case=retained_case)`).

## Major

- **M1. Which case is the "retained candidate case" (line 74)?** `_save_case` hashes live `c.case`. The sidecar binds `case_tree_sha256` from live `c.case`, which includes the `freshness.jsonl` the stress tester appended to. State that it is live `c.case`, checked against the sidecar's `case_tree_sha256`. Also say what happens if a checkpoint restore changes only `freshness.jsonl` (return False vs refuse).
- **M2. A crash window is missing.** A kill after `confirm_hits` writes `freshness-verdict.json` but before the sidecar is written isn't covered. State the expected restart path (reuse the retained receipt through `confirm_hits`, no new reviewer call), and add it to the midterm exams next to "stopped-after-proof restart".
- **M3. The sidecar's reach isn't scoped.** Writing it "for factory jobs" in `loop_freshness` also fires inside `extension_evaluator` comparisons and in ordinary non-extension runs. `attacks/` is also a diagnosis input (`diagnosis.py:693`) and a stress `Records` source. Say whether that's intended. If not, limit the write to the active-extension path.
- **M4. The order of the two completed-outcome checks contradicts itself.** Line 68 says unchanged-writer keeps priority; line 69 says `verified` runs "first". Give one order for `completed_route`, `run` and `subsequent_entry`. Also, an outcome whose evidence contains `extension-terminal/<id>-public-match.json` but fails verification must refuse; it must never fall through to `Records.load('stress')` or `refuse('extension_outcome_changed')`.

## Nits

- **Heilmeier:** the objective is jargon-dense ("sidecar", "land8", "G2"). The Impact answer (stopping the pit stop, avoiding a second paid review) is only implied.
- **Line 41:** confirming that `len(blocked)==confirmed_hits` deliberately excludes mixed confirmed and unresolved rows (they stay `freshness_public_match` with history open) would stop a well-meaning "fix".

## What holds

- Same-family reviewer rejection.
- The no-follow and retrieval-digest reuse.
- Not making up a pass from the public scorecard.
- Reusing `extensions.complete(evidence_root=…)` with no other history writer.
- Real artifacts in the exams.
- Not closing Murphy rows.
- Scope matches the `be567f9` slice-table row: Medium, 3–5 h.

The `attack-state` receipt really is `validated`/`review_completed` before `loop_freshness` runs (`run.py:1611-1616`), so the producer's precondition can be met.

**Result: NOT PASSING** (B1–B4 open). Round 1 of at most 2.

## Elephant disposition

Accepted B1–B4, M1–M4 and both nits. Replace the first design with one deterministic proof-only stress-fail terminal contract and explicit next-diagnosis retirement. No blocker rejected. Round 2 is the final design review allowed for this slice.
