# Architecture

The repository contains a local inventory benchmark, a scored exam, and a factory
that builds sealed exam cases. This describes the implementation on this branch.

| Area | Ownership |
| --- | --- |
| `projects/medusa/` | Pinned application, Docker Compose services, seeding and database baseline. |
| `cases/`, `guards/`, `scenarios/` | Traffic, promises, guard implementations and maintenance changes. |
| `bin/bench.py`, `bin/bench_judging.py` | Runtime orchestration and pure verdict calculations. |
| `bin/checkpoint*`, `bin/exam*`, `bin/strategy*` | Trial evidence, exam execution and strategy simulation. |
| `factory/run.py` | One case's builder, qualification gates and scientific criteria. |
| `factory/gate_pipeline.py`, `factory/calibration.py` | Gate sequencing, reusable passes and calibrator attempts. |
| `factory/model_runtime.py`, `factory/model_router.py` | Model execution, routing, usage accounting and provider handling. |
| `factory/durable/engine.py`, `executor.py`, `runtime.py` | Durable scheduling, execution and control-side composition. |
| `factory/durable/workers.py`, `channel.py`, `worker_step.py` | Worker provisioning, authenticated transport and execution. |
| `factory/durable/ledger.py`, `keys.py`, `artifacts.py` | Money reservations, scoped keys and encrypted artifacts. |
| `factory/durable/checkpoints.py` | In-step snapshots and evidence-bound completion receipts. |
| `control/` | Control VM setup and services. |
| `harbor/` | Harbor task packaging and adapters. |
| `tests/` | Offline regressions, explicit live probes and retained evidence fixtures. |

A batch is built from a clean, pinned Git commit and admitted through the control
service. Workers run the case builder, then the configured gate pipeline. The
runner records scorecards and checkpoints; collection returns encrypted evidence
and publishes the allowed summary. The existing production release remains pinned for rollback. This candidate has
removed its legacy launchers and controllers; shared runner and budget callers
now use the durable path. Live cutover is not yet qualified.

The benchmark resets its own Postgres/Redis stack for each trial. A reset that fails before
the guard is installed, with hard evidence that Postgres crashed (`pg_isready` fails, or its container
is OOM-killed or not running; never error text), restarts it once, records the container state and
any readable OOM line in the trial, and redoes the reset; if that fails the same way the trial's
worker stops with one infrastructure error (in a parallel pool, other slots finish on their own
stacks first). A failure once the guard is being installed stays that trial's ordinary reset error. The checker uses
read-only database access. Parallel factory slots have separate Compose projects,
volumes, ports and seed manifests. Model roles run with information walls between
case internals, testers and contestant-visible material.
Durable OpenCode calls put each role's private CLI state on an executable tmpfs.
After process containment closes, cleanup unmounts that state instead of overwriting
a potentially large disk cache.
A call cgroup left unlocked by a dead owner (a step killed at its deadline) is killed, emptied
and removed by the next call's check; a poisoned or undrainable one still refuses containment. Failed cleanup remains an infrastructure failure.

## Invariants

- Infrastructure failures are invalid runs, never scientific passes or failures.
- Gates and judging own case results; launch and recovery plumbing only carry them.
- Preserve contestant secrecy, role isolation and authenticated checkpoint inputs.
- Enforce approved money, call and time ceilings across retries and continuations.
- Genuine provider limits are handled by waiting, account switching or an approved
  fallback in the same model family; they must not shrink or terminate the plan.
- The control VM and remote artifact storage own batch lifecycle. The founder's
  laptop must be able to disconnect without stopping it.
- Resume follows the checkpoint launch path. Avoid one-off per-case rescue paths.

These are engineering requirements, not a claim that every failure mode is already
automatically recoverable. Unit tests do not qualify a live worker release.

## Durable-execution migration

