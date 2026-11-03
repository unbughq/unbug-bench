# Authenticated batch diagnosis opt-in (scheduling increment 1)

## Objective, scope and baseline

Enable automatic diagnosis for an explicitly selected batch, while every other
batch stays off. Reuse the manifest already authenticated on the control host
and installed on workers. This removes a global switch that cannot distinguish
a pilot from another running batch.

Baseline: lane-1 merge 36dfd7a contains factory-simplify ff31d87 (parent locked
suite 180/0). B's pilot plan is t3/batch-service-control-vm abc11ef,
docs/designs/pilot-run.md, Diagnosis scheduling row (read-only).
The founder's replacement pilot decision is recorded in
stream-d-item8-offline-preparation.md. No pilot or spend is authorized here.

This is the first of three small increments, each handed back after its own
design review, implementation, locked suite and fresh diff review:

1. This increment: authenticated per-batch activation; no tracked batch opts in.
2. Feed eligible authenticated collected generations into batch_service.plan
   from the existing holder tick, only after durable collection ACK. Persist
   planning through the existing journal; no dispatch in this increment.
3. Drain resume requests through holder.reserve and existing reconcile/dispatch.
   Use operation_id(batch, job, source_generation, release) as durable replay
   identity. Revalidate current generation, ACK, retirement, money, deadline,
   existing operation and capacity at the holder boundary. Keep queue rows as
   durable history (their sequence numbers are dense); never delete them to
   mark consumption. Design the exact scanner and refusal rules separately.

Increments 2 and 3 are prerequisites for a working production diagnosis cycle.
Their outline is not their reviewed implementation design. B owns holder/pilot
admission, worker lifecycle limits, cleanup and Boat settlement. This work does
not enable HOLDER_ENABLED or change practice.active. O7 is paused and assigned
elsewhere; no O7 design/code was committed. O5b is deferred.

## Existing path and what this deletes

batch_money.manifest verifies host release and tracked manifest bytes.
job_config.verified_config verifies the worker release, manifest hash, job,
case and money channel. install already stores a separate in-memory
authenticated_batch_manifest and authenticated_job_config on the worker.
There is no need for a new job config field, schema, environment flag, public
scorecard field, checkpoint authority or second authentication path.

Delete batch_service.DIAGNOSIS_ENABLED and replace every production reference:
batch_service.plan; diagnosis_dispatch.apply (two checks) and _dispatch (one);
extension_package.observation_enabled. Remove test toggles of the global.
No outcome router, journal schema, money allowance, launch path or retry rule
is added. No batch manifest under factory/batches is changed.

## Manifest contract and readers

Optional top-level field:

```json
"diagnosis_policy": {"schema": 1, "enabled": true}
```

Absent means off. Explicit false means off. The subobject must contain exactly
schema/enabled, schema must be integer 1 (not bool), and enabled must be a bool.
Null, unknown keys/version, strings and integer substitutes refuse as money_wait
through the existing MoneyWait manifest error contract.

In batch_money add diagnosis_enabled(record): validate that optional subobject
and return its bool, with absence returning False. check_manifest calls this
helper. It imports no worker budget or diagnosis module (host accounting
isolation is retained). batch_service.plan uses it on its freshly authenticated
record at the current global gate location, after retire_legacy and before
projection/enqueue. Disabled plans keep diagnosis_unavailable.
Legacy retirement remains independent of activation.

In job_config add diagnosis_enabled(c): use only the installed
authenticated_batch_manifest, never c.card or checkpoint_card. Missing installed
manifest means False. Validate policy with batch_money.diagnosis_enabled.
If off, return False without creating authority. If on:
- call job_authority.for_case(c), preserving money_wait/retired_batch_bound;
- require manifest id and batch_deadline to equal the current authority's
  batch and batch_deadline; mismatch becomes BudgetError('money_wait');
- return True.

Policy validation MoneyWait, missing keys or malformed installed manifest map
to BudgetError('money_wait'); do not rename a BudgetError from for_case.
The installer is the authentication boundary: only it installs these separate
RAM objects after the release/config/manifest verification above. No helper
re-reads a restored manifest or accepts a caller-provided bool. Failed install
already resets authenticated_job_config, so a stale manifest cannot authorize
an enabled call through for_case.

The worker uses job_config.diagnosis_enabled(c) at all existing global gates,
including observation_enabled (retain factory_job, audit and rehearsal guards).
Do not add worker scheduling or a second dispatcher.

## Enabled and disabled behavior

