**Verdict: BLOCK.** One blocking finding is new in this round. The card-effects diff at lines 180–188 (NB1) captures the wrong set of card keys. It records too much (plumbing fields) and misses gate results that were set before the gate ran. Everything else from rounds 1 and 2 is fixed or properly deferred. Two Majors also need one sentence each.

# Goldfish design review (round 3): `docs/designs/stream-d-package-completion.md`

**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW. **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Worktree:** `t3-4ac6b632` @ `54344fc`. I worked read-only, made no edits and started no subagents.
**Read:** `docs/ENGINEERING.md`, the three persona files, both standards, the design (including the Round 2 amendments, which I treated as binding over anything they contradict), and `docs/reviews/stream-d-package-completion-design-{1,2}.md`.
**Code checked:** `gate_pipeline.py`, `gate_attempt.py`, `extension_compare.py` (`Workspace`, `_pending`, `_path`, `_save`, `snapshot`), `extensions.py` (`stages`, `complete`), `diagnosis_dispatch.py` (`CARRY`, `apply`, `replay`, `_dispatch`), `fairness.py`, `carry_over.py`, `durable_checkpoint.py`, `model_runtime.py` (`case_budget_boundary`, model-call card writes), `budget.require_case_budget`, `gate_state.scientific_version`, and in `run.py`: `_opencode`, `public_progress`, `_gate_completed`, `_gate_pipeline`, `early_probe`, `calibrate`, `g3`/`g4`/`g5`/`g10`, `write_and_attack`, `run_gates`, `main`.

**Scope:** I accept the first-slice scope. Comparison, entry capture, the writer-validation and public-match outcomes, and version-drift integration stay open. The package checklist stays unchecked and no Murphy row closes. Lines 9–14 and 173–176 say this clearly.

## Status of the earlier findings

| Finding | Status | What I checked |
|---|---|---|
| NB1: closed list of card keys | **Partly fixed. A new blocker remains (B1 below).** | Switching to a diff with exclusions fixes `owner_contract`. The boundary the diff uses is wrong in two ways. |
| NB2: record looked up inside the retry journal | **Fixed** | `run_gate` → `gate_attempt.execute` → `retry` (`gate_pipeline.py:139`). Checking `replay_gate` before `execute` skips `start()`. A valid record then builds an ordinary `Outcome(ok, info, elapsed)` (`gate_attempt.py:7`) and goes through the normal log, card, `after_gate` and failure handling (`:187-199`). The stale-journal test is specified. |
| M1: evidence roots | **Mostly fixed. One root is missing (M-A).** | `strong_calibrator`, `easy_calibrator`, `early_probe`, `judge_breadth`, `g11-evidence` and `fairness-g1{6,7}-inputs` are real roots. The pilot homes are correctly excluded. |
| M2: gate-details rule | **Fixed** | No live writes. Only changed files or verified gate-cache files are copied. |
| M3: carried fields and infrastructure stop | **Fixed** | `stop_infrastructure` sets `c.stopped` without raising (`gate_pipeline.py:149-157`). Returning at once keeps `infrastructure_exhausted`. Main's `finally` checkpoints it (`run.py:3383-3391`). The clear also runs on completed-row replay. |
| M4: completed-row replay | **Fixed** | `Workspace(...)` matches the dataclass field order (`extension_compare.py:24-33`). `JobAuthority.source_generation` exists (`job_authority.py:23`). Replay never calls `snapshot` or `complete`, which avoids the provenance mismatch in `_execution` and `complete` (`extensions.py:494`). |
| Round-2 nits | **Fixed** | Only shapes `_pending` accepts are recorded. The early probe is disabled with ordinary checkpoints kept. `statement` is captured once. The `apply` check validates the `stress/record.json` bound to the row. The two commits are named. |

**Routes I re-checked, all OK:**
- **Crash after history, before card:** `extensions.active` returns `None`. The new last-row branch in `apply` routes it.
- **New pending diagnosis:** `queued_inputs` → `replay` finds no `decision.json`, so normal dispatch runs. A completed row cannot be reopened.
- **Package failure:** `BudgetError('extension_incomplete')` sets `exhaustion_occurred` (`run.py:3365`). `finalize_accounting` then queues one new exhaustion.
- **All-pass:** `c.stopped` stays False, so the run reaches the ordinary `seal(c)` (`run.py:3383`).