`factory/durable/contract.py` v6 defines the shared records, wire protocol, keyed
references and package interfaces. Its reviewed change permits restoring ADMIT
checkpoints; the wire fields remain the same. The candidate integrates the DBOS engine, executor,
Boat worker pool/channel, worker-side steps, SQL ledger and wrapped-key service.
`guard.py` is the campaign's minute-by-minute check, for one batch (`batch_id`) or several started side
by side (`batch_ids`: each keeps its own bound, the campaign finishes when all are terminal, and one live
worker per watched batch is allowed): failures pause new attempts. A stall (a case waiting for credentials or
the router, no case, ledger or router-spend progress for 15 minutes while cases are live and no step is in flight, or a case parked on a
founder decision for 30 minutes) reads `degraded` with its reason in `stalled` and alerts; it pauses nothing. Only a money,
deadline or confirmed Boat limit is a hard stop: after a bounded checkpoint grace the guard stops the
controller and deletes the workers. Worker size is a Boat type: the controller config's `vm_type` (Boat's
default when absent), or for a bounded campaign the request's `vm_type` (default `"default"`), read at each
create. A type other than `default` needs its approved rate in the request's `worker_rates_usd_per_second`
(e.g. `{"large": ...}` for 8 vCPU/16 GB); otherwise nothing is created and the guard degrades. The guard's
compute bound uses that rate and each live worker is judged at its own Boat type's approved rate, so a
large worker does not trip the default type's `max_worker_rate_usd_per_second` (always the default rate; a
`"default"` key in the map is ignored); the infrastructure approval is unchanged, so a dearer type fits
fewer running slots. `preflight.py` adds advance warnings to the guard's alerts and
status (router TLS certificate, router paid headroom, campaign deadline, unbounded routes); they never
degrade, pause or stop, and an unreadable input is an "unknown" warning. The guard itself alerts once router
paid spend reaches 80% of its ceiling and when the provider credit falls below a floor (`UNBUG_LOW_CREDIT_USD`,
default $25), each with the time left at the last hour's spend rate; `unbug board` shows the same wallet line.
On SIGTERM the engine drains, then
exits without touching DBOS again, and systemd restarts it unless an operator stopped it.
Restart the controller or send a plumbing or bench release only when `control/check-drained.py --config
<config>` exits 0: no attempt holds a leased worker without its recorded `attempt_step`, and the
model router holds no unexpired lease (read-only; exit 1 names what runs, 2 means unreadable). Restarts
and release sends mid-step cost 19 hours of `infra:worker_lost` from 6 November.
`runtime.py` composes these components; `cli.py` exposes a private operator socket.
`client.py` reads that operator's public status/report over SSH using a saved local
connection and default batch. `bin/install-unbug` packages a standalone read-only
client with Python's standard library; it neither imports DBOS nor starts recovery.
Controller-local status clients enrich the public scorecard with read-only ledger
and DBOS observations plus worker ownership journals. They never poll workers,
decrypt artifacts, start recovery or change reservations. The formatted output
distinguishes current attempts from historical results and reserved from spent funds.
Status/report clients remain available while the controller is stopped; they read
persisted cards via DBOSClient and show service liveness separately from workflow state.
Plumbing bundles include their authenticated `bin/processes.py` runtime helper;
factory imports and qualification use that release copy. Scientific bench files
remain on the separately pinned worker image.
Images may supply `~/bench-source/prepare.py` to verify their bound public source
and prune obsolete files restored by a snapshot overlay. This runs before release
qualification and key delivery; changed source fails preparation.
`control/release.py` makes both releases from one git commit on the control VM, recording each step
under `~/.unbug-release` so a rerun resumes where it stopped. `bake-bench <commit> --from-image <current>`
builds `~/bench-source` (tracked bench files hashed as git blobs, the reviewed `tools/install_source.py`
pinned by sha, a `prepare.py` binding manifest, bundle and count), installs it on a sandbox of the current
image keeping Medusa's generated files, runs `bin/bake-image.sh` and `prepare.py`, writes
`~/bench-source/result.json` ({source, bench_version, source_files_verified, no_model_secrets, model_calls}),
snapshots it under a name unique to that bake, `durable-bench-<UTC date-time>-<sha7>` (never `bench-env`, the
source image or an earlier bake), and tests a fresh sandbox (`prepare.py`, bench fingerprint, that
result.json, and unless `--no-image-build` the Medusa image build). Its sandboxes are named
`bench-bake-…`/`bench-test-…`, which the pool never claims as case workers; the name is recorded before
the create, so a lost create response is found in `boat list` and deleted. `build-plumbing <commit>` builds
the commit's bundle with its own `workers.py release`; `register` runs `bin/unbug install` (both it and
`send` refuse a bench tested without its Medusa build unless `--allow-unbuilt`); `send` runs `bin/check-release-pair.py`,
then requires `control/check-drained.py` to exit 0, then sends `plumbing_release`/`bench_release` per
batch; `switch` checks drained and prints the root commands (source-current symlink, unit restart) without
running them. Every Boat call goes through `bin/boat-call` with `BOAT_NO_UPDATE=1`.
The control units and setup script live under `control/`. ADMIT reuses the existing
selector, registry, freshness and idea-realism screens. A retried ADMIT keeps the provider
preflight checks that passed in the same step within 30 minutes and re-asks the rest; an unresolved G2
freshness review is asked again up to twice within the attempt, re-fetching flagged pages not read
live (the hit still blocks until cleared)
before the admit fails `infra:freshness_review_unavailable`. Unless INPUTS pins `rotation_slot`
or models, a new case's rotation slot cycles by the count of other cases on the registry
board, which batches carry forward, so one-case batches still rotate. DIAGNOSIS uses the existing
review contract through an isolated pilot user. These paths passed combined offline
qualification; live worker qualification remains before replacing the production
release.

The target is DBOS 3.4.0 on control-side Postgres. Workflow replay reuses recorded
results, with idempotent attempts keyed by case, sequence, step and attempt.
Workflow functions remain deterministic: clock reads and external effects go
through steps, waits use DBOS, and workflow changes use `DBOS.patch()`. Pin the
application version for the database lifetime and register admission queues before
recovered work can enqueue. Attach to existing workflow IDs when resuming.

