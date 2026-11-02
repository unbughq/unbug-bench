**BLOCK** (round 1 of 2). One blocker, three majors, two nits.

## Blocker

**B1: a writer that changes nothing but had no repair request still re-runs stress and gates.**
- **Where:** "Producer and proof", the condition that `repair_requested` must be True; the first sentence of the opening section.
- **Why:** `admit_extension` (`factory/diagnosis_dispatch.py:476-478`) sets `repair_requested = bool(r.writer_feedback(c, previous))`. `writer_feedback` (`factory/run.py:1135-1142`) returns `None` whenever the previous card has no `failed_gate`. That can happen after a `budget_exhausted` or `infrastructure_exhausted` stop whose frontier is not a recorded failed gate.
  - In that case an unchanged writer never raises `unchanged_repair`. Both checks require `repair_requested` (`run.py:1364` and `run.py:1521`).
  - `write_and_attack` then moves on to G1, stress and gates on a byte-identical case. That is a re-roll of a retained failure. It contradicts the design's own "No stress or gate is run to rediscover the same result" and the no-reroll rule.
  - The design's claim that "Today the writer loop stops at unchanged_repair" holds only when `repair_requested` is True.
- **Fix:** the writer finishes inside `admit_extension`'s `pending_call` before `extension_package.run` is called, so the package-entry check already sees every completed extension writer. Qualify on `type(repair_requested) is bool` (or drop it), keeping `before_repair_sha256 == output_sha256 == case_hash` plus full-tree identity. Add a test with a previous card that has no `failed_gate`. The current fixture (`tests/factory/test_stream_d_execution.py:52`, `failed_gate: 'G8'`) only covers the True case.

## Major (non-blocking)

**M1: a writer whose only change is new search rows stays stuck.**
- `factory/prompts/builder.md:55` tells the writer to append every search to `freshness.jsonl`. `case_hash` ignores that file (`run.py:896`).
- So a repair-round writer that searches and then changes nothing is plausible. The design routes it to `extension_snapshot_changed`, which leaves an active history forever. That is the same dead end, in a narrower case.
- Refusing is the right scientific call, because G2 reads that file. But the design should list it with the other open outcomes, and narrow "removing this active-history dead end" to exact full-tree identity.

**M2: the card fields at the terminal stop are left to the implementer.**
- For `extension_incomplete`, diagnosis takes the held stage from `card['failed_gate']` (`diagnosis.py:244-245`).
- After `attack_unresolved`, the card carries `stress_review={'status':'unresolved','reason':'unchanged_repair'}` and whatever `failed_gate` was left over.
- The design doesn't say what `failed_gate`, `failed_detail` and `stress_review` should be on the fresh path and on replay. My suggestion: set `failed_gate` to the entry's frontier stage (or remove it), and state what `stress_review` holds. Test that the diagnosis input shows the retained entry stage, not a leftover value.

**M3: the cost section is wrong.**
- "There is no new model spend" is false. The design queues one more diagnosis model call.
- It should say that the call is the only spend, and why going through the existing diagnosis route beats retiring the case directly: it keeps one route, and diagnosis can still choose factory_bug.

## Nits

- **N1:** "row/entry binding" in the replay verifier is vague. List the exact equalities:
  - proof `extension_id`, `round` and `writer_operation_id` against the row;
  - `receipt.operation_id`, `extension_id` and `round` against the row;
  - `entry_sha256 == digest(row['entry'])`;
  - proof `case_sha256 == row['entry']['case_sha256']`.
- **N2:** say where the temporary staging directory lives. Use a system temp dir or a `.terminal-` directory under `extension-snapshots/<n>/`, never under live work, because a kill skips `finally`. Also say the proof is written with `atomic_json`, so bytes match on retry.

## Checked and sound

- **Authentication:** `writer_receipt` checks the immutable intent, the reservation and continuation. The tuple fields exist exactly as described (`complete_writer`, `run.py:381-386`).
- **Full-tree check:** `_verify_case` plus `digest(tree)` correctly covers the gap left by `case_hash`.
- **Evidence staging:** `_save_case` already accepts `evidence_root`, so only `complete` needs it passed through. Rename-then-history ordering and existing-target verification give a safe retry.
- **Next diagnosis:** `_trigger` queues it once `outcome_sha256` is set. On the next close_to_passing, dispatch computes `no_progress` (not pending), so it reaches `admit_extension` → `entry` → `subsequent_entry`. There the verifier runs before `current_pair`/`Evaluator`, so version drift cannot cause paid re-evaluation.
- **Lagging card:** `completed_route` and `run` cover history written before the card was published, and `read()` already tolerates a lagging `outcome_sha256`.
- **Scope and Heilmeier questions:** answered. No progress or schema changes, and no Murphy rows are closed.

Nothing was edited, and I made no live or paid calls.

## Writer disposition

B1 accepted and addressed: both repair_requested values qualify; the extension-only unchanged checks inside write_and_attack stop before checks even when the writer finishes there. M1–M3 and N1–N2 are addressed in the revised design. No implementation yet; fresh round-2 review requested.

