# Durable execution: summary and context

*Snapshot 2026-11-05. The resume point for any agent is
[`durable-execution-handoff.md`](durable-execution-handoff.md). The full design is
[`durable-execution.md`](durable-execution.md).*

## The goal

The case factory takes **an app pin, a promise and a case count** and produces
**sealed exam cases**:

```
app pin + promise + case count  ->  factory  ->  sealed cases
```

The founder wants to launch a batch and go to sleep.

## Why it wasn't working

- Cases are long, 30–77 hours each.
- Cases are interrupted constantly: 435 times across 50 real cases, mostly model-tool
  errors and provider limits.
- Restarting a case from scratch after each interruption is too expensive in quota and
  time, so the factory must *carry on* from where it stopped.
- Carrying on is hand-built today:
  - 12 separate launch and recovery paths;
  - state spread across cards, ledgers, checkpoints, holders, R2 and the founder's Mac.
- Most open Murphy rows are two copies of that state disagreeing, or a crash between
  two writes. Each fix added a receipt, and each receipt produced the next row. That
  is why refactoring never converged.

Python versus another language, and object-oriented versus procedural, were never the
real problem. The hand-built state machine was.

## What we decided

**Durable execution:** one workflow per case on the always-on control VM, using
**DBOS**, a Python library on Postgres.

- **Crash recovery.** The engine records each step's result the moment it finishes.
  After any crash, completed steps return their saved results, and only the open step
  reruns. This is proven on the real engine.
- **One recovery path.** A resume and a fresh launch are the same operation. This
  replaces all 12 recovery paths.
- **Disposable workers.** Workers hold no state; losing one loses at most the open
  step.
- **Typed outcomes.** Every step ends in one of six outcomes, and one policy, following
  `ENGINEERING.md` section 3, decides what happens next:
  - infrastructure failures retry and are never scored;
  - provider limits sleep without using any allowance;
  - money or round exhaustion goes to diagnosis, and a replacement case starts at
    once;
  - only a real disagreement between reviewers reaches the founder.
- **Secrecy by design.** The engine records only IDs, keyed hashes and fixed codes,
  never case content.

## How it was done

1. **Branch and contract.** Branch `durable-execution` holds the design and a frozen
   shared contract (`factory/durable/contract.py`) that every work package builds
   against.
2. **Design reviews.** Five rounds of fresh-reviewer design review (the elephant and
   goldfish flow). Blocking findings went **10 → 10 → 4 → 1 → 0**. Every review is saved
   verbatim in `docs/reviews/`.
3. **Work packages.** The work is split into **7 wave-1 packages** with disjoint file
   ownership, run as parallel agents in two batches. Each package gets a diff review
   before it merges.
4. **Founder decisions.**
   - Freeze new lifecycle work on `factory-simplify`: approved.
   - Retire the 43 legacy checkpoints instead of migrating them: approved.

## Where it stands

| Package | Branch | Status |
|---|---|---|
| WP3: encryption and artifact store | `de/wp3` | Reviewed and merged |
| WP4: failure classifier | `de/wp4` | Reviewed and merged |
| WP1: engine core, executor, policy | `de/wp1` | Built and pushed, not yet reviewed |
| WP2: worker pool and channel | `de/wp2` | Built and pushed, not yet reviewed |
| WP5a: worker-side step runner | `de/wp5a` | Built and pushed, not yet reviewed |
| WP6/WP7: ledger and key service | `de/wp6-wp7` | Built and pushed, not yet reviewed |

- **Saved:** everything is pushed. Draft PR
  [unbughq/unbug-bench#12](https://github.com/unbughq/unbug-bench/pull/12) tracks it.
- **Not merged:** nothing has been merged into `factory-simplify`.
- **Not yet run on real infrastructure:** Boat VMs, R2, Docker or a live batch.

## What's next

1. **Finish wave 1.** Review and merge WP1, WP2, WP5a and WP6/WP7. The steps are in the
   handoff note.
2. **Wave 2.** Diagnosis and extensions, admission, and deployment to the control VM.
3. **The final exam.** A live practice batch has to survive a killed worker and a
   control-VM restart with no human. That is what lets the founder sleep.
4. **Delete the old recovery paths,** about 8k lines.

## Open founder decisions

- Postgres on the control VM.
- DBOS over Temporal.
- Using `durable-execution` as the integration branch.
- The $50 per-case money and the 24-case limit.
- Whether an overnight stopgap is still wanted.

## Side finding

206 of the 210 `opencode_error` stops occurred in cases that used free OpenCode Zen
routes for the writer, stress or reviewer roles. This is a **correlation, not a proven
cause**, because those cases also ran far more work. Still, it may be a cheap routing
fix, and the encrypted transcripts can confirm or rule it out.
