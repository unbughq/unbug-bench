# Startup smoke: a no-model job on the real worker, ahead of every practice or pilot job

## Problem

Offline tests can't reproduce the real Boat worker. The image is a Boat snapshot
(`bin/boat-bake`), and its Docker state is not local Docker's
(`docs/reviews/preflight-design-1.md` B1). Stop 10 of the 2026-11-03 practice run
was a Docker name clash at `factory/run.py:3387`, three minutes after worker
start. It surfaced only after deployment, admission, a worker, a 60-minute
disconnect window and a decrypt-and-diagnose cycle. Every later
real-environment surprise will cost the same, unless something exercises the
real machine cheaply and early.

The repo already has `tools/run-gate-smoke.sh` and `bin/gate-smoke`, a no-model
smoke on one new Boat worker. But it creates its worker through its own path
(`boat-launch-guards.sh` directly), not through `batch_holder.dispatch`. So it
skips the parts that broke (router delivery, dispatch, cleanup and collection),
and it's a second launch path, which `docs/ENGINEERING.md` section 4 forbids.

## Change

Add a **`smoke` job to the practice manifest**, ahead of the `practice` job. It
is the same job with `--dry-run` appended. `run.py --dry-run` already means "no
model calls; practice case as fixture; throwaway key" (`factory/run.py:3213`).
It goes through the one launch path:

> admission → `batch_holder.dispatch` → `launch.sh` → worker → `run.py` startup
> (Compose, the stop-10 line) → G1/G3/G4/G5… on the fixture → seal → collection →
> publication → deletion

The operator dispatches `smoke` first. `practice` is dispatched only after
`smoke` passes.

**Smoke pass:**
- the card is collected and published;
- `terminal_stop` is not `runner_error`;
- G1 and G3 passed, which proves startup, Docker, setup and seeding on the real image;
- the worker deletion is verified.

Later gates may not finish inside the 1800 s run cap. That is acceptable, and
it is recorded.

Manifest changes, as a new batch `b-plumbing-practice-3`, because a pinned
manifest is exact-matched and -2 has retained operations:
- `jobs.smoke`: the practice args plus `--dry-run`; case
  `case-b-plumbing-practice-3-smoke`; `requested_total_usd` and
  `incremental_usd` both `0.000000000`.
- `practice.EXPECTED` and `practice.BATCH` move to -3. Nothing else changes.

**Accounting.** Collection requires `card['continuation_budget']` to be a dict
(`factory/batch_accounting.py:95-114`). The 11-03 crash card had none and was
refused. A dry run makes no model admission, so it may never write a ledger.
The fix: when `run.py` starts a batch job with `--dry-run`, it writes the same
empty ledger `budget.py` creates by default. Collection then accounts it as $0,
spent and settled. Only dry-run batch jobs get this. Non-dry jobs keep today's
refusal of a missing ledger, which `docs/designs/practice-startup-error.md`
requires.

**Sealing.** A dry run seals to a throwaway key (`run.py:3380`), and
`collect.sh` already collects `*.throwaway-key.txt`. Collection and publication
must accept this card for the smoke job only. They must still refuse a
throwaway-key card for any non-dry job.

**Infra cost.** The observed worker debit was $0.0019 for about 3 minutes, so a
30-minute smoke is roughly $0.02. The practice infrastructure ceiling stays
$5, shared.

## Deletes

- `tools/run-gate-smoke.sh` and `bin/gate-smoke`, the separate-path smoke. The
  smoke job replaces them. Their tests are removed too, unless another caller
  exists (to be checked).
- In practice-run.md, the step-4 to step-6 sequence for the first worker. It
  becomes the smoke job, then the practice job.

## Tests (real artifacts)

- The retained -2 manifest and policy, upgraded to -3. Admission accepts
  `smoke`, `smoke` dispatch builds argv with `--dry-run`, and the practice args
  are unchanged.
- The real `run.py` startup under `--dry-run` against local Docker reaches G1,
  with the stop-10 fix from `t3/batch-service-control-vm` merged. This proves the
  dry-run path is intact locally. It doesn't prove the Boat image; only the live
  smoke does.
- A dry-run batch card with the empty ledger passes `batch_accounting` at $0.
  A non-dry card with no ledger is still refused. That uses the real 11-03 card
  shape from `tests/factory/fixtures/practice-startup-conflict-20261103.json`.
- Collection accepts the smoke's throwaway-key card and refuses one from a
  non-dry job.

## Murphy rows

- `new-smoke-1`: Real-worker environment faults surface only during paid
  practice or pilot runs. It closes when the first live smoke passes, or when
  it catches a fault before the practice job starts.

## Depends on, and overlap

- It depends on `t3/batch-service-control-vm` (the stop-10 fix), and on
  preflight merging first, which uses the same practice files.
- `practice.py` and the manifest are B's area, so the stream coordinator
  (thread 7d333d37) must agree. `practice_cleanup.py` and `dispatch` are not
  changed.

## Cost and timeline

Implementation: about half a day offline at $0. Each live smoke costs about
$0.02. It runs automatically before every practice and pilot attempt, with no
founder pause: no disconnect window, no model spend.

## Founder decision

On 2026-11-03 the founder chose to start item 7, the real-worker test ("Start
with 7"). That is a decision to build it. Each live smoke spends about $0.02 of
Boat credit inside the existing $5 cap. The first live run is still confirmed
with the founder at launch, as every live run is.
