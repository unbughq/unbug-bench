# Case factory runner

## Runtime ownership

`run.py` composes the factory and retains gate-specific scientific criteria.
Shared execution work has these owners:

| Responsibility | Module | Contract |
| --- | --- | --- |
| Model execution | `model_runtime.py` | Select models and routes, construct isolated CLI calls, and enforce model-call budgets. The runner records durable checkpoints after calls. |
| Case contract | `case_contract.py` | Validate case structure, patch applicability, and ingredient declarations for G1/G14. |
| Gate pipeline | `gate_pipeline.py` | Own gate reuse, sequencing, early review, and concurrent-gate cancellation and joining. Scientific evaluators and completion callbacks are supplied by the runner. |
| Run artifacts | `run_artifacts.py` | Collect run evidence, atomically seal archives, and clean up homes, walls, and bench slots. |
| Benchmark judging | `bin/bench_judging.py` | Evaluate scores and scenario verdicts without runtime I/O; `bin/bench.py` owns services and scenario execution. |
| Shop preparation | `bin/factory_pool.py` and `bin/bench.py` | G3 holds the root bench lock across retirement, main setup and extra-slot preparation. Ordinary checkpoint preparation uses the checkpoint's existing lock. Only explicit fresh preparation reseeds slot zero. |
| Checkpoint evidence | `bin/checkpoint_evidence.py` | Publish an atomic summary and machine receipt; verify the requested run count, ordered records and aggregate counts before returning evidence. Scientific gate criteria remain with the gate. |
| Gate attempts | `gate_attempt.py` | Publish progress, retain private crash diagnostics, retry only operational exceptions when the caller permits it, and propagate budget stops and process interruptions. |
| Recovery decisions | `recovery.py` | Interpret public stop and ledger labels consistently while keeping the restart, holder and adopter policies distinct. Archive authentication and deliberate authorization remain with their callers. |
| Calibrator attempts | `calibration.py` | Own verified receipt reuse, interrupted workspace quarantine, atomic completion and attempt summaries. Model execution is supplied by the runner; gate scoring remains with its evaluator. |

An extra slot's `.prepared.json` binds completed preparation to its seed IDs.
It is not live database proof: every trial still resets the shop and checks the
database baseline. Missing or changed preparation evidence causes fresh setup of
the disposable extra slot before parallel trials begin.

The checkpoint CLI still prints `Checkpoint:` for people and older callers. New
callers use the versioned `UNBUG_CHECKPOINT=` receipt through the shared reader.
A complete batch with invalid runs remains available to factory gates for their
existing verdict rules; strategy execution requires a valid batch. An operational
failure must never become evidence that a case is hard or a guard is correct.

Budget continuation flags propagate out of model-call and early-probe scopes even
when a call stops. Only a completed, atomically recorded calibrator attempt counts
toward the requested tries; uncommitted workspaces are quarantined on resume.

Run offline checks from the repository root:

```sh
python3 tests/run.py factory bench integration
```

See [the test guide](../tests/README.md) for all suites, individual tests, and the
explicit live-stack probes. Regression tests are grouped under `tests/`; runtime
modules remain beside this README or in `bin/`.

Deployment tests build a hermetic synthetic release with explicitly bound hashes;
they do not depend on historical release artifacts. Pure judging and model-call
tests live in `tests/bench/` and `tests/factory/`; integration tests retain runtime coverage.
Offline checks do not qualify a worker release or prove Docker execution. New
runtime files must be included in newly qualified source releases; existing
holder and deployment pins are not bypassed. Real-worker validation uses the
public gate smoke described in `results/infrastructure/2026-10-24-gate-smoke/notes.md`.

See [efficiency implementation status](IMPROVEMENTS.md) for the October 20 recovery,
admission and repair changes, their verification boundaries, and remaining rollout work.

Builds sealed scored cases (FACTORY.md) on throwaway boat.dev VMs. One VM builds one case:
builder phase, then gates G1–G15 in FACTORY.md execution order (stop at the first failure), then G12 seal.
The founder (and any Claude session) sees only the scorecard and the archive hash.

Factory bench parallelism is opt-in: `python3 factory/run.py ... --bench-workers 2`.
The default is `1`, preserving the existing serial bench, exam, and Harbor behavior.
Each additional instance has its own Compose project (`unbug-factory-1`, ...), Postgres
volume, Redis, app ports (9100/9101, ...), guard image tag, seed IDs and
`results/factory-slots/<slot>/` evidence. Slot zero uses the original bench.
G3 prepares the extra instances; G12 gathers their evidence and wipe removes their
volumes/images. Bench subprocess groups are stopped on timeout before sealing/wiping.

Runs within G4–G7 and calibrator checkpoints, G6 negative probes and G11 guard reruns can
run concurrently. Run numbers, traffic options, seeds and run counts are retained;
the final fake-pass run stays on slot zero for its post-traffic database diff.
The two G10 model roles run concurrently by default when isolation is supported;
`--no-concurrent-roles` retains serial calibration.
Strategy/silent-window steps and their information walls stay serial.
Legacy inventory services stay serial unless they adopt the endpoint isolation
contract below; undeclared hardcoded host ports must never be guessed or rewritten.


`--concurrent-roles` enables strong/easy G10 calibration on Linux (enabled by default).
For Boat default 8 GB, use `--bench-workers 2`; larger machines require separate measurement.
The users `pilot-strong` and `pilot-easy` have separate homes and live bench instances
(slots 0 and 1, APIs 9000/9001 and 9100/9101). Each role's attempts remain sequential;
its resets and checkpoints use only its own instance, without bench-worker fan-out.
The copied contract and pilot prompt name that instance's endpoints. UID firewall rules
allow its own local APIs and DNS, reject other local/container/private-network APIs,
and leave public provider access available. Setup fails closed if iptables/ip6tables
cannot install these walls. Seal, wipe and resume cover all three pilot identities/homes;
resume also removes the old firewall rules before recreating users.

G3 prepares at least two slots when this option is usable. This uses two live shops,
including the original bench; it does not silently reserve a third shop on an 8 GB VM.
Base scenarios with legacy inventory services retain serial calibration. A resumed
run whose budget has not yet been reopened also retains serial G10,
so two roles cannot reset the resumed ledger at once. Serial calls retain the
whole-session budget lock. Concurrent calls instead lock each
ledger transaction; any terminal budget stop cancels peer model processes, and workers
are joined before sealing. Run counts, seeds, solve rules and scorecard fields stay the same.