| Input | Host plan | Worker gates |
|---|---|---|
| Missing/false policy | diagnosis_unavailable, no D import or queue write | Existing disabled diagnosis_pending/comparison refusal; no new diagnosis call or extension admission |
| True policy, valid current authority | Existing projection/enqueue code | Existing enabled diagnosis invocation, extension selection and first-entry capture |
| Invalid policy or mismatched current authority | Existing manifest money_wait | money_wait/retired_batch_bound, no model work |
| True only in scorecard/checkpoint/environment | Off (manifest decides) | Off (installed manifest decides) |
| Another batch opted in | This batch remains off | This batch remains off |
| Unpinned edit to manifest bytes | Host authentication refuses | Worker release/manifest hash verification refuses |

This deliberately preserves replay semantics: completed decision validation,
factory-bug hold recovery and retirement still run where they already do.
The new flag replaces the old gates, not a new early return that bypasses
evidence validation or loses a completed result. A prior opted-in checkpoint
does not opt the current batch in; install uses the current launch manifest.
Turning the flag off cannot enlarge money or retirement authority.

## Tests and evidence

Use saved public cards/ciphertext in ServiceTests and saved 5813be ledger,
practice case bytes and job-money fixture in the existing D suites.
Manifest/release envelopes and CLI answers remain explicitly authored controls;
this is offline wiring evidence, not pilot qualification or row closure.

- test_batch_money: absent/true/false and each malformed policy; policy-only
  tampering still fails the existing authenticated manifest digest check.
  Keep test_host_job_config_does_not_load_worker_accounting passing.
- test_job_config: extend its real deliver/verified_config/install path with
  pinned opted-in manifest bytes. Assert the installed policy gates diagnosis,
  card/checkpoint spoofing does not, hash drift refuses, and a subsequent
  disabled manifest install turns it off. Enabled query with wrong current
  channel, batch/deadline, missing binding and expired authority refuses before
  work. Missing/false policy works with old schema-1 config (no extra fields).
- test_batch_service: migrate fixtures to manifest policy (freeze before collect,
  never mutate a pinned journal's manifest). Keep disabled no-import/no-queue
  proof and exercise enabled real plan projection contract as before.
- Existing stream-D tests: replace global toggles with temporary authored
  installed manifest policies on their own c objects. For broad control-flow
  suites this is explicitly a policy control, not proof of installation.
  Preserve real for_case checks; do not mock the production predicate merely
  to turn diagnosis on. RuntimeTests can supply an authored default-off
  installed manifest matching its existing current job-money identity.
  Tests using ResumeTests keep its existing full manifest and change only
  diagnosis_policy. Main subprocess harness serializes this authored RAM
  manifest with its existing authored install control and selects per-fault
  opt-in there; the real install proof stays in test_job_config.
- Re-run all affected files and the full suite under the shared lock, unique
  committed log+JSON. No new live calls, workers, provider checks or secrets.
  No timeout weakening or duplicate simultaneous full suite.

## Cost, payoff, risks, exams and exit

Offline cost $0 inference/infrastructure; one bounded implementation cycle.
Payoff: B can pin a pilot-specific flag in its later reviewed manifest without
enabling other batches or adding a worker config channel.
Risk: tests historically patched a process-global constant in many files.
Migrate those controls explicitly; retain dedicated real authentication tests
so passing control-flow tests cannot be mistaken for authorization proof.
The auth/shape check must stay shared on host/worker to prevent drift.

Midterm: real installed config plus two independently pinned batch manifests
prove only the selected batch can opt in. Final: affected files, locked full
suite, fresh diff review (at most two rounds each). No Murphy row closes:
row 9 needs the later real production queue-to-diagnosis cycle; the
current-comparison row remains open. No live activation until the remaining
increments, B prerequisites, item 7 and founder pilot conditions are met.

## Design-round-1 dispositions (binding)

Review passes. Apply evaluates the worker policy once on its close_to_passing
branch and reuses that bool locally. Separate dispatch/invocation and apply
boundaries revalidate current authority; a deadline expiring after decision.json
is durable intentionally refuses with retired_batch_bound. The in-memory card
may already be completed, but replay must consume the same retained decision
without another diagnosis call. Add that explicit regression.

observation_enabled runs its cheap factory/mode/audit guards first, then policy.
An enabled-policy BudgetError propagates from run_gates before observe or
pipeline.run. Add an expired-authority regression at that actual boundary.

Reset authenticated_batch_manifest to None alongside authenticated_job_config
at install entry. Migrate test_batch_admission_clamps too. The main subprocess
control serializes authenticated_batch_manifest and selects per-fault policy
inside its authored install function. Update docs/practice/b3/preflight.py to
check its pinned manifest policy instead of the deleted global. Update the
item-8 rollback paragraph: absent/false policy in a new reviewed release/batch,
or stop B admissions; a pinned journal cannot be toggled in place.