---

## Blocker

### B1. The card diff around `invoke` captures plumbing fields and misses card effects set before the gate ran
**Scope:** NB1 amendment (lines 180–188) and the capture paragraph (lines 67–72). Code: `run.py:216-238`, `model_runtime.py:494/586/677`, `run.py:141`, `durable_checkpoint.py:28`, `run.py:1489/1505`, `gate_pipeline.py:135-137`.

**(a) Too wide: plumbing state ends up in the bench record.**
- Inside one gate's `invoke`, a serial model call completes (G2 freshness, G8/G9 reviewers, G13/G14/G15/G16, the G17 review). `_opencode` then calls `checkpoint_progress` (`run.py:230-236`). The package traversal never sets `calibrator_slot_offset`, so that guard does not stop it.
- That call writes `c.card['durable_checkpoint']` and runs `seal(c, checkpoint=True)` in the middle of the gate.
- Model calls inside the gate also add to `cleanup_errors` (`model_runtime.py:494/586/677`) and pop `router_waits`/`router_interrupted_calls` (`run.py:222-223`). `public_progress` can set `public_progress_error` (`run.py:141`).
- None of these keys are in the exclusion list. The diff records them as gate-owned, and replay restores them.
- **Concrete failure:**
  1. A resumed process replays G8 and G9 within 900 s of each other.
  2. The first `after_gate` checkpoint overwrites the receipt. The second is throttled (`durable_checkpoint.py:23-24`), so G9's stale `durable_checkpoint` receipt from the dead process stays on the card. That receipt reports `remote_durable: true` for an archive from that dead process.
  3. Replay also sets `cleanup_errors` back to the list as it was when the gate ran. Any `usage_reconciliation`/`diagnosis_state` cleanup errors that the crashed run's `finalize_accounting` appended (`run.py:3077-3095`) are dropped.
- This breaks the section 4 rule that plumbing and bench logic stay separate.

**(b) Too narrow: early-reused gates record an empty diff.**
- The extension writer round runs `early_checks` (G15, G3, G4, G5) in the same process before stress (`run.py:1489`, `:1505`). The traversal's `invoke` then returns `c.early[gate]` (`gate_pipeline.py:135-137`) without running `g3`/`g4`/`g5`.
- So the records for those gates capture no card diff. The fresh card still holds the values set during `early_checks`:
  - `bench_workers_effective` and `factory_slots_prepared` (`run.py:2406`, `:2410`);
  - `plain_app_broke` (`:2426`);
  - `reference_fix` and `scenario_keys_match` (`:2435`, `:2464`).
- After a kill and resume, `write_and_attack` raises its terminal handoff straight away, so no early checks run. Replay rebuilds a card without those keys. They are not in `CARRY` either.
- The fresh-vs-replayed card equality test that NB1 itself requires will fail. The implementer then has to choose a fix, which the zero-decision rule does not allow.
- The same gap affects the `prepared_factory_slots` context effect, which G3 sets during the early check.

**Required change (two sentences in the design):**
- **(a)** Name the plumbing exclusions completely. Add at least `durable_checkpoint`, `cleanup_errors`, `public_progress_error`, `router_waits`, `router_interrupted_calls`, `sha256`, `archive`, `r2_object`, `early_gates`, `early_probe`, `roles`, `rotation_slot`, `provider_accounts`, `account_handoffs`, `continuations`, `calls_delta` and `cost_delta`. `carry_over.py:20-34` already lists these keys and could be used as the reference set. Add a test where a gate's model-call path appends `cleanup_errors` and writes `durable_checkpoint`; the record must contain neither.
- **(b)** Pick one rule for early reuse. Either:
  - clear `c.early` at package entry, so G3–G5/G15 go through `check()` and the gate cache. This costs G3 setup, because G3 is not in `REUSABLE`; or
  - define the effects of an early-reused gate as the card and context diff taken around the matching `early_checks` invocation.

  Then make the equality test cover an early-reused G4/G5.