G8/G9 remain after the mechanical gates: their shared review prompt requires checking
traffic, discoverability in the running system and the built box. Those observations can
change while mechanical gates reset/rebuild the app, so the reviews are unsafe to overlap.
G11 waits for both calibrators' passes. Reviewers, builder/attacker and strategy gates remain serial.

Expected savings are up to half of G10's model time when role durations are similar
(three paired sessions instead of six sequential sessions), reduced by setup and the
loss of checkpoint fan-out within each role. End-to-end savings are unmeasured. Local
synthetic tests verify overlapping emitters, exact shared usage, peer cancellation,
separate identities/homes/slots and serial fallback. A cpx42 Linux smoke test with real
UIDs verified private case/peer homes, own local API access, blocked peer APIs and exact
concurrent usage, without models or Docker. That original test did not exercise Medusa.
Full AI calibration and UID firewall behavior through Docker NAT remain unverified.
That test server (170954122) was deleted; the provider confirmed it was absent.

For an 8 GB cpx32, use two instances: the existing per-instance container limits
are 3,456 MiB each, so three instances' combined limits exceed RAM.
Eligibility also reads every service's finite positive `mem_limit` from merged Compose
configuration and Docker's daemon-reported `MemTotal`. Docker containers on Boat live
outside the SSH runner's user.slice, so that unrelated slice cap is not their allowance.
All concurrent shop limits must fit,
leaving 768 MiB for OS/runner overhead; unknown or excessive limits fall back to serial.
Two standard shops plus a 64 MiB service each fit a 7,941 MiB guest; a missing or 4 GiB
service limit disables concurrent testers and checkpoints. No limits are raised.
Replicated/scaled services stay serial; the eligibility accounting assumes one container per service.
G3 lowers an excessive requested worker count before preparing extra databases; later
gates use that effective count, reported as `bench_workers_effective` in the scorecard.
Idle extra instances start with their databases stopped. If a heavier scenario falls
back to serial, its idle peers are stopped too; factory resets restart only their own
Postgres/Redis. Slot zero's final database remains available for fake-pass inspection.

Inventory service isolation is explicit. Each scenario's service entry declares
`host_ports: [9010]` (unique integers 9002..9099; `[]` for an internal-only service).
Its hooks use `ctx.serviceURL("service-name", "/path")`, with an optional third
argument selecting another declared port. Slot zero retains the original ports;
slot N publishes port + 100*N. The runner validates loopback-only TCP publications,
project-scoped plain local volumes/bridge networks and containers, and rejects host binds,
custom storage/network drivers, driver options and external
resources. Compose projects, service guard images, adapters and state stay separate.
The copied pilot contract maps documented endpoints, and UID walls allow only its
own app and declared inventory-service ports. The public S13 fixture demonstrates
the contract. Sealed old cases are not modified automatically.

`python3 tests/factory/test_inventory_ports.py` checks endpoint routing, publication
overrides and fail-closed legacy behavior with synthetic fixtures and no model calls.
Add `--compose` to validate the generated overrides using Docker Compose without
starting containers. Parallel AI testers still run in G10, after scripted gates;
overlapping them with scripted checks needs a separate scheduler and more live shops.

Public Boat smoke measurements on 2026-10-18: two S0 reference runs took 59.10 seconds
serially and 32.14 seconds with two workers; two S13 service runs with two workers took
40.49 seconds, with no errors or OOMs. Marketplace ports 9010/9110 had independent
orders, and resetting slot 1 preserved slot 0's service orders. These are scripted
reference measurements, not AI tester or end-to-end factory timings. Evidence is in
`results/infrastructure/2026-10-18-parallel-testers/`.
`python3 tests/factory/test_parallel.py` checks scheduling, seeds, serial defaults and timeout
cleanup without Docker or model calls. The scored exam does not enable these workers.

