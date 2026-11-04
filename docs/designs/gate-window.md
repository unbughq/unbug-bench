# One window per mechanical gate (G13/G14/G15)

## Problem

`GatePipeline.check` wraps G13/G14/G15 in `processes.deadline(agent_timeout)`
(default 4h; `docs/designs/isolation-timeouts.md`). Every child inherits the
remaining time, so one attempt is bounded. But the retry loop sits *outside*
`check` (`gate_attempt.execute`, `attempts=2`), so each retry opens a fresh
window. A gate whose nested scenario/guard checkpoints outrun 4h burns 4h, is
retried, and burns another 4h before `infrastructure_exhausted` — an 8h gate
that delays collection. Reproduced with a controlled clock at
`processes.py` (`tests/factory/test_gate_window.py`, 8 units run in a 4h
window on baseline dd81ff8).

G14 also calls `bin/strategy checkpoint` directly, with none of the completed-
checkpoint reuse that G13/G15 get from `strategy_resume.execute_cached`, so any
retry or restart redoes every completed scenario/guard unit.

## Change

1. `GatePipeline.window(c, gate)`: the existing deadline context, for the three
   mechanical gates only. `run_gate` and `early_checks` wrap the *whole*
   `gate_attempt.execute` in it; `check` keeps its own (nested windows only
   shrink), so direct callers are unchanged. A retry inside an expired window
   fails at once at the first child spawn and spends the existing
   infrastructure allowance; it buys no new time.
2. G14 `run()` goes through `execute_cached` with the same exact binding as
   G13/G15 (`strategy_binding`, extracted from `strategy_run` with a
   byte-identical identity so existing receipts stay valid). Cache key still
   covers scenarios, guard, report, runs, seed, label, workers and the bench.
   Live silent windows are never cached (unchanged).

Expiry stays `infrastructure_exhausted` / `invalid-infra`: never a gate pass,
fail, or writer feedback. Run counts, guards, seeds, and allowances are
unchanged. Extension re-runs call `run_gates` again and get their own window.

## Deletes

The per-attempt window inside the retry loop (moved outward).

## Tests

`tests/factory/test_gate_window.py`: (a) retry shares one window for G13, G14
and G15 (baseline: 8 units, now 4); in-window work passes; (b) real retained
`cases/medusa-oversell-v2` step order through real `run.g14`, real
`execute_cached` and real `processes.run`; only `bin/checkpoint` (docker bench)
is replaced. Three expired windows never redo a completed unit (baseline
redoes them). `tests/bench/test_strategy.py` gains the `work` dir real cards
always have.

## Murphy rows

Row 42: implemented and tested, **not closed** — no live bench run proves it,
so ENGINEERING section 2 closure is not claimed. Row 35: not claimed; this
test shows reuse of completed G14 units inside one runner, not an off-worker
checkpoint boundary.

## Limits

- The window is still `agent_timeout`; the two retries share it, they do not
  shrink it.
- The unit in flight when the window ends is lost (a child is killed).
- Unannounced (live window) units in G14 always re-run.
- A fresh `run_gates` (repair, extension, resume) opens a new window by design.