---

## Major

### M-A. G16/G17 replacement-calibration roots are not listed
**Scope:** M1 amendment (lines 197–202). Code: `fairness.py:57-91`.
- If a recorded try has no submitted guard, `review_attempts` runs a replacement under `c.work/fairness-replacement-<sha>/` (`results.json`, a `try-N/execution.json`, `guard/`).
- That replacement's workspace is the one reviewed (`attempt = {**rows[0], ...}`) and is bound into `fairness-g1x-inputs`.
- These roots are absent from M1, so the G16/G17 proof would be incomplete whenever a replacement ran.
- **Fix:** add `fairness-replacement-*` to the G16 and G17 roots, using the calibration-root file rule. Also add `c.work/transcripts/strong-calibrator-<folder>-*.jsonl`, which is the exact transcript glob (`fairness.py:129-131`).

### M-B. Replaying a completed row still passes through the money boundary
**Scope:** lines 138–147 and the M4 amendment. Code: `gate_pipeline.py:163`, `:200`; `model_runtime.case_budget_boundary`; `budget.py:652`.
- `GatePipeline.run` calls `budget_boundary` before every gate. For factory jobs that raises `money_wait` when `spent + outstanding >= committed_total_usd`.
- **Concrete failure:**
  1. A scientific fail at gate K uses up the extension's committed money.
  2. No line-200 boundary runs after a fail, so `complete` commits.
  3. The crash comes before the card is written.
  4. Replay hits `money_wait` at the first gate boundary instead of reproducing `extension_incomplete`. The case parks rather than routing to diagnosis.
- **Fix:** state that completed-row replay spends nothing, so its traversal passes a no-op `budget_boundary`, injected the same way as the other callbacks, or else allow and test this stop explicitly.

---

## Nits
- **Missing record during completed-row replay.** "No fresh evaluations permitted" (line 144) does not name the error raised when `replay_gate` returns `None` on a completed row. Name it, probably `extension_outcome_changed`, and say that `around_gate` raises it instead of calling `invoke`.
- **Progress publication on replay.** Replaying before `execute` skips `publish('running'/'completed', reused=True)`, so public progress will not show replayed gates. Either accept this or publish once with `reused=True`.
- **Disabling the probe.** `_gate_completed` already honours `c.args.no_early_probe` (`run.py:892`). Check whether the package can use that instead of the new `probe=` argument plus the `after_gate` callback. One parameter fewer, if mutating `args` is safe for identity: only five `args` keys go into the journal identity.
- **Version drift on a completed all-pass replay.** `scientific_version` depends on `c.models` and the card's `roles` (`gate_state.py:198-204`). `main` re-runs `pick_models` before the seam. On another VM, a completed all-pass replay may therefore stop at `extension_comparison_pending`. That is consistent with this slice, but say so next to M4 so it is not read as a bug.

## Heilmeier and readiness
- Objective, current state, approach, impact, risks and payoff, cost (no new spend authority; production cost is the stream-d qualification item), and the midterm and final exams are all answered in plain language.
- Phasing is two stable commits.
- The Murphy statement is right: it supports rows 9 and 13 and closes none.
- Readiness fails only on B1, which is an implementer decision forced by the design's own test. M-A and M-B each need one sentence.

## Zoom-out
The architecture is right and needs no new path. It is the ordinary pipeline plus `replay_gate`/`around_gate`, one record per stage, `snapshot()` unchanged, and completed rows replayed rather than regenerated. B1 is a boundary-definition fix, not a redesign.

## Remaining work before PASS
1. **B1(a):** complete the plumbing exclusion list, plus the test.
2. **B1(b):** one rule for early-reused card and context effects, plus an equality test that covers early reuse.
3. **M-A** and **M-B:** one sentence each.

After that, a fresh goldfish should re-review.

## Elephant disposition

B1 accepted. Complete post-invoke scientific projection (with explicit plumbing
exclusions) replaces a diff so early/cache effects survive. Context capture is
also a complete projection. M-A/M-B accepted: replacement roots and no-spend
completed replay are explicit. Fresh review requested before production edits.
