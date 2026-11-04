# Goldfish review: gate-window design 1 (verbatim)

Reviewer: fresh general-purpose subagent (Claude opus), personas zoom_out, design_critic, implementation_readiness; Mode: REVIEW; standards heilmeier + implementation-readiness. Reviewed commit 9ffc6f4.

---

# Goldfish review: `docs/designs/gate-window.md` at 9ffc6f4

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard.md and implementation-readiness-standard.md.

## Verdict: BLOCKING (4 blocking findings, 5 nits)

The core mechanism holds. The `GatePipeline.window` context now wraps the whole `gate_attempt.execute` retry loop (`factory/gate_pipeline.py:89`, `:158`). That makes a retry in an expired window fail at the first child spawn. `processes.deadline` takes `min(end, previous)` (`bin/processes.py:198-201`), so nested windows only shrink.

I checked how expiry is classified, and it is never a verdict:
- `TimeoutExpired` is an `Exception`, not the `BudgetError` interruption. It spends the allowance (`bin/run_validity.py:95-101`) and becomes `stop_infrastructure` / `invalid-infra`.
- In silent windows, `processes.shell` raising `TimeoutError` becomes errored samples (`bin/silent_window.py:73`). Those count as unknown seconds, so `valid=False` and `error_runs=1` (`bin/exposure.py:47,79`). `require_valid` then raises `InvalidInfra`.

The G14 cache key really is exact. It covers the case tree, `STAGE_DEPENDENCIES["G14"]`, the runner closure, slot, environment, scenario and guard trees, report, runs, seed, label and workers. Run counts, guards and allowances are unchanged. `tests/factory/test_gate_window.py` (3 tests) and `tests/bench/test_strategy.py` (14 tests) both pass locally.

The blocking findings are about what the design claims, and about one G13/G14/G15 entry point it misses.

### 1. [blocking] "Byte-identical identity so existing receipts stay valid" is false (design line 28-29)

`strategy_binding` builds the same identity dict as before. But one of its values, `gate_state.inputs(c, gate, BENCH)["runner"]`, comes from `runner_inputs(gate)` (`factory/gate_state.py:90-91, 162`). That function hashes the gate function's source plus every same-module name it reaches. This commit changes `strategy_run` (`factory/run.py:1946`) and adds `strategy_binding` (`factory/run.py:1907`).

I compared `gate_state.source_inputs('g13')` against the HEAD~1 `run.py`:
- `strategy_run`: digest differs.
- `strategy_binding`: new key.
- `g15` differs the same way.

So every existing G13/G15 strategy receipt, every checkpoint cache, and every G13/G14/G15 gate-cache entry is invalidated on rollout. Every in-flight case re-runs all three gates once. That is correct conservative behaviour, but the design claims the opposite and omits the rollout cost. Fix the sentence and state the one-time re-run cost.

### 2. [blocking] G13/G15 get no checkpoint reuse on any v2 case, so the problem statement's premise is wrong (design line 15-17, 27-28)

`simulate` turns `execute_cached` off whenever any step is `unannounced` (`bin/strategy:168-169`). `factory/case_contract.py:82-90` requires unannounced ingredients on every v2 case. `cases/medusa-oversell-v2`, which the test uses, has step deliveries `[announced, announced, pending, pending, announced, announced, unannounced]`.

Three consequences:
- **G13/G15 still redo every unit on restart in production.** Row 42's remedy, "Resume completed checkpoint units", is not delivered for G13/G15. The design does not list this as a remaining gap.
- **G14 now caches where the existing path deliberately does not.** "Same exact binding as G13/G15" makes G14 the only mechanical checkpoint cache actually used on v2 cases. The design gives no reason why caching is safe for G14 when `simulate` refuses it in the same situation. G14 looks safe to me: its report is fixed at `{'pending_decision': 'approve'}`, history is passed explicitly, and `silent_checkpoint` is never cached. The design must still say so, because the `simulate` gate has no recorded rationale (`git log -L` shows only the initial commit).
- **The design must also state either that G13/G15 reuse stays off, or why.**

### 3. [blocking] The extension comparison path runs G13/G14/G15 with no window at all (not mentioned in the design)

The comparison child is forked by `factory/extension_evaluator.py:409-412`. It calls `getattr(r, stage.lower())(c)` directly (`factory/extension_evaluator.py:313`) and bypasses `GatePipeline.check` and `window`.

The parent wraps each attempt in `gate_attempt.execute(..., attempts=2)` (`:586-591`) and is not inside any `processes.deadline`. Its `receive()` loop (`:418-425`) only polls for child death or cancellation.

The result on this path:
- Each `bin/strategy checkpoint` unit gets its own `timeout=14400` (`bin/strategy:94`).
- A whole G14 run is bounded only by number of units x 4h.
- Each retry gets fresh time.

