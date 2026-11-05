# Durable execution: handoff

**Snapshot 2026-11-05.** Written so a fresh session can resume without the original
conversation. Every branch below is pushed to `origin`. Draft PR:
https://github.com/unbughq/unbug-bench/pull/12 (`durable-execution` → `factory-simplify`).
Nothing has been merged into `factory-simplify`.

## Where things stand

The design (`docs/designs/durable-execution.md`) passed design review 5. The frozen
contract is `factory/durable/contract.py` (v5). Wave 1 has seven packages, briefed in
`docs/designs/durable-execution-wave1.md`. Each package has a branch `de/<id>` cut from
`durable-execution`.

| Branch | Package | Head | State | Next action |
|---|---|---|---|---|
| `de/wp4` | Failure classification | `eb4707c` | **Merged** (diff reviews 1–3, PASS on 3) | none |
| `de/wp3` | Sealer and artifact store | `9bd0836` | **Merged**, with follow-up (diff reviews 1–2, both PASS) | none |
| `de/wp1` | Engine core, executor, policy, report | `7d09dae` | Built, not yet reviewed. Agent may still have been finishing its full-suite run. | Diff review, then merge |
| `de/wp2` | Worker pool, release store, channel | `18b2d2c` | Built, not yet reviewed. Agent was finishing its full-suite run. | Diff review, then merge |
| `de/wp5a` | Worker-side step runner, `run.py` hooks | `63d01f1` | Built, not yet reviewed | Check the two requirements below, diff review, then merge |
| `de/wp6-wp7` | Ledger, key service | `4cabb42` | Built, not yet reviewed. Agent was finishing its full-suite run. | Diff review, then merge |

## Requirements sent to agents mid-run

These came out of the WP4 diff reviews. They are not in the wave-1 brief, so check them
during each diff review.

**WP1.** Commits `524625d`, `ab3a431` and `7d09dae` say all four are settled; verify
them in review:
1. Operator pauses (`infra:paused` and similar, from WP4) do not use the infra-retry
   allowance and are never scored.
2. The executor passes WP4's optional `reset_at` to `classify` when a provider reset
   time is known.
3. PROVIDER_LIMIT attempts that spend nothing are capped per step, at 96 per
   `ab3a431`, then give up. This is because `credential_expiring` is also raised for a
   missing local secret.
4. Two edge cases:
   - A batch-deadline stop (`infra:deadline` from `retired_batch_bound` or
     `provider_wait_deadline`) never uses a running case's infra allowance or pushes
     it to DIAGNOSE. The contract's `deadline_epoch` only stops new cases and
     extensions.
   - `budget.py:165` raises `money_wait` before any spend. Under a BATCH-limited grant
     it must wait, not give up.

**WP5a.** These were sent after its first implementation commit, so verify they are in
`63d01f1` or later:
1. Under the engine, the runner's per-call timeout comes only from
   `StepInput.deadline_s`. No batch-deadline check survives in the step path:
   - `budget.py` :145, :834-839, :1220, :1247;
   - `job_authority.py` :47, :74.
2. Under the engine, `money_wait` is emitted only when the attempt's spend plus
   reservations exceeds its grant. JobAuthority and job_config plumbing faults must
   surface as INFRA_ERROR instead. Their sources are:
   - `budget.py` :141, :144, :714;
   - `job_authority.py` :51, :63, :71, :73;
   - `job_config.py` :88, :96, :172;
   - `factory_waste.py` :41, :314.

**WP1/WP2, from WP3's review.** Verify each worker-output Ref with `open_from`, scope from
`scope_for`, before the engine records it.

## How to resume

1. Check out `durable-execution` and read `docs/ENGINEERING.md`, the design, and this
   file.
2. For each unmerged branch, run a **fresh goldfish diff review** of
   `git diff <durable-execution base> de/<id>` against the design, the brief and the
   contract. Use the personas in `tools/egm/agents/` (`zoom_out`,
   `implementation_readiness`), Mode: REVIEW.
3. Save each review verbatim to `docs/reviews/durable-execution-<id>-diff-<n>.md` on the
   package branch, and append a resolution table.
4. Blocking findings go back to the package for fixing, followed by a narrow
   verification review.
5. Merge with `--no-ff` into `durable-execution`, with `Reviewed-by:` trailers listing
   every review file. Follow the WP3 and WP4 merges as examples.
6. After the wave-1 merges, run the full suite on the merged tree:
   `uv run --with numpy --with scipy --with dbos==3.4.0 python -B tests/run.py`
   - **Known failures in a cloud sandbox:** `test_boat_legacy_debit` (when the checkout
     is under `/home/user`), plus six that need Docker: `test_practice_startup`,
     `test_preflight`, `test_recovery_routes`, `test_restore_permissions`,
     `public_qualification/test_finish` and `test_launch_manifest`.
   - **Timing-sensitive under load:** `test_batch_holder` and
     `test_isolation_outer_callers`. Re-run them alone.
7. Then wave 2 (WP10, WP11, WP5b–e, WP8), per the design's work-package table.

## Founder decisions

**Recorded:**
- Freeze new lifecycle work on `factory-simplify` while waves 1–2 run.
- Retire legacy checkpoints instead of migrating them.
- Run wave 1 in batches of 2–3 packages.

**Still open:** decisions 3–7 at the end of the design:
- Postgres on the control VM;
- DBOS over Temporal;
- the integration-branch exception;
- the $50 per-case money and the 24-case limit;
- the overnight stopgap.

## Not exercised anywhere yet

These have not been run against real infrastructure:
- a real Boat VM;
- real R2 and HTTPS;
- Docker and the shop;
- the live practice batch, which is the final exam in WP9.

## Findings worth acting on outside the migration

From WP4 (`docs/reports/durable-execution-wp4-stops.md`):
- 206 of the 210 `opencode_error` stops occurred in cases that gave free OpenCode Zen
  routes (MiniMax, DeepSeek) to the writer, stress or reviewer roles. That is a
  correlation, not a proven cause: those cases also ran far more work.
- Confirming the cause needs the encrypted transcripts.
- Recording a sanitized error type and status code next to `opencode_error` would make
  the next analysis possible from the cards alone.
