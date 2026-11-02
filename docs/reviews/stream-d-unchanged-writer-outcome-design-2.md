**BLOCK.** One blocker is left. Everything else from round 1 is fixed and checks out against the code.

## Blocker

**B2: the design turns a writer that only adds search rows, with no repair request, from a run that works today into a new stuck stop.**
- **Where:** "Producer and proof": the `(repair_requested or extension is not None)` change, the package-entry rule that "a hash-only unchanged receipt with a changed full tree is `extension_snapshot_changed`", and the closing claim that such a writer "remains an evidence stop".
- **Why:** `case_hash` skips `freshness.jsonl` (`factory/run.py:891-898`), and the writer prompt tells the writer to append every search there.
  - **Today:** an extension writer whose `repair_requested` is False and who only appends search rows does not hit either unchanged check (`run.py:1364` and `run.py:1521` both need `repair_requested`). The case goes on through G1, early checks, stress and the gates. That is a real evaluation of a different case, because G2 reads that file. It is not a re-roll.
  - **Under this design:**
    - On a fresh or resumed run, the widened check raises `unchanged_repair` because `case_hash` matches.
    - The package then finds that the full tree differs and raises `extension_snapshot_changed`.
    - At package entry, the same completed receipt is refused before `write_and_attack` ever runs.

    Either way the history stays active with no way forward: a new pit stop.
  - This breaks two of the design's own statements: "All other writer/infra/provider/money/cancel results keep their route", and "remains an evidence stop". That second one is only true when `repair_requested` is True (round-1 M1). Round 1's B1 showed the False case happens after budget or infrastructure exhaustion stops.
- **Fix:** base the extension-only stop on full-tree identity, not `case_hash`.
  - In both `write_and_attack` checks, use `repair_requested or (extension is not None and extensions.digest(extensions.tree(c.case)) == extension['entry']['case_sha256'])`.
  - At package entry, if the receipt tuple matches but the full tree differs, fall through to today's route instead of refusing:
    - repair True → the existing `unchanged_repair` stop (this is the deferred M1 case);
    - repair False → `write_and_attack` carries on into G1 and stress as it does today.
  - Keep `extension_snapshot_changed` only after `stress_review_unresolved:unchanged_repair` with repair True, and for proof or tree tampering.
  - Add a test: freshness-only change, `repair_requested` False, previous card with no `failed_gate`. It must reach G1 and stress, with no terminal proof and no snapshot refusal.

## Nits

- **N3:** "If the entry frontier names a failed stage" should say what happens when the frontier row is `unreached` rather than `fail`. Then `failed_gate` is absent, and `_held_stage` (`diagnosis.py:244-248`) gives `'unknown'`. Say this and test that the next diagnosis accepts it.
- **N4:** `extension_incomplete` is raised unconditionally. That is only right because an entry that passed every stage cannot exist. Say so, or refuse if `entry.frontier == len(stages)`.

## Checked and sound

- **B1 on the repair-True path:**
  - Every writer that finishes inside `admit_extension`'s `pending_call` (`diagnosis_dispatch.py:479-481`) is seen at package entry.
  - A pending writer that finishes via `writer_call_done` (`run.py:1355-1365`) or the continuation loop (`run.py:1521`) stops before G1, early checks and stress.
  - `attack_unresolved` (`run.py:1016`) does not change `attack-state.json`, so `writer_receipt` still sees the completed receipt afterwards.
  - Ordinary non-extension behaviour is unchanged.
- **Receipt check:** `writer_receipt` (`extensions.py:321-360`) freezes `before_repair_sha256` and `repair_requested`. `output_sha256` can still change, so it is correctly checked against `case_hash`.
- **Saving the outcome:** `_save_case` already takes `evidence_root`. The `extension-terminal/` key passes `validate_snapshot`. `atomic_json` sorts keys, so a retry writes the same bytes. `_verify_case` on retry ignores `source_generation`.
- **Next diagnosis:**
  - `_trigger` queues once `outcome_sha256` is set.
  - In `apply`, `comparison_pair` on identical entry and outcome gives `no_progress`, not pending, even after version drift. So it reaches `admit_extension` → `entry` → `subsequent_entry`, and the verifier runs before `current_pair` or `Evaluator`.
  - `retired_no_progress` is an existing label (`extensions.py:396,403`).
- **Card fields (M2):** they are fully specified. `_held_stage` reads only `failed_gate`, which the design now sets from the entry frontier.
- **M3 and N1-N2:** addressed. The scope stays clear of progress and schema changes, activation, limits and attribution, and no Murphy rows are closed.

I made no edits, live or paid calls, or subagents. Per the brief there is no round 3, so the parent decides what to do with B2.

## Writer disposition

B2 remains open. Stopped after round 2 under the parent's review limit; no implementation or round-3 review. Parent decision required. N3 and N4 are recorded for that decision.

