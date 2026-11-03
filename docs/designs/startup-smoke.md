# Startup smoke: a no-model job on the real worker, ahead of the practice job

Revision 3, after `docs/reviews/startup-smoke-design-1.md` and `-2.md`. Round 2 was
the final round. The parent accepted both of its blockers, which are fixed below.

## Problem

Offline tests can't reproduce the real Boat worker. Its image is a Boat
snapshot (`bin/boat-bake`), and its Docker state differs from local Docker
(`docs/reviews/preflight-design-1.md` B1). Stop 10 of the 2026-11-03 practice
run was a Docker name clash at `factory/run.py:3387`, three minutes after the
worker started. It surfaced only after deployment, admission, a worker, a
60-minute disconnect window and a decrypt-and-diagnose cycle. Every later
real-environment fault will cost the same, unless something exercises the real
machine cheaply and early.

`tools/run-gate-smoke.sh` / `bin/gate-smoke` already run a smoke with no model
calls. But they create their worker outside `batch_holder.dispatch`, so they
skip the batch path that broke: router delivery, dispatch, cleanup and
collection.

## Change

A new pinned batch, `b-plumbing-practice-3`, holds two jobs. `smoke` is the
practice job with `--dry-run` appended. `run.py --dry-run` means no model
calls, the practice case as the fixture, and a throwaway key
(`factory/run.py:3213`). The smoke goes through the one launch path:

> admission → `batch_holder.dispatch` → `launch.sh` → worker → `run.py` startup
> and prepare (Compose, the stop-10 line) → G1 → (G3 if time allows) → seal →
> collection → publication → deletion

The operator reserves and dispatches `smoke` first. `max_concurrency: 1`
(`batch_holder.py:242-245`) only stops the two jobs from overlapping. Running
smoke first, and requiring it to pass before practice, are operator steps in
the runbook below.

**Smoke pass:** all of the following hold.
- The card is collected and published.
- `terminal_stop` neither starts with `runner_error` (it can be `runner_error:<Type>`, `run.py:3145`) nor is `money_wait`.
- Startup and prepare completed, and G1 passed.
- Deletion of the worker is verified.

G3's status is recorded but isn't required. There is no measured G3 time on the
Boat image, and the 1800 s run cap may be hit mid-gate. When that happens,
`collect.sh` pauses the run and the card is collected with `terminal_stop=paused`.

### Money (B1)

`batch_money.py:55` and `:72` refuse $0 jobs, `:74` caps the sum,, and `budget.py:716` would stop a
$0 job before G1. So the jobs get these allocations:

| Job | `requested_total_usd` / `incremental_usd` |
|---|---|
| `smoke` | `0.010000000` |
| `practice` | `19.980000000` (was 19.99) |

`money_limit_usd` stays `19.990000000`. This splits the founder-approved total
between the two jobs. It doesn't add money. The smoke makes no model calls, so
its $0.01 is never spent. It only satisfies the job-budget check.

### Accounting

Collection requires `card['continuation_budget']` to be a dict
(`batch_accounting.py:95-114`). In `finalize_accounting` (`run.py:3139`), a dry
run uses the empty default ledger: `jload(c.ledger, EMPTY if c.args.dry_run else
None)`, where `EMPTY` is a fresh dict literal `{'cost': 0, 'calls': 0, 'events': []}`, the
`budget.py:113` default, built per call and not a shared constant. Collection then accounts the smoke at $0, which review 1 traced
through `collection_facts`. Non-dry jobs keep today's refusal of a missing
ledger.

### Sealing (B2)

`batch_service._card` (`:180`) requires `<case>.casekey.age`, but
`run_artifacts.py:109` skips the case key for dry runs. Change that line to
skip only dry runs that have no restore recipient:
`case_key = None if c.args.dry_run and not vm_recipient else r2_upload.case_recipient(...)`.
A batch-mode smoke is then sealed to the throwaway key plus the case key, and
collection and publication need no change. No throwaway-key check is added:
only `--dry-run` creates one (`run.py:3380`).

### Renaming -2 to -3 (B3)