That is the exact failure row 42 describes. Design line 35 ("Extension re-runs call `run_gates` again and get their own window") is true only for the `extension_package` path (`factory/extension_package.py:598, 676`). The design must list every G13/G14/G15 entry point and either bound this one or list it as an open part of row 42.

### 4. [blocking] Resume after an expired window never reaches the G14 cache; the test hides this (design line 15-17, 45-48; test lines 101-113)

The retry journal key is the operation identity plus `runtime_revision()` (`bin/run_validity.py:66`). It persists in `work/infra-attempts.json`. After the window expires, the row is left at `invalid_attempts=2`. The next `run_gates` on resume then raises `InfrastructureExhausted` in `start()` (`bin/run_validity.py:77-80`) before it invokes anything.

The cache therefore only pays off in two cases:
- after a worker crash, where a stale `running` row costs one attempt and the gate continues in a new window;
- after a code or identity change, i.e. a factory-bug resume.

The G14 test calls `run.g14` inside a bare `processes.deadline` and skips `GatePipeline` and the journal entirely. So "three expired windows never redo a completed unit" demonstrates a path production does not take. (`pipeline = run._gate_pipeline()` at test line 100 is unused.)

The design must also state the consequence in Limits. A case whose honest G14/G13/G15 workload exceeds `agent_timeout` can never complete without a code change. Every attempt ends `infrastructure_exhausted`, which is a pit stop under ENGINEERING section 3. Classifying it as infrastructure is correct per row 42, but it must be stated.

### 5. [nit] The test replaces more than `bin/checkpoint` (design line 46-47)

`test_gate_window.py:86-97` replaces `module.checkpoint`, which is the whole `bin/strategy` wrapper including `read_completed`. The stub writes its own `checkpoint.json` and `_evidence_path`.

So the real evidence-path layout and the `stored == summary` equality check (`bin/strategy_resume.py:73-78`) are not exercised for G14. Under ENGINEERING section 4, "a fixture generated by the code under test proves nothing". This is acceptable only because row 42 is not closed. The design text should say what is actually replaced.

Separately, the comment at test line 107 ("finishes the rest") is wrong: the third window also raises `TimeoutExpired`.

### 6. [nit] The `early_checks` window is untested

The design names `early_checks` (line 22), and G15 runs there (`gate_pipeline.py:86-89`). Test (a) only drives `pipeline.run`.

### 7. [nit] "Deletes" deletes nothing (design line 37-39)

`check` still opens the same window on every attempt (`gate_pipeline.py:60`). The design keeps it for "direct callers", but the only direct caller, `checked_gate` (`factory/run.py:945`), is used only by tests, and only for G16 (`tests/factory/test_calibration_delivery.py:202-211`).

The inner window is now always dominated by the outer one. Remove it so `window()` has one owner, or remove the Deletes claim.

### 8. [nit] The deadline is enforced only at subprocess boundaries

In-process work keeps running past expiry until the next spawn or the in-flight child's timeout. Examples are silent-window `asyncio.sleep` (`bin/silent_window.py:65, 83`) and tree hashing. This matches "fails at once at the first child spawn", but it is not truly "gate-wide". One line in Limits would cover it.

### 9. [nit] Heilmeier gaps

The design has no stated cost: the rollout re-run from finding 1, and growth of the `strategy-g14-checkpoints` cache. It also has no risk section beyond Limits.

Implementation readiness is otherwise fine: the change is small, the files are named, and no decision is left to the implementer.

## Are the Murphy-row claims honest?

- **Row 42 "not closed": honest, and understated.** Besides the missing live bench run, three gaps remain:
  - G13/G15 checkpoint resume is off for all v2 cases (finding 2).
  - The extension comparison path has no gate-wide deadline (finding 3).
  - Resume after expiry is blocked by the retry journal (finding 4).

  The design should list these as row 42's remaining scope, rather than implying that only live proof is missing.
- **Row 35 "not claimed": honest.** The G14 receipts live in `c.work`, and results live under the worker's `BENCH/results`. Nothing here creates an off-worker boundary for a long mechanical gate.

---

## Disposition (elephant, commit 71b2e84)

- 1 fixed: `strategy_run` restored byte-for-byte; G14 uses a separate `g14_binding`. Verified `gate_state.source_inputs` g13/g15 digests identical to baseline dd81ff8; only g14 changes. Cost stated in the design.
- 2 fixed in design: G13/G15 reuse stays off on v2 (unchanged), stated as a remaining gap; why G14 caching is safe stated.
- 3 fixed: `extension_evaluator.__call__` wraps `gate_attempt.execute` in `window()`; the fork inherits the context deadline. No dedicated test (stated in Limits).
- 4 accepted as a limit, written in the design: no allowance reset on retry is a task requirement.
- 5-9 fixed (comment, unused var, early_checks test, Deletes wording, Limits, Cost).
