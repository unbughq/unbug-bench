**Verdict: NOT PASS.** This is diff review round 1 of 2. One blocking finding is open.

I reviewed `e1087df..b038eba` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` (branch `t3/stream-d-implementation`, HEAD `b038eba`). I checked it against `docs/designs/stream-d-public-match-outcome.md` and both of its design reviews, in Mode REVIEW with `zoom_out` and `implementation_readiness` and the implementation-readiness standard. I edited, committed, pushed and delegated nothing. The worktree is still clean.

## Blocking

**B1. Completed replay and crash recovery stop working once the saved HTTP receipt is 24 hours old. (Blocker)**
- **Where:**
  - `factory/extension_public_match.py:129` (`_confirmed`) calls `late_recovery.freshness_proof`.
  - `freshness_proof` (`factory/late_recovery.py:80-81`) calls `freshness_retrieval.load`.
  - `load` (`factory/freshness_retrieval.py:110`) requires `at <= now < at + 24h`, with `now` taken from the live clock.
  - `verified` (`extension_public_match.py:210`) and `complete` (`:186`) both go through this path.
- **Effect:**
  - The design says completion and replay are built only from retained bytes, and that "No age expiry rerolls proof".
  - In practice the retained proof checks against the current time. After 24 hours, `verified` raises `extension_snapshot_changed`.
  - That makes `subsequent_entry` refuse with `extension_snapshot_changed` where it should refuse with `retired_no_progress`. `completed_route` and `package.run` refuse the same way.
  - A crash after the confirmation cache was published, resumed more than 24 hours later, also refuses instead of completing.
  - The next diagnosis and resumes after a pause are exactly the paths where more than 24 hours will often have passed. So in practice the feature becomes a pit stop.
- **Proof:** I ran a focused offline check from `/tmp/pm-review`. It subclasses `PublicMatchTests`, runs `confirm()` and `complete()`, and checks that `verified` is True. It then sets `freshness_retrieval.datetime.now` 25 hours ahead. Result: `verified` raised `extension_snapshot_changed`. All 15 existing tests stamp `at=now`, so none of them can catch this.
- **Required fix:**
  - Give `freshness_proof` an explicit no-clock mode for retained proof. Pass it from `extension_public_match._confirmed` only.
  - In that mode, validate the retrieval bytes and receipts without the current-time window. Keep: receipts are a list matching the rows, URLs match, `at` parses, each body's hash matches, and the retrieval digest equals `confirmation.retrieval_sha256`.
  - `cleared_stress` must keep the current 24-hour check unchanged.
  - Add tests that move the clock more than 24 hours ahead and check that:
    - `verified` and `stop` still give `extension_incomplete` with no fetch or review;
    - `subsequent_entry` after `diagnosis()` refuses `retired_no_progress`;
    - recovery after the cache was published but before completion still completes.

## Major

**M1. The shared validator changes how the old clearance path fails. (Major)**
- **Where:** `factory/late_recovery.py:77-78`.
- **What changed:**
  - `extensions.tree(verdict.parent/'retrieval')` runs outside the `try`, and raises `BudgetError('extension_snapshot_invalid')` on any symlink.
  - Before, a symlinked body was rejected inside `load`. That raised `InvalidInfra`, which became `ValueError('missing stress freshness retrieval')`.
  - The direct reads also changed. A missing `review-completed.json` now raises `FileNotFoundError` instead of `Refused`. A verdict that isn't a dict now raises `AttributeError`, where it used to raise `Refused`.
- **Effects on the callers:**
  - `extension_package.py:291` catches only `(OSError, ValueError, KeyError, TypeError)`. So a symlinked retrieval body now escapes as `extension_snapshot_invalid` instead of `refuse('extension_execution_pending')`.
  - `gate_marker` → `mark_gates` (`run.py:3065`, ordinary non-extension runs) now raises an extension-labelled `BudgetError` where it used to raise `ValueError`.
  - The brief requires the shared validator to keep the old policy, and the design says `cleared_stress` keeps its rules.
- **Required fix:**
  - Map the new failures inside `freshness_proof` to the old exception types: catch `BudgetError` and `OSError` from `tree` and the reads, and raise `ValueError` through `require`. Alternatively, move the `tree()` check into the public-match path only.
  - Add a clearance test with a symlinked retrieval body that checks `extension_execution_pending` at the `:291` site.

## Nits

- **N1.** `capture.record` (`extension_public_match.py:90-106`) is not wrapped the way `complete` is. A corrupt existing sidecar or receipt (for example, an envelope with no `record`, or a `KeyError` on `binding`) escapes `loop_freshness` as a raw `KeyError` or `JSONDecodeError`, not as `extension_snapshot_changed`. Wrap the body with the same exception list → `refuse()`.
- **N2.** Some decision-table rows have no test, although the design asks for every row to be covered:
  - a confirmation whose binding is for another request (must return False);
  - an entry identity that differs from history (must refuse);
  - a reviewer whose family matches the builder or attacker (refuses);
  - a symlinked live proof file before completion. Only the retained marker symlink is tested.

  Add one assertion for each.
- **N3.** `stop` also writes `gate_results={'G2': detail}`, which the design doesn't mention. It looks harmless; note it in the design or the report.

## Checks that pass

- **Scope:** the change covers only the confirmed public-match terminal. There is no blocking-stress, factory-bug-return or lane 2 work. `diagnosis_dispatch` and `propose` are untouched, and `run.py` gains only the recorder hook before `confirm_hits`.
- **Hook order:** unchanged-writer first, then public match, then the existing logic, in `completed_route`, `run` and `subsequent_entry`. `run` checks the live full tree before `stop`, and the freshness stop is re-raised when completion fails.
- **Scored versus infrastructure:** the outcome is one stress fail with `{confirmed_public_match:True, freshness:<deterministic info>}`, all other stages unreached, and `frontier=0`. No pass is invented.
- **Accepted design-review items:** the M-A detail is built only from retained bytes and never reads the card. The `.get('freshness_review', [])` default matches `loop_freshness`.
- **Determinism:**
  - `_binding` is portable (stage, version, case) and `_calibration` is None for stress, so passing different `args` to `complete` and `verified` doesn't matter.
  - Execution comes through the new keyword argument, and its validation matches the five-key schema.
  - Version, slot, seed, model and card drift tests, and the retry-after-rename test, pass.
- **No paid work:** the replay, recovery and next-diagnosis tests forbid the writer, gates, Evaluator, fetch and reviewer, and money stays flat.
- **Murphy register:** unchanged, so no row closes.
- **Diagnosis:** `batch_service.DIAGNOSIS_ENABLED = False` is unchanged.
- **Suite record:** source `66f0351`, 175 scripts, 0 failed, exit 0. The `66f0351..b038eba` diff is docs-only (design wording plus the report and log).

## Skipped checks and risk

- I did not rerun the full suite or the existing test files, as instructed. The only thing I ran was the one focused 25-hour check above, offline, with no workers, network, secrets or background processes.
- I did not trace every downstream handler of `mark_gates` to see exactly what each changed exception type produces. M1 is graded on the policy change itself.
- **Residual risk:** if an intent is excluded in the final round and `c.case` changes before the stress record is saved, a resumed `complete()` would refuse instead of continuing. I did not find a real writer of that path, but nothing tests it.

**Final: NOT PASS. B1 must be fixed (no-clock validation of retained proof, plus tests with the clock moved ahead). M1 should be fixed in the same round.**

## Elephant disposition

B1 and M1 accepted in full; no blocker rejected. Add an explicit retained-proof clock policy used only by the public-match validator, preserve ordinary clearance expiry and failure mapping, and cover delayed completion/replay/next diagnosis plus clearance symlinks. N1–N3 also accepted: normalize capture failures, fill decision-table assertions, and document gate_results projection. Fresh round-2 diff review will verify these fixes; no self-verification of B1.
