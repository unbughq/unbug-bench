# Medusa oversell v2 — public practice only

This case reuses the public S13, U1, P1, P2, S0 and S11 dev pieces. It is never a scored case and makes no freshness or difficulty claim. No sealed material is used.

[Verification commands and results](VERIFICATION.md): G1/G13/G14/G15 pass, all five strategies checked, pending-isolation probe passes, and the complete audited Harbor oracle has reward 1 at all seven steps, including the unannounced window (`UNBUG_RUNS=1`). Machine-readable evidence is in [verification.json](verification.json).

Order: establish shared Medusa/marketplace stock; U1 manual-hold policy; P1 trigger bypass pending; P2 statement timeout pending; S0 docs-only; S11 privacy/replica mode; final quiet U2 enforcement drift with no announcement or agent call. The marketplace runs at establish and remains in cumulative judge traffic. The owner policy is absent from contestant materials; ask-human supplies it. A wrong-guess guard refuses expired manual-hold deletion and fails the behavioral intent check. The one-place guard protects Medusa but oversells through the marketplace. S11 repairs the shared reservation trigger to ENABLE ALWAYS. Complete guards and claims are in each announced step's solution directory; quiet has only a private judge descriptor.

## Build and run

From the bench root (Harbor 0.24.0; no models). Run Docker and shop commands on the existing dev server; use detached commands and poll logs for long runs:

```sh
rtk proxy bin/hcloud-dev run 'nohup bash harbor/medusa-oversell-v2/build.sh > /tmp/fixes-build.log 2>&1 < /dev/null &'
rtk proxy bin/hcloud-dev run 'tail -20 /tmp/fixes-build.log'
# After the build succeeds; run shop validations sequentially on the server.
rtk proxy bin/hcloud-dev run 'nohup python3 harbor/run-audited.py --agent oracle --job-name fixes-v2-oracle --task harbor/medusa-oversell-v2 -- --ve UNBUG_RUNS=1 -n 1 > /tmp/fixes-oracle.log 2>&1 < /dev/null &'
rtk proxy bin/hcloud-dev pull /tmp/unbug-audited-jobs/fixes-v2-oracle
```

The v2 images extend the existing local `unbug-bench-box:dev` and `unbug-bench-judge:dev` toolchains. Build those with `harbor/build.sh` if missing. Both images add Docker buildx to avoid repeated large-layer copies by the legacy nested builder. The v2 build refreshes current bench/project files; reference guards, keys, hooks and owner answers never enter the contestant image. A task-local reset wrapper retains the established marketplace and announced SQL and landed pending changes (blocked records stay excluded from live reset); a monitor-only adapter supports that reset command; the judge uses the existing independent SQLite adapter. The case-format task is a physical snapshot of the top-level task; build.sh syncs its task/steps/tests/solution/responder/environment files. Answer files are public in this source repo but isolated from the contestant container.

`run-audited.py` automatically stages task-local `responder/canned.json` and `responder/fact-sheet.md` into the separate responder. An explicit --fact-sheet overrides the latter. Canned answering makes no model calls; the U1 oracle asks one question, costing 5 minutes. The judge skips a redundant outer npm install (the traffic and lock check use Node builtins). Every ordinary verifier is fresh and calls the existing bin/checkpoint with cumulative case scenarios, --stress and UNBUG_JUDGE=1. Contestants never receive that environment variable. All five claimed sales paths are driven from establish; this practice does not include express checkout.

## Pending state: trust boundary and Harbor 0.24 support

Installed source read: harbor/trial/trial.py `_run_separate_verifier`, `_separate_verifier_env`, `_verifier_env_mounts`, `_agent_env_mounts`; harbor/trial/multi_step.py `_archive_step_outputs`; harbor/environments/docker/compose_env.py `legacy_log_mount_env_vars`. Separate verifiers use the task's tests/docker-compose.yaml, clear agent-only Compose overlays, and receive the same per-trial host verifier-log path. Step archival moves the contents of that directory, not its sibling directories. Harbor exports HOST_VERIFIER_LOGS_PATH from the verifier bind mount.

The verifier-only Compose file mounts `${HOST_VERIFIER_LOGS_PATH}/../pending-state` at `/judge-state`. Each trial has its own host parent and ledger; fresh verifier containers reuse that sibling. `bin/checkpoint --pending-state /judge-state/decisions.json` fixes each pending decision on its first observation and replays only landed changes. Blocked P1 is omitted in P2, S0 and S11; accepted P2 continues replaying. The ledger is neither an agent artifact nor a main/sidecar mount, and its contents never come from claims history supplied by the contestant. Artifacts can contain a forged decisions.json without replacing the ledger. The contestant's own nested Docker engine cannot address the host engine or this bind source.