Every hard-coded -2 site moves to -3:
- `factory/practice.py` (`BATCH`, `EXPECTED`);
- `factory/batches/b-plumbing-practice-3.json`, which is new (-2 is kept, because
  its operations are retained);
- `control/unbug-practice-cleanup@.service:9`;
- `factory/practice_preflight.py:19` (`DROPIN`), and `LIVE` at `:22`, whose
  practice ceiling becomes 19.98;
- `tests/factory/test_practice_readiness.py:92-97`, covering the id and the
  practice amount, plus `old['id']` at `:105-106`, which becomes the -2 id.

Deployment then rebuilds the control-VM `policy.json` and the release and pins
bundle for -3 (`manifest()` checks the release's `source-manifest.json`, and the
pins include `practice.conf`). It also reinstalls the cleanup unit and the
holder drop-in. With either one left at -2, cleanup refuses and dispatch would hold
for ever.

## Practice-run steps (replacing steps 3–6)

1. Run `tools/qualify-batch-inputs.py --policy POLICY --home CONTROL_HOME --job smoke`,
   reserve `smoke` once, then start `unbug-practice-cleanup@<smoke-op>.service`
   and verify its readiness binding.
2. Dispatch `smoke`. Wait for collection, publication and verified deletion.
   There is no disconnect window and no fault arm for the smoke.
3. If the smoke passes, run `qualify-batch-inputs.py --job practice`, reserve
   `practice`, start `unbug-practice-cleanup@<practice-op>.service`, and
   continue with the existing step 4 (disconnect and Go), step 5 and step 6
   (`practice-fault.py` arm). These apply to the practice operation only.
4. If the smoke fails, stop. No model money has been spent. Diagnose from the
   collected card.

## Deletes

Nothing in this change. `tools/run-gate-smoke.sh` / `bin/gate-smoke` stay,
because they cover what the smoke doesn't:
- G15 on the real image;
- the `unbug-factory-1-seed` restored-state leftover;
- the `case_permissions` EACCES check;
- the two-slot parallel proof.

Retiring them is a separate decision.

## Tests

The tests use real artifacts: the retained -2 manifest and policy, upgraded to
-3.

- `money.manifest` accepts -3. Both jobs admit, and `smoke` dispatch builds argv
  with `--dry-run` while the practice args are unchanged except for the money
  values.
- The smoke job's budget at 0.01 with zero spend passes the
  `gate_pipeline.py:178` / `budget.py:716` check before G1.
- `finalize_accounting` in dry-run mode yields a card that `collection_facts`
  accounts at 0.000000000. A non-dry card without a ledger is still refused.
  The input is a real collected batch card,
  `tests/factory/fixtures/canary6-collected-card.json` from
  `t3/batch-service-control-vm`, with its ledger removed. That fixture is a
  scorecard. `practice-startup-conflict-20261103.json` is only log excerpts.
- A batch-mode dry run writes `<case>.casekey.age`, and `batch_service._card`
  accepts the collected card.
- No -2 string remains in the cleanup unit, `DROPIN` or `practice.py`.
- Local: real `run.py --dry-run` startup against local Docker reaches G1, with
  the stop-10 fix merged. That proves the dry-run path locally, though not the
  Boat image.

## Murphy rows

`new-smoke-1`: Real-worker environment faults surface only during paid runs. It
is closed by a test that replays the first live smoke's collected card through
`batch_service` and `collection_facts`, committed after that run.

## Risks

- If the smoke's accounting were refused anyway, `state['incidents']` would block
  the whole batch (`batch_holder.py:224`). The fallback would be to cut -4.
- A slow seal after the 1800 s pause could be lost to deletion at +2700 s. That
  limit already applies to the practice job.

## Depends on

- `t3/batch-service-control-vm` (the stop-10 fix and its fixture).
- Preflight merging first, because both edit `practice_preflight.py`.
- `practice.py` and the manifests are in stream B's area, so the coordinator
  (thread 7d333d37) must agree before merging.

## Cost and timeline

About half a day of offline work, at $0. Each live smoke costs about $0.02 of
Boat credit inside the existing $5 cap, and $0 in models. On 2026-11-03 the
founder chose to build this ("Start with 7"). The first live run is still
confirmed with the founder at launch, like every live run.