Measured on 2026-10-17 on two separate cpx32 servers in fsn1, started together with
`--dry-run --runs 10 --scenario-runs 3 --seed 17017`, using one versus two workers.
No model calls were made. Observed wall time including seal/wipe was **59.1 versus
54.0 minutes** (the runner's pre-seal scorecards report 58.8 versus 53.2).
Per-gate minutes, serial versus parallel: G1 0.1/0.1, G3 0.5/1.4, G4 4.3/2.8,
G5 53.8/48.7. G12 passed both round trips; it is included in observed wall time
but not separately timed by the runner. All 110 captured run verdicts matched.

Both normal dry runs stopped at G5: reference 10/10, scenario keys 27/30.
The same existing failures occurred in both: S11/reference expects an express-checkout
path absent from its standalone checkpoint; S7a/repaired and S7b/repaired resolve through
`find_guard()` to S11's example because example names are searched globally.
The keys and lookup behavior were preserved. A complete passing factory case, later
strategy gates, model/pilot execution and the scored exam remain unverified by this run.

To exercise the remaining changed scheduling paths, fresh fixture contexts ran G6,
G7 and G11 directly on both servers at the same time, with the same counts and seeds.
These are **isolated gate timings**, not a factory run that bypasses G5 in production:
G6 14.5/10.5 minutes, G7 16.1/10.7, G11 7.7/6.5. Both passed: cheats 0/20;
fresh-seed plain 10/10 broken, reference 10/10 solved, cheats 0/1; fake pass 1/1 survived.
All 163 captured verdicts across the normal and isolated checks matched (110 + 45 + 8).
The negative probes also passed their per-run assertions on both servers.

Two workers peaked at 2.9 GiB used host RAM and about 100% CPU; mean CPU was 57%
in the normal run and 65% in the isolated checks, versus about 41% serially.
All requested local checks passed: `test_run.py`, `test_budget.py`, `test_resume.py`,
`test_v2.py`, and `tests/bench/test-launch-guards.py`; the new `test_parallel.py` and existing
`tests/bench/test_pending.py`/`tests/bench/test_strategy.py` also passed. No heavy Docker ran on the Mac.
The snapshot clones contained a stale `unbug-bench-seed` container; it was removed only
on these test VMs before the paired runs. The snapshot was not rebaked.
Public fixture reports, sampling data and reproduction wrappers are retained under
`results/remote/factory-parallel-20261017/` (ignored by git).
Both created servers (170901450, 170901452) were deleted after collection; provider
queries confirmed both IDs were absent. No other server was modified.

| File | What it is |
|---|---|
| `launch.sh` | Host: `<founder identity> \| factory/launch.sh N --source port\|hunt\|plant [--ttl-hours 4] [--max-spend 3] [--stall-minutes 20] [run.py options]`. Forks N VMs from `bench-env`, starts `run.py` detached, monitors completion/progress, collects sealed results and deletes every VM, including on errors or signals. |
| `collect.sh` | Host: `factory/collect.sh <sandbox-id>`. Copies only `*.age`, `*.scorecard.json`, `*.scorecard.txt` (and a dry run's throwaway key) into `unbug-bench/sealed/` and prints the scorecard. |
| `run.py` | VM: the runner. Standard library only. |
| `prompts/` | Generic role instructions: `builder`, `attacker`, `reviewer` (modes `case`, `pilot-failures`), `pilot`. They restate FACTORY.md and name no bug, app area or promise. |
| `test_run.py` | Local check of G1 on the dry-run fixture (no Docker): `python3 tests/factory/test_run.py`. |

## Statement dedup

Before construction, the writer returns only `statement.md` (3–6 sentences). The runner
uses the easy-calibrator route, from a different family than the writer, to compare it
with its complete shared reservation snapshot. Unavailable or stale admission evidence
stops construction. A duplicate rejects the candidate before construction. The selected
statement cannot change during later repairs. Scorecards contain counts, duplicate case
IDs and admission status, never statement text or the comparison's reason.

Once, run `<founder identity> | bin/setup-secrets statements`, then stage the generated
public `factory/statements-recipient.txt`. Until then that file is empty. This adds a
separate `statements-key` to the encrypted secret bundle; rerunning keeps the existing
key. Launch pushes it through `bin/push-secrets` into VM RAM, alongside API credentials,
and copies local `sealed/*.statement.age` ciphertexts into `~/statements/`. Only the VM
opens those statements. Missing keys or an unattested snapshot blocks admission. Sealing writes
`~/sealed/<case-id>.statement.age` to the public statements recipient; collection brings
that ciphertext back. Launch selection with `--statement-only`, collect each stopped
worker, then run `factory/statements-round.sh`. Its default discovers parked Hetzner
workers; Boat requires `--provider boat --worker-id ID`, repeated for every selected
worker. The coordinator imports collected history and serializes reservations in stable
case order, so each candidate compares against earlier pending candidates as well.
Only ciphertext and hash-bound admission metadata are delivered to each worker; every
uploaded file is verified before its snapshot replaces `~/statements/`.

Statement delivery emits `ready_for_authorized_resume` and leaves workers stopped.
Automatic admission resume is not wired into the launcher. Resume through an approved
launcher preserving the original source, rotation slot, models, efforts, seed, limits,
and cumulative usage ledger; remove `--statement-only` for construction. The registry
does not authorize replacing budgets or extending a worker's lifetime.
The founder identity is never sent to factory VMs.

## Launch and lifetime guards

Model keys: run `bin/setup-secrets` once (Claude token, a dedicated Codex login, OpenRouter
key, age-encrypted to the founder key at `~/.config/unbug-bench/secrets.age`). Launchers read
the founder identity on stdin, decrypt the keys in memory and push them to the VM's RAM
(`/dev/shm/secrets`) with `bin/push-secrets`; the identity itself never reaches a factory VM.
Boat's paid AI relay is off (2026-10-16).

Cloud: Hetzner by default since 2026-10-17 (`bin/hcloud-boat`, cx33 EUR 0.016/h, then cx43, in
nbg1/fsn1/hel1); `UNBUG_CLOUD=boat` uses boat. Servers start from the `bench-env` snapshot made by
`bin/hcloud-bake` (re-bake after bench changes the factory relies on), sit behind an SSH-only
firewall, and carry an `expires` label. Hetzner bills until deletion even when powered off, so
`bin/hcloud-sweep` (launchd, every 5 min, `--install`) deletes any expired `unbug-bench` server;
it never touches unlabelled servers. An exam case runs on one VM, so every arm and try of a case
shares one machine type; `results/spend/hcloud-hosts.jsonl` records each server's type and location.
With Hetzner the spend cap uses the same $0.036/h bound, and the finish record prices billed hours.

`factory/launch.sh 2 --source port` budgets 3 h runtime + 1 h margin per VM (4 h TTL,
$0.288 maximum VM cost for two). `--ttl-hours H` overrides it; `--max-spend USD`
defaults to $3 for the whole invocation. The launcher refuses a batch exceeding either
the cap or the current `boat billing --json` credit balance. `bin/boat-spend` prints
dollars left. Before/after balances and their actual account-wide spend delta are saved
in `results/spend/<timestamp>-<label>.json`; concurrent account use affects that delta.
These estimates cover VM time at $0.036/hour, not model/API charges.

Every exit (including Ctrl-C and TERM) attempts collection before deletion. A failed
copy still deletes the VM: uncollected artifacts and any unfinished plaintext work are
lost. `--no-snapshots` means stopping is also destructive. A paused runner is subject
to the same watchdog: no change to `~/work` or the continuation ledger for 20 minutes
(`--stall-minutes N`) causes collection and deletion. All VMs in a batch are checked
concurrently each cycle and between provisioning VMs; completed VMs are collected promptly. Failed SSH polls are cut off
after about 10 minutes. Exit checks warn loudly about any created VM still alive.

`bin/exam-launch` uses the same guards on one VM, with a TTL of
`1.5 h × arms × tries + 1 h` unless overridden, and watches `~/jobs`, `~/exam-private` (the actual job tree), and `~/exam-out`.
`--private` and `--out` overrides are monitored too.
SIGKILL, host failure and an API outage cannot be cleaned up by a shell trap; the
provider TTL remains the final backstop. Deletion failures are retried at exit and
reported, never presented as successful cleanup.

For an offline check, run `python3 tests/bench/test-launch-guards.py`. It uses an executable
fake `boat` under a temporary directory and never calls boat.dev. `BOAT_CMD=/path/to/shim`
overrides the CLI (and bypasses the direct-API naming helper). Polling defaults to
`BOAT_POLL_SECONDS=120`, `BOAT_STALL_MINUTES=20`, `BOAT_UNREACHABLE_SECONDS=600`,
and `BOAT_COMMAND_TIMEOUT_SECONDS=120`; tests shorten these intervals. A command
that exceeds its timeout is killed locally, followed by cleanup; its remote outcome
may be unknown. The default CLI transport remains `zsh -ic 'boat "$@"' zsh`.

## Measurement round

`bin/exam-round` wraps `bin/exam-launch`: one active cx33 per case, up to 12 cases
at once by default (`--parallel N`, maximum 14 = (64 shared vCPUs - 8 office vCPUs) / 4).
Other Hetzner quotas, such as primary IPs, still apply. No office server is accessed.
All arms/tries of an uninterrupted case share its VM. Results are collected and the
VM deleted before a quota reset wait; a retry/resume uses a fresh cx33 of the same type.

Create a JSON file, for example `round.json` in the repo root (archive paths are
relative to the JSON file). The full round lists all 24 sealed archives:

```json
{
  "accounts": ["claude-token", "claude-token-2"],
  "arms": ["A", "B", "C", "C0"],
  "tries": 3,
  "cases": [
    {"archive": "sealed/case-01.tar.gz.age", "account": "claude-token"},
    {"archive": "sealed/case-02.tar.gz.age", "account": "claude-token-2", "tries": [1, 2]}
  ]
}
```

Use `"accounts": ["claude-token"]` (the default) for one subscription. Cases are
pinned round-robin in listed order; optional `account` fields must agree. A case's
optional `tries` list preselects a subset before scoring. Pins and archive hashes
are saved before any launch in `results/exam-round/<round-file-stem>/manifest.json`.
Keep the JSON unchanged when resuming; a changed frozen input is rejected.

```sh
# Provision the optional second subscription with the existing encrypted-bundle updater:
cat /secure/founder-identity | bin/setup-secrets claude-token-2
# Start, or resume with the identical command:
cat /secure/founder-identity | bin/exam-round round.json --parallel 12
# Offline check (no cloud, Docker or model calls):
python3 tests/bench/test-exam-round.py
```

The round runner reads the identity once, holds it only in memory, and pipes it to
each launcher. The selected secret is checked by `push-secrets`, then copied in VM
RAM to the canonical `claude-token` filename expected by all existing trial wiring.
No identity or secret contents appear in the manifest or launch logs.

Each launch has its own directory beside the manifest, containing `launch.log`,
collected number-only scorecards and encrypted jobs. Resume skips every collected
case/arm/try and every trial marked missing. Raw-archive hashes are checked before
marking a trial collected. Other launch/collection failures return nonzero and
require inspection, then another invocation to resume. Ctrl-C/TERM lets launchers
finish their collect/delete traps; after host failure, wait for existing launchers
or the provider TTL to finish cleanup before resuming.

The runner polls only sanitized `claude-meter.jsonl` metadata over labelled-server
SSH, plus meter summaries in collected scorecards. The manifest's `meters` shows
latest observations per account. At 5h utilization >= 0.85 or 7d >= 0.95, new case
starts on that account wait for its reported reset(s); running trials continue.
Unknown reset times block new starts until fresh meter evidence supplies a reset
or clears the condition. Missing utilization before an account's first observation
permits starts; this is pacing from the latest known meter, not a quota guarantee.
A rejected/HTTP-429 trial exports no score, ends that case's current launch, and is
rerun in full after reset with the same pin (two reruns maximum, then missing).
The command returns nonzero for missing trials, launch failures or interruption.

## What runs on the VM

1. Preflight: install `age` if missing; prepare a fresh seeded shop under the
   existing bench lock before model admission, then hash the bench files. Fixed
   factory containers are removed before Compose down deletes their old volumes.
   Startup command failures retain a bounded diagnostic in encrypted
   `logs/runner.log`; the public card contains only that relative evidence pointer.
2. Builder phase (`--rounds`, default 1): the rotation slot's writer builds
   in `~/work/<case>/case`. A different family stress-tests: writes cheat guards and scores them
   with `bin/checkpoint`, re-checks plain app, reference and keys, searches for the bug, reviews
   fairness, writes writer-fixable `blocking` findings separately from `unfinished_validation`.
   Unfinished validation stops unresolved without a writer call or stress pass. G1 runs after
   each builder pass; valid cases then receive early G15/G3/G4/G5 and one run of each saved
   `guards/cheats/*` before stress. Saved-cheat checks share G6's checkpoint/verdict mechanism,
   have a 30-minute aggregate wall-time bound and use no models; they do not grant a full G6
   receipt. Reopened cheats return to the writer, execution failures stop unresolved.
   The final builder pass also receives early checks after G1; it still stops stress unresolved.
   Stress completes only with a complete review, no case blockers or unfinished validation,
   and completed diagnostics and independent early reviews.
3. Gates. "Broken" and "solved" are per run of `bin/checkpoint --scenario <case>/base --stress`:
   broken = a `promise_paths` path violated or a `promise_checks` check false (both listed in
   `case.json`); solved = clean run, no promise path violated, every judge check true.

| Gate | What the runner does |
|---|---|
| G1 | Parts present, promise ≤ 300 words, leak words absent from contestant-visible files, every `app.patch` applies (`git apply` on a copy of the pinned app), Harbor task parses, bench file hash unchanged, answer key and surprise counts. |
| G2 | `freshness.jsonl`: ≥ 3 web + ≥ 3 GitHub builder searches, ≥ 2 attacker searches, no hit. |
| G3 | `docker compose down -v`, then `bin/setup` on fresh volumes. |
| G4 | `bin/checkpoint` with `guards/none`, `--runs` (10): at least one broken run, no unclean run. |
| G5 | Reference solves every run, legitimate completion ≥ 95%; then every scenario's `expected_judge` guard through `bin/checkpoint` (`--scenario-runs`, 3) must give `key_consistent`. |
| G6 | `guards/refuse-all` and each `guards/cheats/*` on the case traffic: no solved run. `bin/verify-negative` must exit 0. |
| G7 | G4, G5 (reference) and G6 (seeded cheats) again with a new seed. |
| G8, G9 | Each reviewer model reads a copy of the case and writes `fairness` and `realism` votes; all must approve. |
| G10 | Each strong/easy calibrator gets `--pilot-tries` (3) fresh blind base-guard tries as Unix user `pilot`, with separate workspaces and CLI state. Each guard gets `--pilot-runs` (5) checkpoints. Zero strong solves labels the case hard without rejecting it; easy must solve fewer than all tries. Strong all-solves and easy zero-solves are accepted. |
| G13 | After G5: frozen-first-fix must fail a later step. |
| G14 | Structure checked in G1; after G13, wrong-guess/reference intent checks, one-place/second-writer path, previous-reference pending approvals and blind failures are driven mechanically. |
| G15 | Safe/correct honest-reference must beat each lazy strategy by unsafe/wrong steps or ≥30% human minutes. |
| G11 | `bin/fake-pass-check` on every calibrator pass (its `runs` findings ignored, see gaps) plus a fresh-seed re-run on the case traffic. |
| G12 | Bench evidence written during the run and the agents' session stores are moved into the work dir; `tar \| age -r <founder key>` streams to `~/sealed/<case>.tar.gz.age` (no plaintext tarball on disk); sha256 printed. Then `shred -u -z` on every plaintext file, the pilot user deleted, guard image, database volume and build cache removed. The scorecard records how many plaintext files are left. |

Models: one explicit model per role; automatic fallback is disabled. The prefix picks the driver:
`codex/<model>` runs `codex exec --json` (codex-cli 0.162.1, ChatGPT subscription through the VM's
`~/.codex` config and auth, reasoning effort high, hosted web search off, multi-agent off);
`claude/<model>` runs `claude -p --output-format stream-json --verbose` (Claude Code 2.1.299,
installed by the runner into `/tmp/factory-claude-cli` if missing; Claude subscription
through boat's `CLAUDE_CODE_OAUTH_TOKEN`/`ANTHROPIC_BASE_URL`, effort high, tools limited to
Bash/Edit/Read/Write, so no web and no subagents); anything else runs through OpenCode. Any other
CLI version stops the run. API-key variables are removed from both subscription CLIs' environment.
Each codex/claude call gets a fresh config directory (copied `config.toml` + `auth.json` for Codex)
and no session files; the directory is shredded after the call, the stdout transcript is sealed.
Roles use factory/rotation-3writers.json by default (eight slots; default slot 1). The four principal roles
While OpenAI refuses case writing (2026-10-16), writers are Claude 3, MiMo 3, Muse 2; GPT only
calibrates and reviews. `--rotation-table rotation.json` (four writer families) refuses GPT as writer or
stress-tester until its `refused` entry is removed after Daybreak approval.
use four different families. Explicit --builder/--writer, --attacker/--stress-tester,
--strong-calibrator (--pilot alias) and --reviewer1 override their slot. --reviewer2 adds an
optional reviewer. --easy-calibrator defaults to opencode/glm-5.3-flash-free (OpenCode's free GLM 5.3 Flash, zero-retention per
the Zen privacy list, free "for a limited time": if it disappears, pass opencode-go/glm-5.3-flash). MiMo runs on OpenRouter since 2026-10-18 (the
Go plan's MiMo allowance ran out; switch the slot tables back to opencode-go/mimo-v2.6-pro when it has room). Muse Spark 1.3 Contributor runs on OpenRouter (`openrouter-key`,
required; paid-training consent on): OpenCode Go removed it on 2026-10-17. Each role has a --<role>-effort flag;
scorecard roles records exact IDs and effective efforts, including provider-default when
no effort variant is defined. Opus/Sol use high and Muse uses xhigh in the table.
Strong calibration permits Claude under the same Unix information wall as Codex/OpenCode.
Claude's pinned executable is installed in /tmp/factory-claude-cli (no session data there),
so the isolated user can execute it while the runner's home remains private.
`python3 factory/run.py --probe codex/gpt-6.1-sol --probe claude/claude-opus-5-5` makes one
"reply READY" call per model through the same code path and prints the ledger (no case, no gates). Go's request cost is from its plan allowance, so
`--max-cost` there is a runaway guard, not cash. The factory config prices Muse Contributor for
OpenCode v1.19, which does not know it. A provider, quota, pricing-observability, or usage-limit
error (including Go's weekly/5-hour limits and OpenRouter HTTP 402) stops the case.
Codex cybersecurity refusals and Claude usage-limit errors also stop immediately, with the
provider/model in `terminal_stop`. Two rate-limit/429 notices without token progress stop.
`--no-progress-minutes 45` (`FACTORY_NO_PROGRESS_MINUTES`; 15 stalled a MiMo writer mid-test-run on 2026-10-17) kills a call's whole process group
if stdout/stderr is silent, even if the CLI closed its output pipe. The existing four-hour
`--agent-timeout` remains a hard cap. `--max-zero-tokens 3` stops consecutive zero-token
responses (deduplicated; nonzero usage resets the streak, which spans role invocations).
Contributor requires allowing paid model training in the OpenRouter account privacy settings.

`--max-cost 5` limits observed continuation cost of priced (OpenCode) events only, for non-factory
runs, audits and the exam owner. A batch job (`--batch-release-sha256`) has no paid cap: its job money
channel's cumulative commitment bounds every call, and `--max-cost` is ignored. `--max-role-calls 250`
limits observed main model responses per role invocation, and `--max-total-calls 700` limits them
across the run. Founder-approved 2026-10-16 defaults budget roughly 200 builder/attacker
responses plus 100 for fixes/review/pilot (the prior three-round case used ~490 calls).
Raise these flags for larger runs. `--rounds 1`, `--pilot-tries 3`, `--runs 10` screen cases;
**the scored exam still uses 30 judge runs** (FACTORY.md decision 2026-10-16).
Subscription calls have no per-call price: Codex reports tokens per turn (recorded at
cost 0), Claude Code reports list-price `total_cost_usd` per run (recorded as `list_cost_usd`, not
counted toward `--max-cost`); both events are marked `priced: "subscription"`. Codex does not report
per-response usage, so its calls are counted live from completed tool-call and message items (parallel
tool calls count separately, so the limits stop early, never late); Claude calls are its distinct
assistant message ids. A Codex turn or Claude run that ends without its usage event stops the run
(`missing_usage`); `turn.failed` and a Claude result with `is_error` stop it too.
Cost and calls are recorded in `~/sealed/<case>.continuation-budget.json`. Limits are checked
as responses arrive: concurrent in-flight responses can overshoot, and invisible auxiliary calls are
not a provider-side dollar guarantee. Task delegation is disabled. Automatic compaction is on (founder, 2026-10-17): without it a MiMo writer re-read up to ~500k tokens per step and ran out its 4-hour window; whether compaction calls appear in the ledger is to be confirmed on the first run (the provider dashboards show them either way).
An OpenCode response with nonzero tokens and zero reported cost stops the run rather than treating it as free.
An explicit session title disables automatic title-model requests. For this continuation,
`FACTORY_OPENCODE_BIN=/opt/factory-cli-v1/opencode` pins official OpenCode v1.19.0:
v2.0.26 omitted the final usage event in the synthetic route probe. The v1 data directory
is isolated under `~/.local/share/factory-opencode` to avoid v2 database incompatibility.

Resume preserved work with `--resume <case-id> --resume-bench-sha <trusted-clean-template-sha>`.
The runner verifies the bench before any model call, preserves old transcripts, and reruns
all gates. The continuation ledger excludes legacy Argon spending. Explicit `--resume`
archives the previous terminal reason and clears the zero-token streak, preserving every
call/cost/event. An exhausted cost/total-call ceiling still stops before spawning a model;
raise the relevant flag for a pre-approved continuation, never erase usage to bypass it.

Terminal stops write `<case>.scorecard.json`/`.txt` with `terminal_stop` and resume metadata,
try to seal `<case>.checkpoint.tar.gz.age` (including `continuation-budget.json`), and always
write `~/sealed/DONE`. There is no PAUSED wait: the launcher collects the checkpoint and
scorecard and deletes the VM. Resume needs the restored checkpoint work on a new sealed VM
and a trusted clean bench fingerprint; the runner restores its archived ledger automatically.
Local work is retained on a stop until VM deletion. If encryption fails, the scorecard records
`checkpoint_error` and DONE still triggers retirement; that work cannot be recovered after
deletion. Nobody should decrypt a real case on the founder's workstation. The one exception is streaming:
`<founder identity> | factory/launch.sh 1 --restore <case-id> --source <same> --rotation-slot <same>` decrypts
`sealed/<case-id>.checkpoint.tar.gz.age` in a pipe straight into a new VM's `~/work`, restores the ledger from the
collected scorecard and starts `run.py --resume` with the recorded bench fingerprint.
Do not resume a stopped legacy controller with old model defaults; replace it with the
budgeted runner after verifying preserved work and the trusted bench fingerprint.

## What the founder sees

Stdout of `run.py` is the scorecard only; every other byte (bench output, transcripts) goes to
the sealed log. Example shape (values from the dry run below):

```
<case-id>  sha256:<hex>
gates: passed G1,...; FAILED Gn; skipped ...
reviewers: fairness 2/2 approve, realism 2/2 approve
plain app broke the promise k/n   reference fix n/n   cheats 0/m passed   scenario keys k/k
calibrators: strong solved k/3; easy solved j/3 (model IDs in JSON)   fake pass: k/k survived
surprises: 3   scenarios: 11   provenance: 2   source: port   builder rounds: 2
wipe: {"plaintext_files_left": 0, ...}   wall: <min> min
```

No promise text, app area, bug or surprise appears. `<case>.scorecard.json` has the same
fields plus roles (pinned model/effort/family), rotation_slot, gate_results, failed_detail,
per-gate minutes and the G7 re-run numbers. Strategy step details stay in the sealed archive.

### Calibration diagnostics (2026-10-18)

A stopped G11 case can be restored with `factory/launch.sh 1 --restore CASE
--audit-g11 --source port` (or its recorded source). This invokes only its recorded
independent non-Claude reviewer, not a builder or any gate. It caps the audit at
20 minutes, 80 model calls and $0.50 incremental observed spend within the passed
cumulative ceilings. Copies of the case/fixes/evidence and their originals are
fingerprinted; edits invalidate the verdict. A separate `g11-review-CASE` encrypted
archive and fixed-label scorecard are collected. This diagnostic never approves
the original case or overrides G11. Restoring a retired VM uses the usual local
founder-key stdin pipe; keys and detailed findings do not enter this thread.

Continue a stopped intact review with `factory/launch.sh 1 --restore-review CASE
--source port` (or its recorded source). This restores only the encrypted audit,
including notes, prior transcripts and reproductions. It checks the saved input and
bench fingerprints, keeps the recorded reviewer and cumulative usage, and uses only
the remaining original audit dollar/call allowance. A continuation gets another
20-minute attempt; it does not run the builder or gates. Prior verdicts are preserved
as history and cannot stand in for a new report. The normal local key stdin pipe is
required to stream the archive directly into its new sealed VM.
Legacy audits also restore the independently verified original case as an input
baseline while upgrading their input fingerprints to the framed version; neither
archive is decrypted onto the host or used to rebuild the case.

`calibrators.strong/easy.diagnostics` exposes fixed labels and integer counts only.
`calibration_progress` also records a completed role if the other role later stops.
The sealed attempt records keep the supporting details; no check names, paths, tool
output, fix text or narrative reason is copied into these diagnostic fields.

| Field | Fixed labels | Meaning |
|---|---|---|
| `stop_reasons` | `completed`, `time_limit`, `call_limit`, `unrecorded` | How the model session ended. A cap does not imply its submitted fix failed. |
| `outcomes` | `solved`, `no_fix_submitted`, `fix_failed_some_runs`, `fix_failed_all_runs`, `fix_failed_runs`, `run_error`, `unknown` | What judging observed. `fix_failed_runs` is the older format, which lacks the partial/total split. |

Every completed attempt has one stop label and one outcome label. `run_error`
does not assign blame: a contestant's broken fix and a harness fault can both cause
execution errors. Tool calls can also fail during an otherwise successful repair;
those are not automatically harness faults. `calibration_interruptions` records
fixed stop labels such as `provider_limit`, `model_process_error` and
`usage_monitor_error` when a model call aborts. These interruptions retain the
existing stop/resume behavior and do not become scored failed attempts.

Legacy solved/unsolved results remain usable, but most old stop reasons and the
partial/total run split were not saved. Report `unrecorded` or `unknown`; do not
infer a timeout from elapsed time, or infer a harness fault from zero solves.

These are descriptive observations, not causal labels for difficulty. Determining
whether difficulty comes from system interactions, obscure requirements, or the
harness needs an independent reviewer behind the seal to examine the evidence.
The existing `pilot-failures` reviewer rubric distinguishes fair failures from
undiscoverable requirements and bench errors; it is not currently invoked by G10.
No such review is claimed by these counters, and they add no model calls.

Calibration currently gives a blind, single base-fix session, not the full exam
sequence; `calibrate()` does not wire in the owner responder. In the actual exam,
both the baseline and Unbug get the same cases, budgets, tools and responder within
each model family. Difficulty alone favors neither arm. These diagnostic labels
do not change scoring, gates or case selection. Any harness invalidation must use
the same pre-agreed rule across arms; do not drop cases because one arm failed.
This change instruments factory calibration, not the exam arms. Existing live VMs
are not modified; new launchers upload this code on their next explicit launch.

## Dry run

`--dry-run` makes no model call. The practice case (dev only) is laid out in the case format
(base = `scenarios/dev/S0-null`, reference = `guards/reference`, scenarios = the other dev
scenarios, Harbor task = `harbor/medusa-oversell`). G1 runs without the content checks (the
fixture has no surprises, fact sheet or provenance). G2, G8, G9, G10 and G15 are skipped; G14 reports absent v2 ingredients. G13 still runs. G11 uses the
reference guard as a stand-in pilot pass. G12 uses a throwaway age key generated on the VM
(never the founder key), then decrypts, extracts and `diff -r`s the archive against the work dir
before shredding.

`factory/launch.sh 1 --dry-run --runs 3 --scenario-runs 1 --ttl-hours 4`

## What was verified (2026-10-14)

Dry run on one boat VM (`bench-ready` fork, 4 vCPU/8 GB), started with `launch.sh 1 --dry-run
--runs 3 --scenario-runs 1 --ttl-hours 4`, runner wall time 51.7 min:

| Gate | Result | Minutes |
|---|---|---|
| G1 | pass (structural; content-count checks off for the fixture) | 0.1 |
| G3 | pass: `down -v` + `bin/setup` | 1.4 |
| G4 | pass: plain app broke the promise 3/3 | 1.2 |
| G5 | pass: reference 3/3; scenario keys 25/25 consistent | 16.9 |
| G6 | pass: cheats 0/20 passed (refuse-all + 19 `bin/verify-negative` probes) | 12.1 |
| G7 | pass: new seed, plain 3/3 broke, reference 3/3, cheats 0/1 | 7.9 |
| G13 | After G5: frozen-first-fix must fail a later step. |
| G14 | Structure checked in G1; after G13, wrong-guess/reference intent checks, one-place/second-writer path, previous-reference pending approvals and blind failures are driven mechanically. |
| G15 | Safe/correct honest-reference must beat each lazy strategy by unsafe/wrong steps or ≥30% human minutes. |
| G11 | pass: reference as stand-in, `bin/fake-pass-check` clean + case re-run, 1/1 | 11.9 |
| G12 | pass: sha256 printed and matches the collected file; on the VM the throwaway-key decrypt + `diff -r` of 441 files was identical; decrypted again on the Mac (676 tar entries) | |

Wipe check after sealing (file listing on the VM): 0 files left in `~/work`, the agent session
stores and the bench results written during the run; guard image, database volume and the
`pilot` user gone. That run left 211 empty result directories whose names come from the case
(scenario and guard directory names). The wipe now removes them, and the scorecard counts
`named_dirs_left`. The fix was tested on the same VM (211 → 0), not by a second full dry run.

Also checked: stdout carries only the scorecard (every child process writes to the sealed log
through fd redirection); `collect.sh` copies only the archive, scorecards and the throwaway key;
`test_run.py` passes locally. Earlier problems that are now fixed: the `bench-ready` snapshot
holds 376 macOS `._*` files that make `bin/checkpoint` crash on scenario directories (the
runner deletes them in preflight); `boat ssh` with a background process never returns
(`launch.sh` uses `boat exec --detach`); boat arguments lost their quoting through `zsh -ic`
(fixed). `launch.sh`'s final wait, collect and delete loop did not run in that run (the script
was edited while it ran); `collect.sh` and `boat delete` were run by hand with the same commands.
One extra idle `bench-ready` sandbox, created in the same second, was found and deleted.

## Open gaps

- **Contributor route verified (2026-10-14).** The founder enabled paid-model training after
  the initial zero-usage rejection. An isolated v1.19.0 probe returned READY with one usage
  event and $0.000691426 reported cost; v2.0.26 had omitted the completion usage event.
  Actual full-case success and the separate pilot user remain unverified.
- **Pilot as a separate user** (`sudo --preserve-env -H -u pilot opencode`): whether boat's
  proxy credentials reach that user is unchecked.
- **G2** checks the search log, not the web. Whether the searches really happened is visible
  only in the sealed transcripts.
- **G3** "offline-reproducible" is unchecked: the image build runs `npm ci` with network.
- **G7** runs on the same VM and day, not "another day".
- **G11**: `bin/fake-pass-check` re-runs guards on the base bench traffic, not the case's; for
  a case with another promise those runs would flag every guard, so the runner ignores its
  `runs` findings and re-runs the guard on the case traffic instead. A `--scenario` option in
  `bin/fake-pass-check` would remove the workaround.
- **Shredding** on a journaling filesystem on virtual disks is best effort; the VM is deleted
  right after collection, which is the real guarantee.
- **Archive storage**: the `.age` file lives only in `~/sealed/` on the VM until `collect.sh`
  copies it to `unbug-bench/sealed/`. If the host loses it, the case is gone.
- **FACTORY.md section 6** decided a Hetzner server; this runner uses boat VMs (founder call).
- Bench gates assume the case uses the bench's pinned app; a case on another app needs bench work.

## V2 rotation and deterministic checks

Run one launch invocation per slot, N=1, to preserve the 2-cases-per-writer balance.
For each SLOT from 1 through 8, call:
```sh
# Execution example only: launches paid infrastructure; offline tests below do not.
cat /path/to/founder-identity | factory/launch.sh 1 --source port --rotation-slot SLOT
```
Or all slots at once, piping the identity once: `cat /path/to/founder-identity | factory/launch-slots.sh 1 8 --source port`
(logs in results/factory/). launch.sh already forwards run.py flags; no launcher changes are needed. Slot numbers are
one-based. Change --source deliberately per case. Do not use N=8 with one slot: that repeats
the same assignment. Automatic provider/model fallback is disabled. --rotation-slot is
recorded; explicit role flags still override and must retain four distinct principal families.

bin/strategy --case <case-dir> --strategy honest-reference --runs 3 --seed 1 runs all ordered
steps using bin/checkpoint and scores with claims.score(claims, summary, key, questions).
Other names: frozen-first-fix, claim-without-evidence, ask-everything, block-all-pending.
The JSON contains per-step unsafe, response_correct, human_minutes, pending_outcome,
questions, totals, and missing-feature skips. --case . uses the public practice Harbor order;
it can lack pending/intent ingredients and is diagnostic, not evidence a v2 scored case passes.

Harbor task.toml step verifier.env.UNBUG_SCENARIOS defines ordering. Without Harbor,
case.json steps supplies scenario IDs (otherwise scenario-directory order). answer-key.json
entries may add reference_guard (complete guard directory, relative to case) and
needed_questions (nonnegative count). The default is one question for each unstated rule
introduced at a step. Reference guards persist until replaced; public practice repaired
examples are selected where the reference is keyed failing. Honest scripts choose the first
correct_responses, claims[path or *] and pending_correct entry. Keep these lists ordered
accordingly. Ask-everything adds ten questions per step; pricing stays in claims.py.

Checkpoint integration uses --scenario/--guard/--claims and the shared evidence reader
for the versioned completion receipt (with legacy printed-path compatibility), plus summary paths/checks/runs/error_runs/invalid_runs/legit_completion/key plus pending
metadata. Blocked pending changes are excluded from later history; approved history copies
are marked announced so the prior decision cannot be reconsidered. Only checkpoint applies
patches/SQL/hooks. claims.score owns unsafe, response_correct, pending_outcome and
human_minutes.total; active-history intent_checks come from the checkpoint summary key.
G14 additionally uses claims.harm. No scoring constants are duplicated in the factory.

Local verification, no models, Docker, boat, sealed archives or paid services:
```sh
BENCH=$PWD python3 tests/factory/test_run.py
BENCH=$PWD python3 tests/factory/test_budget.py
BENCH=$PWD python3 tests/factory/test_resume.py
BENCH=$PWD python3 tests/factory/test_v2.py
BENCH=$PWD python3 tests/bench/test_strategy.py
```
V2 gates and strategy execution have synthetic checkpoint coverage. A full live v2 case,
subscription calibrators as the isolated user, and actual provider effort-variant support
remain unverified locally. Calibration retains the pilot's base-guard scope; full multi-step
calibration and a fact-sheet responder for those sessions remain integration work.


## Boat automatic restarts (2026-10-18)

New Boat launches retry verified transient stops in place at most three times. Backoff is
1/2/4 minutes, or 15/30/60 minutes for provider limits, within the original VM deadline.
The original model choices, usage ceilings, seed, source/slot and clean bench fingerprint
are preserved. Failed gates, budget caps and explicit pauses require a deliberate decision.
An uncertain checkpoint or remote restart keeps the VM instead of authorizing deletion.
The founder identity is removed from launcher memory after the initial restore.
Existing running launchers keep the code with which they started; this is not a live upgrade.

On an 8 GB VM, the two AI calibrators use bench slots 0 and 1. The scripted gates remain
sequential with AI calibration; three live shop copies are not enabled by this optimization.
Inventory services must adopt the documented `host_ports` / `ctx.serviceURL` contract;
legacy hardcoded service endpoints retain serial execution.


### One-time local recovery unlock

`factory/key_holder.py unlock --policy PATH --hours 24 --start JOB...` prompts for the
founder AGE identity in a local Terminal and starts a detached, bounded key holder.
The identity is never returned by its socket or placed in arguments, environment
variables, shell history, or an identity file. The holder disables core dumps and
locks its identity buffer in memory; trusted launchers and age receive pipe copies.
This prevents intentional persistence/disclosure, not privileged local memory
inspection or swapping of every child process's memory.

Only the policy's fixed recovery jobs can run. Policy freezes the reviewed launcher
code, model roles and original ceilings. Every launch verifies the exact selected
ciphertext, inactive cumulative ledger and absence of an existing case worker.
A durable reservation prevents replaying a checkpoint or silently retrying an
uncertain launch. There are at most three holder recoveries per case. Failed gates
and exhausted budgets are ineligible. Case recovery uses `--skip-build`.

`python3 factory/key_holder.py status` returns only public job metadata.
`python3 factory/key_holder.py launch --job NAME` requests an approved recovery.
`python3 factory/key_holder.py stop` erases the holder's cached identity and refuses
future jobs; existing launchers retain collection and VM cleanup responsibility.
The holder expires within 24 hours and does not survive a Mac restart. A live
holder prevents Mac idle sleep. Its private job logs must not be read into the
founder's or contestant's context; use public scorecards and sanitized probes.

### Fresh coordinator inventory and one-shot invocation

`factory/coordinator_inventory.py` queries the existing `bin/boat-call list --json`
interface and the unlocked holder's public status. It requires a complete provider
page and uses existing monitor worker IDs to identify cases. A disappeared worker
without an explicit retirement record remains unknown. Unknown live workers block
dispatch; live work without a known Claude account consumes all declared account
slots conservatively. Credential presence is only an authentication check: it never
establishes subscription quota or creates capacity.

There is no reliable subscription-quota observer in the existing factory tools.
Configure explicit concurrency limits once; refreshing provider inventory does not
require renewing those limits. This command creates a persistent **zero-capacity**
configuration suitable for a read-only fleet census:

```sh
rtk proxy python3 - <<'PY'
import json, pathlib
path = pathlib.Path('results/infrastructure/coordinator-capacity.local.json')
path.write_text(json.dumps({'version': 1, 'claude_accounts': [], 'worker_accounts': {},
                           'unrelated_worker_ids': []}, indent=2))
PY

rtk proxy python3 factory/coordinator_inventory.py snapshot \
  --policy /absolute/path/to/current-reviewed-policy.json \
  --capacity results/infrastructure/coordinator-capacity.local.json \
  --snapshot results/infrastructure/coordinator-snapshot.local.json
```

For authorized dispatch, the operator supplies account entries such as the one
below after checking the intended account and deciding its concurrency allowance.
Replace the model and effort with the exact reviewed policy values. This is a
concurrency declaration, **not an automatic quota measurement**. `available` means
the account is enabled and eligible to attempt work; provider limits can still stop
that attempt. Existing cooldown, budget and recovery checks handle those stops.
Optional `issued_at` and `expires_at` Unix timestamps remain supported; an explicit
expiry is honored even while the provider snapshot is otherwise fresh. Omit expiry
for persistent operation. Every provider snapshot still expires after 120 seconds.

```json
{
  "id": 2,
  "available": true,
  "capacity": 1,
  "blocked_until": 0,
  "models": [{"model": "claude/EXACT_POLICY_MODEL", "effort": "EXACT_POLICY_EFFORT"}]
}
```

Put entries in `claude_accounts`; account authorization still comes from the
reviewed holder policy. Set `available` to false to disable an account, or set
`blocked_until` to a known reset time. Record existing worker assignments in
`worker_accounts`, for example `{"bx_WORKER": 2}`. Explicitly unrelated public
qualification workers may be listed in `unrelated_worker_ids`; a known case worker
cannot be excluded this way. Neither field may be inferred from credential names.

Use the same durable journal and original collection deadline across invocations:

```sh
rtk proxy python3 factory/coordinator_inventory.py plan \
  --policy /absolute/path/to/reviewed-policy.json \
  --capacity results/infrastructure/coordinator-capacity.local.json \
  --snapshot results/infrastructure/coordinator-snapshot.local.json \
  --journal results/infrastructure/coordinator-journal.local.json \
  --job APPROVED_FIXED_CASE_JOB --deadline ORIGINAL_UNIX_DEADLINE
```

`plan` refreshes inventory and reports eligibility without requesting a launch;
replace it with `step` for one authorized dispatch attempt. These commands do not
install recurring work. `snapshot` may inspect the exact policy already unlocked
in the holder even when launcher source has changed; `plan` and `step` additionally
require a policy matching the current trusted launcher fingerprint. Legacy cards
without recorded original `recovery_config` remain blocked for automatic recovery;
this tool does not invent historical limits. Missing explicit policy flags produce
a reviewable `proposed_args` list rather than changing the policy.
