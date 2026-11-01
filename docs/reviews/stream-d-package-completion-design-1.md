# Goldfish design review: `docs/designs/stream-d-package-completion.md`

**Reviewer:** fresh goldfish (Opus 5.5). Read-only, no history.
**Personas:** zoom_out, design_critic, implementation_readiness. **Mode:** REVIEW.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-4ac6b632` @ `54344fc` (branch `t3/stream-d-gates`).
**Files read:** `docs/ENGINEERING.md`, the design, `factory/extension_compare.py`, `factory/extensions.py`, `factory/gate_pipeline.py`, `factory/gate_state.py`, `factory/run.py` (`write_and_attack`, `_gate_pipeline`, `run_gates`, `validate_and_repair`, `main`, `g1`–`g17`), `factory/gate_attempt.py`, `factory/diagnosis_dispatch.py`, `tests/factory/test_stream_d_execution.py`, and `docs/designs/stream-d.md` (the item 7 sections and checklist).

## Verdict: **BLOCK**

The design names the right seam: replace the `extension_comparison_pending` stop at `run.py:3346-3347`. But it does not choose several things the implementer must have before writing code. Some of its requirements also contradict the API it says it reuses. One section (isolated evaluators for version drift) states openly that it is undecided, and the implementation-readiness standard does not allow that. The simplifications below would remove most of the blockers by cutting scope, without adding new mechanism.

---

## Blockers

### B1. "Reuse failures and stochastic gates on replay" contradicts `snapshot()`'s reuse rule
- **Persona:** design_critic / implementation_readiness
- **Scope:** design lines 25-36. `extension_compare.py:185-188` and `:169-229`.
- **Finding:** The design says to use `extension_compare.snapshot` as the single receipt producer. It also says to persist after every stage, so a restart reuses passes **and** scientific failures, "including normally nonreusable stochastic gates". `snapshot()` cannot do either:
  - It reuses a previous row only when `status == 'pass'` and `stage in gate_state.REUSABLE`, which is G4/5/6/8/9/13/14/15/16.
  - It returns one complete snapshot at the very end and has no per-stage persistence point.

  So a crash after G10 (stochastic, not reusable) would roll G10 again on resume, which the design itself forbids. Hitting the stated requirement means changing `snapshot()`, but the design says nothing about how.
- **Required decision:** pick exactly one durable per-stage record and its reuse rule. Workable options:
  - **(a)** Give `snapshot()` an optional `persist(partial)` callback, called after each terminal stage. Also give it a `reuse_terminal=True` mode that reuses any `_load`-valid pass **or** fail row whose version vector and case digest are identical. `compare()` keeps today's policy.
  - **(b)** Simpler, and preferred: see S2. Keep `snapshot()` unchanged. The package's own evaluator returns a recorded per-stage result on replay.

  Either way, state the crash window between "receipt written" and "row persisted", and say why it cannot lead to a second roll.

### B2. Support evidence per gate is undefined, and many gates leave none under `c.work`
- **Persona:** implementation_readiness
- **Scope:** design lines 29-31. `extension_compare._save` (`:144`, `:147-148`). `gate_state.inventory/save` (`:225-256`).
- **Finding:** `_save` rejects an empty `paths` list as an incomplete execution, so the stage becomes `pending` and `complete()` can then never accept the outcome. `_path(w.work, …)` also requires every path to sit under `w.work`. The design's "gate detail and gate-state referenced evidence" does not work:
  - Only G5, G8 and G15 (and fairness/G16) write `gate-details/<G>.json`.
  - Gate-state evidence of kind `bench` lives in `BENCH/results`, which is outside `c.work`.
  - Non-reusable gates (G1, G2, G3, G7, G10, G11, G17) have no gate-state record at all.

  As written, several gates would always come out pending and the package could never complete.
- **Required decision:** a per-gate rule for producing support paths. A workable rule:
  1. Take the before/after `gate_state.inventory` diff that `gate_state.save` already computes.
  2. Copy changed `bench`-kind files into `c.work/bench-results/<rel>` first. `run_artifacts` already uses that layout at line 62, and `gate_state.load` already accepts it at line 284.
  3. Add `gate-details/<G>.json` when it exists.

  Also state explicitly what happens to a gate whose diff is empty, for example a G2 rejection with no artifact: either that gate always writes a detail file, or it is pending by design. Then add a test that runs over every stage in `extensions.stages()`.

### B3. Version-drift evaluation is explicitly left undecided
- **Persona:** implementation_readiness (zero-decision rule) / design_critic
- **Scope:** design lines 59-66, 84-86. `extension_compare.py:3-5`. `stream-d.md` §item 7: "item-7 process adapter must materialize a separate results/VM execution layout".
- **Finding:** The design says "Exact adapter/layout work must be resolved in design review before implementation." That violates the zero-decision rule. It is also not cheap:
  - Gates hard-wire the module globals `BENCH` (`BENCH/results` in g1, g4, g6, g10, g11 and `run.py:1888-1924`), `COMPOSE` (one medusa compose project with fixed postgres/redis), the `PILOT_HOME` users, `SEALED` progress publication, and factory slots.
  - `_gate_pipeline()` resolves evaluators with `globals()[gate.lower()](c)` against the live `c`.

  An isolated layout therefore means either parameterising roughly 16 gate functions plus pipeline publication, or a second VM. Neither is designed. The test line "changed versions rerun only affected stages in isolated layouts" tests a mechanism that does not exist.
- **Required decision:** take S1 below and delete this scope from the increment. Otherwise the design needs a concrete layout: which roots get rebound (results dir, compose project name, pilot users, slot range, progress path), how, and which gate code changes.

### B4. Card/seal contract on all-pass is unspecified
- **Persona:** design_critic
- **Scope:** design lines 47-49. `run.py:3346-3354` (main), `:3383-3391` (seal in `finally`), `gate_pipeline.run` (`:191-199`), `validate_and_repair` (`:3001-3011`).
- **Finding:** "Publishes the card's stress/gate results from retained validated receipts before returning to ordinary seal" adds a second writer for `c.card['gates']`, `gate_results`, `gate_minutes` and `failed_gate`. It also skips what the ordinary route does around `GatePipeline.run`:
  - `mark_gates` (gate continuation marker, which `authenticate_gates` checks on resume);
  - the `after_gate` checkpoint plus `early_probe` after G5;
  - `stop_infrastructure`;
  - G10 overlap/cancel.

  Seal also checks the G16 calibration identity (`gate_state.py:216`) and needs whatever per-gate state the ordinary loop leaves behind (for example `c.votes`, `c.strategies`).

  The design does not list which of these the package calls, which it skips, and why seal stays valid. A new card publisher next to `GatePipeline.run` is the kind of second path that section 4 ("One launch path", "Delete before adding") warns against.
- **Required decision:** either run the traversal through `run_gates(c)` (see S2), or list every side effect of `GatePipeline.run` and `mark_gates` and say for each one whether the package reproduces it or drops it. Add a test that seals a package all-pass card.

### B5. The scientific-failure stop label and its diagnosis interaction are not named
- **Persona:** implementation_readiness
- **Scope:** design lines 49-50. `diagnosis_dispatch.STOPS` (`:30`). `finalize_accounting` → `diagnosis.record_exhaustion(new_exhaustion=c.exhaustion_occurred)` (`run.py`).
- **Finding:** "A scientific failure checkpoints with a stable exhausted label" does not say:
  - the `terminal_stop` string;
  - whether `c.exhaustion_occurred` is set;
  - whether `record_exhaustion` therefore queues a **new** exhaustion/diagnosis now.

  The last point matters: with diagnosis disabled it might only park, but it changes `diagnosis_state` and how the next increment replays it. The same gap covers "outcome-before-public-card replay": the design does not give the label a replayed completed outcome resumes with.
- **Required decision:**
  - Name the label.
  - Say whether `exhaustion_occurred` is set.
  - Name the exact `diagnosis_state` transition, or state that there is none.
  - Add a test asserting the card and `diagnosis_state` after a package fail, and again after a replay of that fail.

---

## Major

### M1. Three overlapping journals
- **Persona:** zoom_out
- **Scope:** design lines 32-39.
- **Finding:** The design has a package journal ("binds extension id, writer operation, round, case digest, source generation"), per-stage package snapshots, and "existing operation journals" (`infra-attempts.json`). The binding fields duplicate what `extensions.read()` already authenticates on the active row: `writer_operation_id`, `round`, `extension_id`, `entry.source_generation`. `_binding`/`_case` in the receipts already bind the case digest. Collapse to one per-stage record (S2). Its only extra key should be the pinned version vector.

### M2. `snapshot()` change detection versus `freshness.jsonl`
- **Persona:** design_critic
- **Scope:** `extension_compare.py:216-217` (`_case` uses `extensions.tree`, which **includes** `freshness.jsonl`) versus `run.case_hash` (`:886`, which **excludes** it). Also g2 → `ensure_freshness`, and model prompts that append `<case_dir>/freshness.jsonl` (`run.py:654`).
- **Finding:** If any gate's model work appends to `case/freshness.jsonl`, `snapshot()` raises `_Changed`, a bare `RuntimeError` that main turns into `runner_error`. That is a pit stop and not a scientific result. Confirm that no stage writes under `c.case`, or define the behaviour. A test running real g2 freshness under the adapter would show it.

### M3. Early-gate reuse is unstated
- **Scope:** `gate_pipeline.run.invoke` (`:135-137`) versus `check`.
- **Finding:** `write_and_attack` already runs G15/G3/G4/G5 as early checks in the extension round. A per-stage `check()` adapter ignores `c.early` and reruns them, which costs about 20 minutes plus G15 strategy model calls. Say whether `c.early` reuse applies when `case_hash` is unchanged. It does apply automatically if the traversal goes through `run_gates` (S2).

### M4. Entry capture "exposed for the later admission route" is speculative
- **Persona:** zoom_out
- **Scope:** design lines 53-58.
- **Finding:** This increment does not admit, so building and testing an entry-capture adapter now is YAGNI. Move it to the "All diagnosis outcomes" increment, which owns admission. The "existing admitted entries must contain verifiable receipts" check is the only part that belongs here, and only if the package compares (see S1, which removes that too).

### M5. Heilmeier gaps
- **Persona:** design_critic
- **Scope:** whole document.
- **Finding:**
  - **Objectives** are written in project jargon ("durable scientific outcome", "comparison pending", "captured vector"). A new reader cannot state the goal in one plain sentence. Suggested: "After an extension's writer and stress round, run the normal gates once, save each result so a crash never re-rolls it, record the extension's outcome, and seal the case if everything passed."
  - **Cost and timeline:** "Offline inference cost is zero" covers tests only. The production cost of one package (stress plus G10/G16/G17) is a known open item (`stream-d.md:644`, `:890`). Say this increment adds no new spend authority and cite that.
  - **Risk:** no risk/payoff paragraph.
  - **Exams:** the mid-term exam is reasonable; there is no final exam beyond "full suite".

### M6. Tests rely on authored gate outputs for gates whose evidence shape is the risk
- **Persona:** design_critic / ENGINEERING §4 "Real artifacts"
- **Scope:** design lines 78-88. `test_stream_d_execution.py:75-79`, which patches `g1`, `early_checks`, `loop_freshness` and `validate_and_repair`.
- **Finding:** B2 means the risky part is what files real gates leave behind. Authored `(ok, info)` returns with no on-disk artifacts cannot prove support-path collection. Require at least one test per evidence class that goes through real `GatePipeline.check` and `gate_state.save` over saved practice artifacts:
  - a bench-results gate (G4 or G6, as in the existing gate-state tests);
  - a gate-details gate (G5 or G8);
  - an artifact-less gate (G2 or G1).

---

## Nits

- **N1.** Lines 41-42: "Finish the original-version outcome first only if versions remain the captured vector; otherwise enter comparison pending." This contradicts lines 44-46 (complete the outcome after traversal). Outcome completion should not depend on drift. Only comparison should.
- **N2.** "G12 remains publication, not a comparison stage." `extensions.stages()` already excludes G12, so this needs no work. Say so instead of restating it as a requirement.
- **N3.** Murphy: "Supports rows 9 and 13; closes none" is fine. Name any `new-<topic>-<n>` row if B5's label is a new stop kind.

---

## Specific workable simplifications

### S1 (removes B3, M4 and most of the test list): drop comparison from this increment
- Nothing in this increment consumes a comparison result. `propose()` (`extensions.py:397-407`) already does `comparison_pair` plus `progress` on the current versions when the next admission happens, and admission belongs to the "All diagnosis outcomes" increment.
- So this increment should only:
  1. finish stress;
  2. do one gate traversal;
  3. call `extensions.complete(c, outcome)`;
  4. seal on all-pass, or checkpoint with the B5 label on fail.
- Version drift then needs no evaluator. Drift between entry and outcome surfaces later, at admission time, as the `extension_comparison_pending` refusal `propose()` already raises.
- The isolated-layout design becomes its own increment, or an item 8 prerequisite, with a real layout spec. The design already allows "comparison stays pending if no safe evaluator", so this is the degenerate case of its own fallback.

### S2 (removes B1, B4, M1 and M3): traverse with the ordinary pipeline and build the snapshot afterwards
1. Call `run_gates(c)` (the ordinary `GatePipeline.run`) with one change: inject an `evaluate` wrapper through the existing `GatePipeline.evaluate` field. The wrapper:
   - on first execution, runs `globals()[gate.lower()](c)`, computes support as in B2, and atomically writes `extension-package/<extension_id>/<gate>.json` = `{versions, case_sha256, ok, info, support paths}` **before** returning;
   - on replay, if that record exists and its versions and case digest match, returns the recorded `(ok, info)` without executing.

   This keeps G10 overlap, `after_gate` checkpoints, `c.early` reuse, `stop_infrastructure` and card publication. There is no second publisher and no `validate_and_repair` (no repair loop).
2. Then call `extension_compare.snapshot(live_workspace, source_generation, evaluate=read_record)`:
   - `read_record` returns the stored triple;
   - the stress stage reads the validated terminal stress report;
   - `snapshot()` stays unchanged and remains the single receipt producer.
3. Then call `extensions.complete`.

The only run.py changes are:
- `_gate_pipeline(evaluate=...)` takes an optional evaluator;
- the seam at line 3346 becomes `package.run(c)` and then falls through to the ordinary `finally` seal when `c.card['failed_gate']` is unset.

Delete the per-stage snapshot persistence and the separate package journal binding.

### S3: one test file
Extend `tests/factory/test_stream_d_execution.py`. Do not add a new module. Change `terminal_replays('extension_comparison_pending')` into package-completion assertions, and add:
- kill after gate K, then replay: zero re-executions of gates up to K, including G10;
- a G10 fail record reused on replay;
- an all-pass that seals;
- a fail that gives the B5 label;
- a tampered `<gate>.json` that refuses.

Use real `GatePipeline` evidence per M6.

---

## Summary for the elephant
- **Blocking:** B1 (reuse contradiction), B2 (support evidence), B3 (undecided isolated layout), B4 (card/seal contract), B5 (fail label and diagnosis interaction).
- Taking S1 and S2 removes B1, B3 and B4 by deletion. B2 and B5 still need one paragraph and one test each.
- Re-review after revision with a fresh goldfish.

## Elephant disposition

All blockers accepted. Revised design selects ordinary pipeline with an around-invoke
hook (covers early/cache bypasses), serial evidence collection, one atomic record,
explicit proof/state restoration and extension_incomplete diagnosis semantics.
S1 is used only to sequence implementation slices: current-version comparison is
still required within package increment 2 and this task, so the checklist stays open.
Fresh design review requested; no implementation has started.
