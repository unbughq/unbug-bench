# Goldfish design review 4 (Codex rerun): stream D item 3, money cleanup

Reviewer: Codex `gpt-6.1-sol`, high reasoning effort, through T3
`delegate_task`. Fresh context, read-only, a different model family from the
writer (Claude), against bbd75e2. Codex was chosen at the founder's direction,
after the DeepSeek round 4 returned nothing (`stream-d-money-design-4.md`).
Final report below, verbatim.

---

**Verdict: FAIL.** Reviewed the committed design at `bbd75e2`; implementation references below describe the uncommitted drafts. No files changed and no tests run.

**Blockers**

- **B1 — The next-writer admission proof still depends on a synthetic maximum.** `tests/factory/test_stream_d_runtime.py:345–355`; `factory/run.py:386`; `docs/designs/stream-d.md:1973`. In `reviewer_then_writer`, only the reviewer receives its real maximum. The next writer retains the synthetic maximum installed by `setUp`. With the real Claude maximum of $50, the default $50 ordinary limit, and this saved ledger’s positive spending, `pending_call` raises `budget_exhausted`, even after correct gate-bound settlement. The writer-retry subtest uses real Claude maxima, but bypasses this writer-admission check through `model_call`. Thus round 3’s real-maxima correction is incomplete. Specify the intended ordinary-envelope behavior and prove subsequent admission with real maxima; if using a larger authorized ordinary envelope, state that prerequisite explicitly.

**Majors**

- **M1 — Smaller nonfinal receipt replays lack a defined accounting transition.** `factory/budget.py:295–301`; `factory/batch_accounting.py:164–166`. `_settle_leaf` can replace an existing estimate with a smaller gate-bound estimate while leaving the reservation `estimated`. It records a decrease only when final usage becomes known. Concrete scenario: an earlier generation reports a maximum-based estimate; a subsequently supplied nonfinal receipt lowers it. Local admission uses the lower total, but collection can reject the decrease as `unsupported_decrease`. Define whether nonfinal evidence is immutable, whether such replacements must be refused, or how their decreases receive valid provenance. Add a saved-artifact generation-transition test.

  `_gate_bound` also accepts shape-valid forged or stale data: `closed=True`, `forwarded_requests=1`, and zero dollar fields can erase the unbooked estimate. It does not bind the snapshot to the reservation’s route or authenticate its contents. Since receipts and ledger evidence share a trusted work directory, this alone is **not a new security-boundary violation**—an actor able to rewrite both can already falsify accounting. Nevertheless, stale/replayed evidence needs an explicit consistency policy; the current arithmetic accepts it silently.

**Nits**

- **N1 — Contradictory failed-stop instructions remain.** `docs/designs/stream-d.md:2033`. The round-2 response still says a failed stop retains the factory marker, whereas the operative design deletes that exception. Mark the old response superseded so an implementer cannot follow both instructions.

**Verified findings**

The genuine gate snapshot is conservative under the code’s pinned pricing contracts. Reservations precede forwarding; `close` retains unfinished requests; late `finish` cannot refund retained holds. Claude reserves at the highest input/cache rate, and OpenRouter uses uncached input pricing and the full configured output hold. `enforce` snapshots after `_wall_access` closes the gate. Pre-close snapshots, zero-forward snapshots, and absent snapshots retain the reservation maximum. Production `_invoke` refuses unsupported nongated routes before launching.

The failed-stop marker exception is deleted. Route receipts are inherited, and outcomes are recorded before `complete_invocation`. The revised settlement test runs real `_invoke`, `run_budgeted`, and `Allowance` arithmetic, although it substitutes the enforcement context and authors request activity.

Row 8 has credible saved-case/ledger coverage for the scoped batch behavior. Row 21 demonstrates removal of unknown-total poisoning and real-maxima inline retry, but B1 prevents accepting its claimed next-writer admission proof. The explicitly accepted runner-SIGKILL start-evidence gap remains.

**Files read**

- `docs/ENGINEERING.md`, `docs/murphy-register.md` (rows 8 and 21), `docs/designs/stream-d.md`, and money-design reviews 1, 2, and 3-Claude.
- `tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`; Heilmeier, implementation-readiness, and zoom-out standards.
- `factory/{model_call_gate,budget,model_runtime,run,diagnosis,batch_holder,batch_accounting,token_prices,gate_state,batch}.py`.
- `tests/factory/{test_stream_d_runtime,test_stream_d_projection,test_model_call_maxima}.py`; `tests/fixtures/factory/stream-d/job-money.json`.

---

## Elephant response

Every finding is accepted and fixed. Nothing was rejected.

- **B1, fixed.** The admission subtest runs both routes at their real
  maxima: the DeepSeek OpenRouter gate maximum and Claude's $50. The writer
  `pending_call` is admitted under an ordinary limit of 100. That value is
  authored configuration, and the design now states the prerequisite: under
  the default $50 ordinary limit, a $50 Claude writer round after any spend
  is refused whether usage is known or not. That is the existing rollout
  prerequisite in "Exhaustion routing and effective money source" (the
  E/A route-maximum report against the ordinary limit), not part of row 21.
  It is flagged to the founder in the stream report.
- **M1, fixed.** `_settle_leaf` never lowers an existing estimate from
  evidence without final usage. Only a final receipt can lower it, and that
  path records `reconciled_decreases`, the provenance B's collection
  accepts. The test replays a stale snapshot with $0 bounds and asserts the
  ledger stays byte-identical. Without the new guard, that assertion fails;
  this was checked in a throwaway worktree. A forged first snapshot shares
  the work directory's trust with the ledger, as the reviewer notes. The
  design now says so.
- **N1, fixed.** The round-2 failed-stop response is marked superseded.

The red checks ran on a throwaway worktree at HEAD with the new test. Both
subtests fail there: `budget_exhausted` (reviewer then writer) and
`money_wait` (writer retry). Both pass on the change.

A fresh design review 5 follows.