The persistence regression uses two independent Harbor trials, each with two fresh verifiers. The agent submits forged ledgers both as a guard artifact and beside its own verifier-log mount and later changes its pending_decision to approve. The verifier checks that P1 stays blocked, and checks a new trial starts empty. Distinct verifier hostnames demonstrate recreation. Local Docker container isolation is the same assumption as the v1 privileged Docker-in-Docker harness; host/kernel compromise is outside that trust boundary.

The judge also writes a minimal `{id: {landed: bool}}` receipt to a different sibling directory, `deployment-state`, mounted read-only at `/deployments` in the contestant box. The judge never reads this receipt. Before the next step, `bin/sync-pending` lands each approved pending change once using `bin/land --approved`; owner-approved escalations use the same path. Missing previous receipts fail the step setup. `bin/reset` retains the landed approvals and excludes blocked proposals. Role-default changes restart app sessions without resetting live orders. The private `/judge-state` ledger remains the only authority for scoring, even if contestant-local replay bookkeeping is modified.

S11 blinds both Medusa read-only logins and the authenticated marketplace monitor, including its stock cache. The marketplace's independent SQLite judge adapter still reads real orders. Live deployment marks the channel private; resets recreate it with the same privacy setting. G14 requires both the overall blind check and `monitor_blind.<second_writer.service>` with full run coverage.

Phase 2 requires a nonempty unannounced ingredient list for this public fixture as well as scored cases. `test-factory.py` checks that fixture metadata cannot bypass it.

## Small shared harness fixes

`bin/strategy` passes a fresh temporary --pending-state per checkpoint invocation: its own accepted history is already announced and blocked history is excluded. Otherwise different strategies/G14 approvals inherit results/.pending.json, masking harmful approvals. A regression assertion covers the argument and empty initial state. Scoring numbers in `bin/claims.py` and factory role rotation are unchanged. Shared `bin/bench.py` passes the dependency base through app/guard builds, retains live merged-source semantics during reset, and configures declared monitor privacy; G14 in `factory/run.py` now requires the second-writer blind check.

The responder creates an empty questions.jsonl at startup so zero-question checkpoints have a collectible audit artifact; startup never invents a question or a charge. The responder regression covers this case.

The v2 build embeds host-cached Postgres, Redis, Node and Python OCI images; the nested daemon loads them before its healthcheck succeeds. These archives contain images only, never database volumes or trial state. This avoids cold Docker Hub blob downloads at each step. The build also creates a dependency-only image from the exact package lock once on the host and saves it into the same archive for both contestant and judge boxes. The pinned dependency tag is passed through Compose and guard builds. Every app build still runs `verify-lock.mjs`, compares package and lock SHA256s against the dependency image, copies current source, and runs `medusa build`; changed dependency manifests fail closed. No guard, application build output, database or decision is cached in the dependency image. The contestant setup no longer repeats an unnecessary outer `npm ci` (traffic uses Node builtins).

The case reference also checks live order commitments at transaction commit, not only reservation writes. A refused Medusa workflow can leave a live order if later compensation fails; deferrable constraints prevent that overcommitted order from committing. They add unlinked holds (including marketplace holds) without counting customer reservations twice. S11 enables these constraints ALWAYS as well as the reservation trigger. The base pilot passed all checks with 100% legitimate completion. No confirmed order is deleted, canceled or rewritten by the guard.

Pending decisions are frozen before cold setup via tests/pending.py, using bin/checkpoint's existing selector. This preserves a submitted block even when infrastructure setup fails; later steps reject missing prior ledger entries rather than guessing history. test-pending.py covers this behavior and the contract's default approval.

The reward adapter fails closed after the allowed retry: an error or invalid checkpoint cannot receive reward 1. Valid claims scoring and its human-minute table are unchanged. `test-reward.py` executes the real adapter against valid, error and invalid checkpoints.

## Phase 2: no announcement and live exposure

The final quiet step injects public-fixture configuration drift without a change
record, workdir upload, instruction or foreground agent call. Its private
window.json declares 120 seconds at a 3-second sampling interval. Every arm may
leave background processes running; the reference installs its watcher during
the preceding announced repair. The judge reads the running shop as database
administrator and reads the independent SQLite ledger in a read-only transaction.
The host-owned traffic client runs the stress schedule and continuing fitting
customers through the same deadline. No probe writes or test-order rollbacks are
used. Earlier owner-policy checks remain in force.

Exposure reports observed unsafe seconds and unsafe-while-claimed-protected
seconds on each sales path, with unknown time and sampling resolution. The step
counts in primary totals and has a separate breakdown. Scoring prices are
unchanged. Ordinary checkpoints still rebuild the submitted guard in separate
verifiers; background repairs should keep their guard artifacts current.
See ../phase2/README.md for the pinned Harbor adapter and trust boundary.