The case sequence is ADMIT → WRITER → STRESS → GATES → SEAL, with bounded repair,
diagnosis, extension and reviewer-escalation paths. STRESS runs at most `ATTACK_ROUNDS`
(2) times with findings: the last round's findings get one writer fix (`final_fix`) and
the case goes to GATES without another stress round, also from an extension or a gate
repair. The first seq the cap governs (`attack_cap_from`) is recorded as a DBOS event
under the `attack_cap` patch and carried by `resume_point`, so older workflows and
resumed lineages replay their recorded rounds unchanged. ADMIT is serialized per batch;
the active scheduler checks its recorded deadline after funding, before the first
ADMIT dispatch. Queued or unfunded admissions expire with their holds released;
an ADMIT already dispatched may continue across the cutoff and provider waits.
GATES retains the existing pipeline and per-gate cache rather than duplicating it.
Workers publish encrypted snapshots at model and gate boundaries. The channel
fetches the latest committed snapshot; progress not fetched before a worker loss
can still be lost. Completion receipts reuse work only under matching instructions,
inputs and release bindings. Same-case mutable model calls serialize for coherent
snapshots, and isolated calibrator snapshots wait until their workspaces join.
Cases admitted since 10 November carry `bench_workers: 2` and `parallel_gates: true` in their
`recovery_config` (`durable/steps/admit.py` `NEW_CASE_SETTINGS`; recertified imports keep their
own settings while no writer round runs). A case admitted earlier, a recertified case sent to a
repair round included, adopts them when a new writer round begins
(`run.adopt_parallel_checks`): every check and gate runs again after a writer round, a retry of a
round that already began keeps its settings, and an explicit `parallel_gates` on the card is never
overridden (`false` is the only pin; an older card's `bench_workers` is replaced). For those cases G10's two calibrators run at once and
may overlap the bench gates from G6, and G2, G8 and G9 run in order on a second thread after G1,
joining before G6. In a writer step's early checks under the same G10 overlap conditions
(`run.early_lane`, at least two bench workers), G3 runs first, then G15 keeps the foreground pool
while G4, G5 and the saved-cheat sample run in order on the first reserved tester instance; both
finish and every failure goes to the writer in serial order. The lane is fingerprinted as the
foreground case (`gate_state.inputs`; instance and worker count are not scientific), so GATES
reuses its G4/G5, and each gate's evidence is scoped to its own lane's files. Otherwise the serial order G15, G3,
G4, G5, saved cheats is kept. Any snapshot requested while two threads work on the case is deferred
(`durable.checkpoints.concurrent_section`) and one is published when the last section joins; a
case edited during that lane fails the step as infrastructure. The writer step records fixed
phase timings (`bench_prepare`, `writer_model`, `g1`, `early_checks`, `freshness`) in public
progress and the card's `phase_times`. Before another writer call and its checks in the same
attempt, the round compares the time left with 1.25 times the cycle just finished plus 15 minutes;
when it is short, it records the findings and next call in `attack-state.json` (`handback`) and
returns `writer:handback` (OK, with its snapshot). Under the `writer_handback_retry` DBOS patch the engine retries that seq outside the infra
allowance (a STRESS step finding a pending handback stops as infrastructure). The writer hands
back at most `min(rounds - 1, WRITER_HANDBACK_CEILING)` times per round, counted in its receipt
across attempts, where `rounds` is the case's own call cap from the card's `recovery_config`; the
engine, which does not see that card, counts handbacks past `WRITER_HANDBACK_CEILING` per seq as
infra (past `MAX_WRITER_HANDBACKS` for workflows recorded before the `writer_handback_ceiling` patch), and the new attempt continues the round at that call with those findings. The early
saved-cheat sample shares one 30-minute allowance; cheats it does not reach are recorded
`unchecked` (it is advisory; full G6 runs them all), and a spent allowance is never an infra retry.
An older card with no `parallel_gates` key also adopts just that flag at GATES entry
(`run.adopt_parallel_gates_at_entry`), leaving its `bench_workers` value unchanged so its
already earned gate cache identities remain valid. An explicit true or false stays pinned.

DBOS records identifiers, keyed digests, fixed reason codes and numbers only.
Case material belongs in encrypted artifacts, opened in worker RAM. The control
side transfers blobs; workers receive no R2 credentials. Invoke executors through
`guarded_run`; sanitize exception paths and disable Conductor/DBOS Cloud.
Worker steps share structured wait classification: quota/rate/credit/capacity wait durably,
credential delivery, unbounded routes and router outages park without consuming
infrastructure retries; known CLI and unavailable-model faults retain the finite
infrastructure allowance. Each wait, and every failed step, killed, crashed or raising included, retains an
encrypted operational diagnostic with allowlisted causes, retry times and lease
IDs. Worker diagnostics automatically include safe HTTP statuses and error categories.
Scope-bound `durable.diagnostics` inspection runs in worker memory and exports
only operational codes and numeric usage; it never extracts or returns case text.
ADMIT's first attempt may have no snapshot; retries restore the last authenticated
case snapshot under the same case key, retaining its ledger and completed model
receipts while reading the current serialized registry. Contract version 6 relaxes
only ADMIT's input snapshot restriction; other steps still require a snapshot.
The engine guards the changed retry input with a DBOS patch for replay compatibility.
An ADMIT infrastructure failure that exhausts its retries backs off without a
queue slot or outstanding grant, keeping any healthy worker so retries don't spend the
worker creation allowance, then retries the same release once from its snapshot and ledger. The wait doubles to an hour. The case is held after eight backoffs, and as
soon as its infrastructure waste reaches the case's money or the worker creation limit
is hit, with no further retry. After a batch deadline, checked again after each wait,
admission stops.

Workflows that parked before this path existed replay as `waiting_for_release`: a
different plumbing release resumes the same case and sequence from its snapshot and
ledger, previously failed releases cannot resume it, and repair-release continuations
are capped at three and by `max_factory_bug_resumes`. Candidate exhaustion still stops
admission. A DBOS patch preserves historical terminal behavior; already
completed workflows are not revived by deploying the new code. Original admission
exceptions and chained tracebacks stay inside encrypted diagnostics. Snapshots survive
a repair release; generic completion receipts remain bound to their original release.
Malformed retained answers exhaust routes within one Engine attempt. A new funded
attempt may append a fresh judgment, retaining prior rows, outputs and all spending.
Same-attempt replay cannot reopen that allowance, and pending or valid completed
answers are reused. Legacy retry state adopts its first observed attempt key without
guessing that an exhausted allowance can be reset.
Optional `worker_credentials` configuration names an encrypted bundle, control
identity, router client file and selected model accounts. The controller decrypts
in memory and delivers only those accounts and router authority into worker RAM
after release qualification, including on reuse. Credentials never enter images,
release bundles or workflow records; isolated model users lose router authority.
For a legacy registry, `worker_credentials.legacy_registry` also delivers its
statement identity to worker RAM. ADMIT verifies and rewraps occupied statements
under the batch key there, preserving registry history without opening case
material on the controller. The source registry remains untouched.

A pre-durable case can be imported as a one-case batch. On the founder's Mac,
`bin/rewrap-legacy-checkpoint` streams its founder-encrypted archive to the statement
recipient; `prepare <first case id> case <file>` stores that ciphertext unopened under the
case scope, and `start --import-file` passes the ref as the first ADMIT snapshot (only with
`max_cases_started` 1 and `legacy_registry`). ADMIT opens it in worker RAM with the
statement key and keeps only the old case tree: its card, ledger, caches, reviews and
search evidence are dropped, and the old card survives as numbers in `imported_from`.
The existing screens then run once on the case's own statement, skipping only its old
registry entry, and a rejection ends the case without selecting another idea. A case
whose old card passed G1 starts at STRESS; others start at WRITER. Every gate reruns.
The old writer must share today's writer family, so separation rules still hold. Unless
INPUTS pins models or a slot, ADMIT takes the first rotation slot with that writer family;
only an October family absent from the table, or a conflicting pin, refuses the import. The
old spend is not carried in the ledger: INPUTS declares it as `import_spent_usd_micros`,
ADMIT refuses unless it matches the old card, and `start` refuses unless it plus the
batch's `case_money_usd_micros` fits the default per-case ceiling. Import refusals
(`admit:import_invalid`) are deterministic, so they end admission instead of retrying.

A case sealed before G16 and G17 existed is recertified the same way, with INPUTS
`"recertify": true`, a `recovery_config` (the exam reads it) and no pinned models, roles or
slot. ADMIT refuses (`admit:import_recertify`) without a legacy import, or unless the archive's
own card passed G1 to G15 (G12 aside) and names one model per role with its effort. Those models and efforts become the new card's, so the kept verdicts and the rerun
gates have the same roles. `recertify_routes` may move the writer, stress tester or a calibrator
to another model of the same family (the October GLM easy calibrator ran on a free route a
walled calibrator can no longer lease); reviewers stay, since the exam's owner contract binds
the reviewer. Every role still needs a bounded route: the admission screens and GATES rerun the
freshness check, and expired October search evidence is topped up by the writer and stress
tester. ADMIT then answers `admit:imported_sealed`, and the engine skips WRITER
and STRESS: GATES keeps the October verdicts for `run.RECERTIFY_KEPT` and runs only G2 (today's
freshness), G3 (to prepare the worker's runtime), G16, G10, G17 and G11, then SEAL writes the owner contract and
delivery receipts as usual. G10 reruns because G17 and the receipts need this run's calibrator
workspaces. A gate that asks for a repair, or a diagnosis that would extend, retires the case;
a diagnosis that finds infrastructure holds it as for any case. A case retired by a gate's
repair request can be resumed: the resume replays that GATES step, gives its feedback to one
writer round and then runs all gates (no stress round, the October case had its own), and
later resumes of that lineage carry the repaired GATES seq so the decision replays.

An archive whose draft cannot be kept (its writer changed family mid-run, or it stopped
before its case.json) can be imported idea-only: INPUTS sets `"import_mode": "idea_only"`.
ADMIT keeps only statement.md, which must match the old case's registry entry when one
records it; promise.md and case.json are written from INPUTS once the old case.json (if any)
matches the pin and source, or the old card names the same source. The case starts at WRITER
whatever its old gates said, with a MiniMax or DeepSeek writer. Every family the old card
names as a writer is an idea author and may not hold a reviewer role or the easy calibrator
(`admit:import_idea_family`). Spend, screens and the one-candidate rule are as above.

A rejected idea publishes `admit:<screen>_<evidence>` (`durable/admission_reasons.py`): the
screen (dedup, freshness, realism, other) and a fixed evidence kind read from structured
fields only, such as `freshness_upstream_fix`. The sealed card keeps per-candidate codes
(duplicate case ID, confirmed source classes, a release tag's version against the pin).
`python3 factory/durable/admission_reasons.py --config <config> <case|batch>...` prints
those codes for finished cases on the control VM: read-only, existing keys only.
`durable/board_cleanup.py` dedupes the statement board: a one-case batch with INPUTS
`"board_dedup": true` has ADMIT group the board's statements with the easy calibrator in
worker RAM and record only case IDs (`admit:board_planned`, no registry returned); on the
control VM `plan` (dry run), `apply` (new board file plus change log) and `revert` change
entry statuses only. Sealed, live and known_public entries stay; each duplicate group keeps
its most advanced member; other abandoned entries are released.
`control/prescreen.py` screens a manifest of ideas (INPUTS, optional import archive and old case
ID) before a batch starts, so start slots go only to ideas ADMIT can admit. It reruns ADMIT's own
deterministic checks offline and spends nothing: `admit._inputs`, `admit:board_planned`, and with
`--identity` (which needs `--board`) the import archive through `admit._import_legacy` plus
ADMIT's writer-family checks against the models ADMIT will use (a recertify's sealed October
models). The archive is decrypted to the control machine's disk temp dir, not RAM, and removed
after. Dedup uses only digests and recorded verdicts: an exact statement digest held by an
unreleased board entry or an earlier manifest idea (drop for an import, which has one candidate;
review for a fresh idea, whose writer may reselect), and the duplicate groups
`board_cleanup.duplicate_groups` builds from the admission-reasons backfill (`--history`) and
`--group`, each with the keeper `board_cleanup.plan` would keep (after cleanup, the one member
left on the board); a keeper whose group members are
still unreleased must have them released first. A recorded final dedup, freshness or realism
rejection of the same idea is flagged for review. Freshness and realism themselves need models
and are not run, and no check reads difficulty. It prints a table: drop, review or ok per idea.
A first judge's duplicate or realism rejection is final only when a second family agrees
(`run.dedup_second_opinion`, `run.realism_second_opinion`): never the writer's or the first
judge's family, a free route first, refused up front when none qualifies. On a disagreement
the idea goes on to the next screen. Cards record `second_opinion` {second_family, agreed}.

Every request in a `model_router.CHAINS` chain starts at the chain's head, whichever member was asked
for. The heads are the OpenCode Go plan routes on both founder accounts (DeepSeek, MiniMax, MiMo, GLM),
then OpenRouter's gated paid route; the anonymous free DeepSeek and GLM lanes hang, so they come last.
A Go route has no gate: the plan's allowance pays (Extra Usage stays off), each step is booked at the
OpenRouter twin's list price (`token_prices.GO_TWINS`, `go_step_cost`) or OpenCode's report if higher, and
its lease maximum is the twin's, so the reservation check stops it as Codex's (`model_call_cap`). Its quota is published as the account's block,
so the next call takes OpenRouter. The router's money ceiling counts only OpenRouter's paid requests.

OpenCode's free routes (DeepSeek, MiniMax and GLM flash) are bounded at $0 with no gate: a call that books
any cost, or reports a step from another provider or model, is stopped. Free and Go calls run with their
OpenCode provider and one model only, no outside config and no self-update. A calibrator is never leased
either, since behind the wall it reaches only a gate's port: it takes its chain's OpenRouter route, and a
chain with none is refused up front as `unbounded_route`. A full or failing lane hands an unwalled call to
the next route in its chain.
A usage-limit (quota) failure on an OpenCode Go account is published as that account's router health
block until its reset, even when it came from an unstructured CLI line, so later calls skip the exhausted
account instead of retrying it per call. The failed call itself moves on inside its attempt, to the same
model's next route (the other Go account, then its OpenRouter twin): a Go call's unseen usage books $0, so
nothing needs settling first (`model_runtime.go_quota_moves_on`). Any other Go fault ends the attempt as
before, since a refusal or crash would repeat on the paid twin. Chains never cross model family
(`model_router.routes` refuses one that would).
When every seat of a lane is leased to our own calls the router answers `capacity`, not `rate`, to clients
that send `capacity_protocol: 1` (older ones still get `rate`): no provider refused anything, so no health is
published. The call waits in its worker, in FIFO order, for up to `model_router.CAPACITY_WAIT_SECONDS`
(30 min, within the step deadline and the call's own timeout); only past that does the attempt end, as
`router:capacity`, a provider-limit sleep of at most one lease that keeps its worker. Seats are the router
config's per-pool `capacities` (default 1, at least 1); size each pool at least concurrent cases x
concurrent model calls per case on it, counting an exam owner question (asked while its calibrator still
holds a seat) as one more call.

Codex (`codex/gpt-6.1-sol`, the strong calibrator's other family) has no gate either. Its lease
maximum is $50 at the Codex list price (`CODEX_PROFILES`), lowered by funding. The runtime reads Codex's
own session log (`exec` without `--ephemeral`) every few seconds and books each request at list price as
it lands, so the reservation check stops a long turn mid-way; that stop is reported as `model_call_cap`,
as a Claude gate's exhaustion is. Tokens the turn total reports but the log never showed are booked at
the long-context tariff; an unreadable log stops the call (`missing_usage`). Codex's web search and
other tools stay off (`CODEX_OFF`, `web_search="disabled"`), and the wall is unchanged: it blocks local
and private networks, and Codex reaches its public API as before.

A durable case stopped by an infrastructure failure resumes instead: `start --resume-case
<case>` makes it the only case of a new batch. It keeps its case ID, so its key, artifacts,
snapshot card and admission binding stay valid. Only its workflow is new (`<case>@<batch>`),
and the batch maps it back for cards and seals. `engine.resume_point` allows this only when every
workflow of the case finished held or retired and its last attempt (the newest by creation, not the
highest seq: a `factory_bug` resume rewinds below an older diagnosis) ended `infra_error` or
`provider_limit`, never after a verdict, gate, limit or founder decision (one exception for a
`factory_bug` hold follows below). The new workflow
replays every earlier seq from the attempts recorded under the case's keys, with no worker,
wait or message. If any attempt it needs is missing, it fails (`resume:diverged`) rather than
starting new work in that history. The stopped seq first restores its recorded attempts
(their snapshots, diagnostics and keys, so a changed step also diverges), then continues
with a fresh infra retry allowance.
Replayed seqs keep the bench their attempts recorded; the first live seq, unless it is GATES or SEAL
(which take their versions as before), adopts the new batch's current bench release (patch
`resume_adopts_bench`). Nothing kept depends on the old bench: SEAL runs only under its GATES versions and
every later path to SEAL passes a GATES step, which adopts the current bench anyway.
Counters, snapshot and evidence therefore come out of the same code that built them. `start`
refuses unless the earlier spend (the ledger across the original and every earlier resume
batch, plus any declared import spend) plus the batch's
case money fits the default per-case ceiling. Run the resume batch with the stopped batch's
limits, or the replay diverges. Case money is the exception: it is what the case may still spend,
so it is the $50 ceiling less the import spend and less what every earlier batch of the case used
(the ledger holds only batch spend, never the import's, so nothing is counted twice). A recorded
attempt replays from its key whatever case money its job now carries.

A case held by a `factory_bug` diagnosis resumes the same way, but only when the diagnosed step
stopped on a factory check rather than a scientific result (`FACTORY_BUG_RESUMABLE`: today a
writer's `writer:unchanged_repair` or `writer:output_capped`), or when it is a GATES, writer or stress step
whose every attempt ended `infra_error`, `provider_limit` or (before an earlier such resume) one of those factory checks (`FACTORY_BUG_RESUMABLE_INFRA`): the step reached no verdict, writing or finding, so
running it again is one more infra retry, not a re-roll. It resumes at that diagnosed step, not at the diagnosis, so
the diagnosis is not replayed. A later diagnosis at that seq numbers its attempts after it
(`renumber`). The lineage's count of these resumes carries into the new workflow and is added
to the case's own `factory_bug_resumes` when a diagnosis is decided, so the policy's cap of three
covers factory_bug holds across batches. Skips an earlier resume made at or above the diagnosed
step are dropped, since the steps that now take those seqs never ran there. A writer round keeps the case hash it started
from in `attack-state.json` (`round_start`, bound to the round's feedback), so a retry that
restores an interrupted call's edits is not judged an unchanged repair. A writer reply whose last
step stopped at the output cap applied none of its edits: the round retries that repair within its
call cap with `output_capped` set, and only a cap on the last call ends `writer:output_capped`.

Such a hold no longer needs that batch (patch `factory_bug_release_wait`). The case workflow parks
as `held_for_release`, without a worker, until the batch's plumbing or bench release differs from the
one the diagnosed step ran on, or `cli.py resume_held <case>` gives the go-ahead. It then continues
exactly as the resume would: the diagnosed step runs again at its seq after its recorded attempts, on
the current releases, its attempts' money is booked as `factory_bug` waste, the diagnosis is
uncounted and `factory_bug_resumes` grows, so the policy's cap still ends a loop. A release equal to
the failed one never resumes it; any other plumbing or bench release does, whatever the step (writer
and stress steps run on the bench image too), so an unrelated release costs one of the lineage's
resumes. Plumbing and bench releases both wake it (patch `bench_release_wakes`). The operator's go-ahead
names the hold (diagnosis seq/attempt), so a leftover one never frees a later hold. At the batch
deadline it is held as before, for `--resume-case`, which counts the resumes made in place that it
will not replay (event `factory_bug_rerun_seqs`), so the cap holds across batches; a workflow that
held before the patch stays held. Escalations (`NEEDS_FOUNDER`) never take this path.
The board shows `held: waiting for a factory release` apart from `held: needs your decision`, and
the guard neither alerts on it nor counts it as a stall.

Founder 2026-11-11: an operator override resumes, once per lineage, a case these rules refuse:
`start --resume-case <case> --override-reason <text>`. It drops only the rerunnable-stops and
held-only requirements of a `factory_bug` diagnosis, `MAX_FACTORY_BUG_RESUMES`, and the
infra-last-attempt requirement for a held or retired case whose last attempt reached no result
(it never started, stopped on infrastructure, or on a `FACTORY_BUG_RESUMABLE` check), or whose
diagnosis said `close_to_passing` and the batch deadline alone retired it (it had extensions left,
its last extension progressed, and it is not a recertified case). It resumes where the rules would: the
diagnosed step after a `factory_bug` diagnosis (booked as `factory_bug` waste, the resume counted),
otherwise the stopped step itself, so such a diagnosis is asked afresh. It never resumes an
unfinished, unknown or sealed case, nor a scientific stop (`resume:scientific_stop`): a gate verdict
other than a recertified case's repair, a `NEEDS_FOUNDER` escalation or a stress round's findings,
whether last or among the diagnosed step's attempts, and no diagnosis verdict but those two; nor an
exhausted round, call or cost ceiling (`resume:ceiling_stop`, such as `writer:rounds_exhausted`):
FACTORY.md raises those by explicit flags, never by a reset. The
reason rides in the resume record, so a second override of the lineage is refused
(`resume:override_used`); an override the rules did not need is not recorded. A lineage past the cap
retires at its next `factory_bug` diagnosis. The override's case card and the board show the reason;
the published scorecard does not.

Reserve allowance before dispatch and settle actual usage idempotently. A call whose gate refused
every request (exhausted, nothing forwarded) settles at $0, not its hold; `start` refuses a batch
whose batch or case money cannot hold one request on its dearest gated route (`bound_below_call_hold`;
a Claude request reserves $9.52, its full context with the uplift). Worker
model calls atomically reserve their router Lease maxima against that attempt
before launch, including parallel roles. Supported provider gates must enforce
those maxima; unbounded routes are refused. This requires live qualification. Lost
attempts book the grant as infrastructure waste; broken runs charge the batch's
waste line, not the case. Ordinary work draws on case and batch money; diagnosis,
extensions and post-diagnosis work draw only on the batch bound. Batch exhaustion
waits without holding a concurrency slot. Zero-cost genuine provider limits wait
without an attempt-count cutoff; they never retire a case merely for recurring.
Claude OAuth requests omit the organization-dependent `inference_geo` parameter.
Modern-model holds cover the 1.1x regional uplift; missing/unavailable response
geography stays conservatively priced, while explicit global usage releases it.
Engine invocations request a quote bounded by their currently uncommitted attempt
funding. OpenRouter qualification-sized default windows are replaced by this
funded window (at most $50, and at most $12.50 for every role but the writer on every family,
Codex and Claude included, so four such calls fit one grant at once and a non-final receipt, which
books its whole window, cannot exhaust it); explicit Claude profile ceilings remain binding.
A reservation is marked launched before its model process can start; a pending one never
launched spent nothing, so spend accounting and crash reconciliation settle it at $0, while
admission still counts it.
The router persists and validates that quote, and the worker atomically reserves
it before execution. Exam calibrators leave a qualified reviewer window outside
their hold so nested owner questions remain funded. This changes no case/batch bound and retains unknown charges.
The router's operator configuration may set `paid_ceiling_usd`, an absolute shared
wallet spending limit including all retained charges. Restart applies an explicit
limit transactionally without resetting settled or uncertain spending; live wallet
credit is checked separately on every paid request (a refused request still records the balance it saw).
A paid route whose ceiling cannot cover one more request's hold is also refused at lease time as a
`credit` wait; current holds are under the guard's $1 margin, so with the guard running its stop
usually comes first. An older request waiting only on such routes does not hold back newer requests
for that pool. Without this setting, the
historical first-use qualification ceiling remains fixed across restarts.
An unconfirmed paid request books its whole hold until the provider says otherwise.
The gate passes the call's OpenRouter generation id with an unconfirmed settle, and a
router pass every minute (or `model_router.py --reconcile-once`) settles such a row at
that generation's reported `total_cost` ($0 when nothing was charged), never above its hold,
and one generation settles one row. The report names the route's model or its dated permaslug
(`xiaomi/mimo-v2.6-pro-20260921`); a row already bounded below still settles at its report, and
each pass samples unknown rows at random so ones the provider never reports cannot starve the rest. Older unknown rows are bounded by the account's all-time usage: rows
older than the credit window together cost at most that usage less the provider-reported
costs of settled rows equally old, so their charges are scaled down to that bound and
marked `reconciled`. A bound only ever lowers a charge, and the ceiling is unchanged; a later
generation report replaces the bounded share with the provider's cost, which may be higher but
never above the row's hold.

Poll transport failures do not prove a worker is absent. Cancel or establish that
the old attempt is finished before starting another. Enforce release identity and
attempt deadlines; SEAL must use the versions under which GATES passed. Startup reconciles pool ownership before DBOS recovers workflows. An unconfirmed
create keeps its identity for 15 minutes from its saved intent, then a new create may go ahead and any
late sandbox of an older identity is deleted by its ownership name. A failed create or Boat inventory outage waits
and retries without spending the case's infra allowance, for at most six hours per step, and ADMIT stops after the
batch deadline. A control-side sweep every five minutes deletes owned sandboxes that no record claims and resolves
settled creates. After a normal restore, launch deletes such strays; a quarantined restore still refuses them
(`restore_unclaimed_worker`) after reconcile until its first clean launch, and `restored.json` keeps the reconcile attestation.
Boat ownership uses a versioned 106-character sandbox name containing pool and
case hashes plus the saved create nonce. Inventory resolves case hashes only from
saved pool journals; unknown owned hashes identify orphans, never invented case ids.
The operator `publish` command writes the allowlisted scorecard (codes and numbers
only) to `scorecards/<batch>/<digest>.json` in the object store; it is not yet
called automatically at batch completion.
Ciphertext publication exports the wrapped scope key first, and fetched worker
outputs authenticate before entering immutable storage. Cold backup/restore has a disposable PostgreSQL exercise that preserves grants,
keys, artifacts and release pins. Scheduled backups pause the controller and invalidate only their own restore fence before restarting it;
R2 ciphertext stays in immutable storage. Normal handover requires the source fence.
Lost-source or stale archives restore into a quarantine that cannot execute work
until external ownership and spending have been reconciled. Only the operator's
`reconcile --ownership-reconciled --spending-reconciled` releases it: it works on a
quarantined restore alone, under the state and database locks, refuses while a pool
record is uncertain unless the operator names it with `--cleared-record`, and records the attestation and time before removing the fence.
This path does not claim automatic recovery from unrecorded post-backup spending
and cannot see a stale source controller elsewhere. Legacy lifecycle modules and their obsolete tests have been removed from this
candidate. The clean offline suite passed (151 scripts), along with Linux worker
checks and a disposable PostgreSQL restore exercise. Model-free live checks cover
Boat/R2, Docker, control restart, worker replacement and authenticated checkpoint
reuse. Model access, routing and provider spending ceilings still require live
qualification before production cutover. The practice fixture is not a scientific case.

## Helper machines (G6/G7 built; the rest designed)

Independent seeded gate work can run on short-lived helper workers instead of serially on the case
worker. Built: G6/G7 cheat checkpoints (`run.cheat_runs`, full G6/G7 only, never the advisory early
check), behind `--helper-workers N` (default 0 = today's serial path, untouched) and a
`c.helper_pool`. `factory/durable/helpers.py`: the case worker sends one job per checkpoint (case,
guard and scenario tree digests, bench version, `verdict_code()` release hash, runs, seed, label); a
helper runs `bin/checkpoint` on its own bench copy and returns the checkpoint directory's files
sealed with an HMAC (per-dispatch key) over the exact job. The case worker verifies the seal and the
job echo, rebuilds the directory and reads it with `checkpoint_evidence.read_completed`, the serial
reader, so `verdicts()` and the gate verdict see identical inputs. Any helper fault (death, refused
inputs, bad seal, invalid batch) requeues that job only, once; a job no helper completes runs on the
case worker as today (with its normal infra-retry allowance). At most N helpers at once and N +
jobs leases per dispatch; `case_budget_boundary` runs before each dispatch; each lease, job and
release (with seconds) goes to `helper-ledger.jsonl`. Cheat checkpoints are no-model runs, so no
per-helper money is booked yet. Trust: the seal authenticates the transport (the helper holds the
per-dispatch key), not that `bin/checkpoint` really ran, so helpers are our own workers; the case
worker also requires exactly one `runs`-run batch, `read_completed` cross-checks summary against
records, and the job carries the machine class (vCPU, RAM) and bench worker count, which a helper
of another size refuses and the seal echoes. `durable/helpers.py` is in `VERDICT_CODE` and in G6/G7's
bench dependencies, so editing it re-binds cached verdicts. Same runs, seeds, guards and pass rules; only where they execute
changes.

Transport (`factory/durable/helper_link.py`, off unless runtime config has `"helpers": {per_case, total,
vm_type, min_per_copy, job_timeout_s}`): the case worker holds no Boat credentials, so `SpoolPool` turns
lease/run/release into request files under `~/durable/helpers/<attempt>/req` and waits for answers in
`res`; the control VM's `Broker`, started from `BoatChannel` for GATES attempts only (spool written at
start, relay kept alive by each poll, no new engine step, so recorded workflows replay unchanged), reads
the requests over `boat ssh`, leases each helper through `BoatPool` under case id `<case>-h<k>` (same
release install and verify; `vm_type` may differ), pushes the case tree, runs `helper_link.py run` on it
(the real input check: release, bench, case, guard and scenario digests; then `bin/checkpoint`) and writes
back the sealed result. Helpers are deleted on `release`, when the attempt ends or is cancelled, when
polls stop for `idle_s`, and for every leftover helper record at controller start. A claim by an earlier
controller process is answered as lost, so the case worker requeues. `per_case` and `total` cap helpers;
a refused lease just leaves that work to run on the case worker. Lease and release seconds per helper go
to `<state>/helper-leases/<case>.jsonl`; the case worker also books released lease seconds on the case card
(`helper_lease`), and with `usd_per_hour` in the helpers config, as `helper_lease_usd` beside the model spend,
and a dispatch that would take spend plus lease money to the case limit stops like a model-budget stop. A
helper runs `bin/checkpoint` with the case worker's own `UNBUG_*` env and `agent_timeout` (carried in the
job), and an invalid helper batch is charged to the same `infra-attempts.json` row serial would charge and
runs locally, never on a second helper. `helper_link.py` is in `VERDICT_CODE`. The seal records the
machine class that ran each job (in `helper-ledger.jsonl`). The machine
rule stays "same cpus and RAM as the case worker" unless `min_per_copy` {cpus, mem_gib} asks for at least
that per bench copy. Not built:
G10 tries: one job per strong try behind the same pilot wall, with the
authority for all tries sized up front (founder-approved 2026-11-12) and each helper's lease seconds
and model spend booked to the case line; the result is the AttemptSeries receipt, authenticated the
same way. G5/G15 writing-round checks: same job shape, `plain_and_reference` and the key checks as
jobs. Releasing the first G6/G7 change re-binds G6's gate cache once (`run.cheat_runs` is in G6's
traced source).
