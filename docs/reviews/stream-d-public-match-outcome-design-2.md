**Verdict: PASS. No blockers are left open.** Round 2 of at most 2. There is one Major finding and a few nits; none of them needs the implementer to invent policy or an interface.

I reviewed `docs/designs/stream-d-public-match-outcome.md` at `1a083a4` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. I checked it against the worktree code and against the `factory/` changes in `184e81c`, which I read with `git show` and did not merge. This was Mode REVIEW, using the zoom_out, design_critic and implementation_readiness personas and the Heilmeier and implementation-readiness standards. I ran nothing, wrote nothing and delegated nothing.

## Round 1 findings

**B1 (paid re-run at the next comparison): resolved.**
- The outcome is now a stress fail, exactly as `extension_evaluator.py:211-213` already records a public match: `{'confirmed_public_match': True, 'freshness': …}`.
- At the next comparison, `extensions.progress` sees entry stress pass and outcome stress fail, so it returns `'regression'` (`extensions.py:83-84`). `propose` also refuses with `retired_no_progress` (`extensions.py:396`).
- The `verified` check sits in `subsequent_entry` before `current_pair`, `compare` and `Evaluator`, and after the existing live-case check (`184e81c` `extension_package.py:575`).
- The production route really does reach that check:
  - `run.py:3354` calls `dispatch(comparison_route=True)`;
  - `diagnosis_dispatch.py:242` skips the pending stop;
  - `admit_extension` → `entry` → `subsequent_entry` runs before any writer call (`diagnosis_dispatch.py:471-472`).

**B2 (retry can't rebuild identical evidence): resolved.**
- The receipt bytes now come only from retained inputs:
  - the recorded execution, through a `_save` keyword argument;
  - the recorded versions and `source_generation`;
  - no card projection.
- The source files are copied byte for byte (`_save`, `extension_compare.py:149-176`), and `atomic_json` sorts keys (`registry.py:22`).
- A retry after the outcome directory is renamed gets adopted through `_save_case`'s target-exists `_verify_case` branch (`extensions.py:179-181`).
- `_load` checks the shape of the retained execution but does not compare it to the current slot (`extension_compare.py:131-133`).
- One remaining gap is listed as M-A below.

**B3 (sidecar absent, stale or tampered): resolved.**
- The decision table covers every case asked for: absent, superseded, source-SHA mismatch, identity drift (including changes only to `freshness.jsonl`), version or slot drift, exclusion, mixed rows, and corrupt or symlinked files.
- The superseded rule matches the real rename pattern: `round-N-superseded-<hex>.json` at `run.py:1585`.
- Drift completes using the recorded binding, so no re-review is paid for.

**B4 (proof-copy and `Records` pipeline can't be built): resolved.**
- `Records.save` and `sources` are no longer used, and the list of copied files is explicit.
- The `_save` support names land under `comparison-support/stress/<original>`, and that is exactly where `verified` looks for the metadata.
- `freshness_proof` takes its work and case roots explicitly. This copies the `SimpleNamespace` pattern `cleared_stress` already uses (`late_recovery.py:73-74`), including models and reservation taken from the binding.
- Rebuilding the search binding from `intent.rows` checks those rows against the confirmation (`admission.py:20-29`).

**M1 (which case is the "retained candidate case"): resolved.** It is the live `c.case`, including `freshness.jsonl`. The full tree is checked before and after copying, and a change only to `freshness.jsonl` is refused.

**M2 (missing crash window): resolved.** Both crash windows are defined and both are in the exams:
- killed after the intent is written but before the confirmation is published;
- killed after publication but before package completion.

**M3 (sidecar reach not scoped): resolved.** The `capture` context manager is installed only around `package.run`'s call to `write_and_attack`, and it checks that the context is the same owning `c`. Evaluator children run on a copied context, so they never record. The design states that `attacks/` being a diagnosis input is intended.

**M4 (contradictory check order): resolved.** The order is now one rule: unchanged-writer first, then public-match, then the existing logic. An invalid marker that is present always refuses. The two outcomes cannot collide: unchanged-writer looks for `extension-terminal/<id>.json` at the top of the evidence, while public-match uses `comparison-support/stress/extension-terminal/<id>-public-match.json`.

**Nits from round 1: resolved.** The objective is now in plain words, the benefit is stated, and mixed rows are explicitly excluded.

## New findings

**M-A. The detail inside `freshness` is never defined. (Major)**
- **Where:** "Observation and next-diagnosis contract" and "Deterministic copy / snapshot pipeline" ("detail above").
- **Evidence:**
  - The evaluator's detail is `c.card['loop_freshness']`, which is `loop_freshness`'s `info` dict: `{rows, requested, verdict_path, outcome, reason}` (`run.py:1066-1093`).
  - The design forbids reading the mutable card, and `verified` requires an exact rebuild. So `info` has to be derived from retained bytes.
  - `requested` is `len(dict.fromkeys(result['freshness_review']))`. That value is neither in the intent nor passed to `recorder(c, rows, report)`.
- **Fix (one line):** define the detail as `freshness = {rows: len(intent.rows), requested: len(dict.fromkeys(attack_report(<copied report>)['freshness_review'])), verdict_path: <freshness-verdict>.verdict_path, outcome: 'public_match', reason: 'same_bug'}`, and use it for both the receipt and `stop`'s `failed_detail` / `loop_freshness`.
- **Why it doesn't block:** the determinism tests would already catch any reading that isn't deterministic.

**Nits**
- Name where the intent's `versions` come from: `comparison._versions(workspace(c, r))`, the same source `subsequent_entry` uses at `extension_package.py:490`.
- In `run`, the completed public-match branch should check `digest(tree(c.case)) == row.outcome.case_sha256` before `stop`, as the unchanged-writer branch does. The design states this only for `subsequent_entry`.
- Say what the recorder does when an intent already exists for the same report but its rows differ: keep the existing bytes, and completion then refuses under the table.
- Name the `Workspace` fields used for the terminal `_save`: `case=tempcase`, `work=tempwork`, `execution=None`, with the override passed only through the new keyword argument.

## Remaining checks

- **Scope:** limited to the confirmed public-match terminal outcome. No lane 2 freshness-only, rejected-writer or partial-entry work, and no later lane 1 slices. `diagnosis_dispatch` and `propose` are left unchanged, which is correct.
- **Heilmeier and readiness:** both standards are met. The file list, interfaces, decision table, one-increment plan, exams on real artifacts, $0 inference cost and 3–5 h estimate are all present.
- **Murphy rows:** none are closed, as required. Diagnosis stays disabled.

**Final result: PASS (no blockers).** Fix M-A while implementing, and check it in the diff review.

## Elephant disposition

PASS recorded. M-A and all nits accepted and pinned before implementation. No blocking finding rejected. Design review budget exhausted (2/2); implementation follows this contract. No row closes.
