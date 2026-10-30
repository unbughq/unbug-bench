# Claude standard/global tariff validation

The implementation uses the passed design in router.md and design review 3.
No live model calls were made. Completed CLI total_cost_usd remains authoritative.

Focused checks (2026-10-30):

- test_model_call_maxima.py: 21 tests passed.
- test_budget.py: 39 tests passed, one existing skip.
- test_stream_d_runtime.py: 21 tests passed. The interrupted writer estimate
  assertion changes from .1232 to .056 under the shared list tariff.
- test_case_budget.py: 33 tests passed with BENCH set to the worktree, as
  tests/run.py sets it. The first standalone invocation omitted BENCH and
  failed two subprocess imports (processes); that was an invocation-context
  failure, and no source was changed to suppress it.
- router-claude-tariff-mutations.json records the exact expression changed
  back to 2.2x. Both real writer subtests fail independently at next-request
  admission; token_prices.py is restored to the recorded SHA-256.

The writer proof is conditional: saved aggregate counters must bound validated
HTTP usage, and unrepresented unknown attempts must not exceed three for
873d7f or two for e15450. There is no complete historical request trace.
The regression asserts those exact tolerances and rejects one additional
unknown attempt. The partial-accounting test copies actual pinned-CLI assistant
mode shapes with real writer counters; its envelopes are transport tests.

Murphy new-router-maxima-1 remains open until the diff goldfish accepts the
implemented conditional proof. Full-suite evidence will be recorded separately
with its tested SHA and terminal result; focused tests do not imply a full pass.
