# Running the bench on Harbor (Track 1b, Phase A: desk work)

**Phase 2 runner, 2026-10-17:** [silent live windows](phase2/README.md) skip the
foreground agent call, retain every arm's background processes, and judge the
running shop through a host-owned administrator reader. Ordinary checkpoints
continue using fresh separate verifiers. Host judge code, traffic, queries, seed
identities and the reader image ID are frozen in each audited input snapshot.
The deterministic [process probe](probes/unannounced/task.toml) needs no model.

**2026-10-16 credential relay:** audited model agents now use the local
[keyswap sidecar](keyswap/README.md), with placeholder contestant credentials
and host credential files mounted only into keyswap. Set
`KEYSWAP_CLAUDE_TOKEN_FILE` / `KEYSWAP_CODEX_AUTH_FILE` (paths, never token values).
Codex refresh persists to its dedicated writable host auth file. Oracle/nop need
neither. Model metadata shares the web audit log; boat.dev is blocked. Offline
unit/Docker checks passed; live subscription acceptance still needs the documented
tiny smoke. Historical boat and standalone Codex-auth notes below predate this wiring.

**Infrastructure update, 2026-10-14:** ask-human and monitor persistence have now
passed both a deterministic Harbor probe and an actual two-session Codex probe.
HTTPS path logging, API TLS passthrough and bypass regressions passed. Current
entry points: [Codex](codex/README.md), [lifecycle contract](smoke-lifecycle/README.md),
[web audit](webproxy/README.md), [fingerprints](FREEZE.md). The older sections below
retain the original investigation and its historical unverified notes.

For the combined practice environment, `run-audited.py --agent oracle --job-name NAME`
stages fixed sidecars, attaches the responder only to the isolated network and
collects both cumulative sidecar logs. `--dry-run` checks configuration without
starting containers or models. Native Codex hosted search and Claude hosted
search/fetch are disabled by this launcher; use audited shell/browser retrieval.
Custom agent wrappers need the same setting verified separately. CLI/model pins
and subscription auth for Codex are in `codex/run.py`; no Claude run is implicit.

**Status 2026-10-14: runs end to end on boat.dev** (see "Phase B results" and "Changes land in
the box"). The sections below were written from Harbor's code before anything ran.
Harbor read at commit `4778ceba` (v0.24.0, 2026-10-12), installed as `uv tool install harbor`
(0.24.0). Code references are paths under `src/harbor/` in that commit.

## Verdict

Harbor fits, with one structural change: **the judge cannot share the contestant's
container.** The bench judge drives Docker (reset per run, guard image builds), and Harbor
gives a verifier no Docker control. So both the contestant and the judge get their own Docker
engine (Docker-in-Docker), and every checkpoint is judged in a **separate verifier**: a fresh
judge box that rebuilds a fresh bench and runs the unchanged `bin/checkpoint` on the
contestant's guard and `claims.json`. That also gives Harbor's regrade for free.
The simulated user does not fit (wrong direction, and Harbor forbids it on multi-step tasks);
the human responder must be a small custom service. Harbor's network allowlist is the wrong
tool for "open web, logged"; a logging proxy on an internal Compose network does that.

## Answers to the fit questions

### a. Judge with live services; compose lifecycle

- **Shared (non-separate) verifier = `exec` in the `main` container while every compose
  service is still up.** `_run_shared_verifier` (`trial/trial.py:867`) runs `tests/test.sh`
  through `environment.exec` (`verifier/verifier.py:229`). The environment is stopped only
  after the last step (`trial/multi_step.py:89-91`), or before the last step's verifier when
  that verifier is separate (`multi_step.py:134-135`). Postgres is a normal network peer, so a
  verifier can connect with its own role (the bench's `bench_checker`); Harbor neither helps
  nor hinders. The verifier's exit code is ignored; only the reward file counts
  (`verifier.py:229-268`).
- **Why we still do not use it:** our judge runs `docker compose exec/stop/up` and
  `docker build` (`bin/bench.py` `dc()`, `reset()`, `prepare_app_guard()`). Inside Harbor's
  `main` there is no Docker unless we add it, and if we add it in the contestant's container,
  the contestant controls the judge's daemon, images and the reset template. Hence a
  separate verifier with its own Docker engine.
- **Per trial:** one Compose project per trial, named from `{trial_name}__env`
  (`trial.py:1335`, project name `docker.py:713`). Start = `compose build` (unless prebuilt)
  → `down --remove-orphans` (`docker.py:1074`) → `up --detach --wait` (`docker.py:1087`,
  `runtime.py:38-41`), so service healthchecks gate the start. Stop = `down`, or with the
  default `delete=true` `down --rmi local --volumes --remove-orphans`
  (`docker.py:1188-1221`; default `models/trial/config.py:201`).
- **Per step:** no restart. Each step uploads `steps/<name>/workdir/` into the agent's
  working directory, runs its optional `setup.sh` (as the agent user, under the baseline
  network policy, no timeout), then an optional healthcheck (`multi_step.py:149-170,
  281-331`). Filesystem, processes and services persist. After a shared verifier, `/tests` and
  `/logs/verifier` are emptied before the next agent phase (`multi_step.py:159-165`,
  `trial.py:829-836`).
- **Separate verifier:** a fresh environment per step, started and stopped around the
  verifier (`trial.py:969-1019`). Its definition comes from `[verifier.environment]`
  `docker_image` or `tests/Dockerfile|docker-compose.yaml` (tests baked in), else a fresh copy
  of the agent environment (`models/task/verifier_mode.py:88-130`). Declared artifacts are
  copied from the agent container and restored at their original paths (`trial.py:925-933`).
  Regrade works for multi-step tasks when every step is separate (`trial/regrade.py:100-110`).

### b. Unbug's monitor as a long-running service between steps

- **Yes, mechanically.** The agent environment, including all sidecars, lives for the whole
  trial (`trial.py:532-549` start, `multi_step.py:91` stop). Two placements:
  1. A process (or nested container) inside `main`, started by Unbug in the establish step.
     Processes started with `nohup`/`setsid` should outlive the `docker exec` that started them,
     and Harbor kills nothing between steps (no such code in `multi_step.py`). **Unverified:**
     whether the agent CLI (Claude Code, Codex) kills its own background children on exit.
  2. A Compose sidecar added **only for arm C** with `--extra-docker-compose
     <file>` (`cli/jobs.py:930-947`, merged in `docker.py:358-432`). In our layout the app
     runs nested inside `main`, so a sidecar cannot reach Postgres; placement 1 is the one
     that works here.
- **Fairness:** between steps the monitor keeps running while other arms have no agent at
  all, and that "between" time is real: the separate verifier for each step runs a full fresh
  bench (expect 15–30 min), during which `main` stays up. Consequences:
  (1) Harbor records tokens only for the agent CLI per step; the monitor's model calls and
  CPU are invisible to Harbor, so the monitor must write its own usage log (collected as an
  artifact) to count against C's budget, as PROTOCOL requires.
  (2) Actions the monitor takes during verification cannot change that checkpoint
  (artifacts are collected before the verifier starts, `multi_step.py:127-142`) but can
  change the next one; record them with timestamps, and count wall time outside agent windows.
  (3) The change lands in `setup.sh` before the next agent session, so the monitor can see it
  first. That is the lifecycle being tested, but latency for A/B/C0 starts at step start.
  If off-clock work must be blocked instead, a job plugin can pause the monitor on
  `on_verification_started` (`trial/hooks.py:17-26`, plugin docs `plugins/custom-plugins`).

### c. Network policy, logging, where a proxy fits

- **How `allowlist` works on local Docker:** Harbor adds an egress sidecar (gost transparent
  proxy + nftables, `environments/docker/harbor-docker-egress-control-sidecar/`). Every
  compose service *without* its own `network_mode`/`networks` is moved into the sidecar's
  network namespace (`docker.py:442-514`). nftables redirects all TCP on the **output** hook
  to gost, except local addresses and DNS (`bin/network-policy:57-84`); gost passes only
  hosts in the allowlist file (`gost.yaml`, SNI/HTTP sniffing). `allow-all` deletes the
  nftables table (`network-policy:123-127`). Phase switching runs
  `network-policy allow|deny-all|allow-all` in the sidecar (`docker.py:1449-1475`).
- **Consequences for this bench (read from code, untested):**
  - If the bench services sat in the sidecar namespace, all of them would share one network
    namespace: both Medusa instances bind port 9000 and would collide, and service names
    would stop being separate hosts.
  - Traffic from `main` to another compose container is not "local", so it goes through
    gost and must be allowlisted by IP/CIDR.
  - Containers nested in a Docker-in-Docker `main` send **forwarded** traffic, which the
    output-hook rules never see: the allowlist would not bind them.
- **Request logging: none.** `gost.yaml` configures no logging; nothing is collected; in
  `public` mode no traffic passes through gost at all.
- **Where a logging proxy fits:** outside Harbor's policy, in plain Compose. Put `main` on an
  `internal: true` network whose only way out is a `webproxy` sidecar (also on a normal
  network), and set `HTTP_PROXY`/`HTTPS_PROXY` in `main`. Docker enforces the isolation, so it
  also binds nested containers. A mitmproxy sidecar with its CA trusted in `main`
  (`NODE_EXTRA_CA_CERTS`, `SSL_CERT_FILE`) logs full URLs (needed to flag visits to #17032);
  model API hosts can be passed through untouched (`--ignore-hosts`) and still appear as
  CONNECT lines. Collect the log with a sidecar artifact
  (`{source = "/log/web.log", service = "webproxy"}`, `models/task/config.py:640-660`).
  Harbor's own `network_mode` stays `public`. Not drafted yet (see Phase B).

### d. Simulated user vs. our human responder

- **How it works:** the *user agent* is the agent Harbor runs; it gets persona + bridge
  instructions + the task instruction (`trial.py:601-618`, `trial/simulated_user.py:14-24`)
  and talks to the agent under test by running `acpx prompt "<msg>"`, which blocks until the
  target finishes its turn (`bridges/acp.py:25-38`, acpx 0.11.2). Turns are not counted by
  Harbor; they are the user agent's `acpx prompt` tool calls in its trajectory, plus the acpx
  session export saved as `bridge-trajectory.json` (`acp.py:248-267`). Target token usage is
  copied into `agent_result.metadata.acp_target_usage` (`acp.py:269-280`).
- **It does not fit:** the user initiates and the agent answers (the reverse of ours); the
  user agent shares the container, so a fact sheet would be readable by the contestant; and
  `MultiStepTrial` rejects any user agent (`multi_step.py:36-39`).
- **Smallest alternative:** a `responder` Compose sidecar that holds the fact sheet (never in
  `main`), exposed to the contestant two ways: an MCP tool `ask_human(question)` declared in
  `[[environment.mcp_servers]]` (Claude Code and Codex register it automatically,
  `agents/installed/claude_code.py:1717-1743`), and a one-line `ask-human` CLI (curl) for
  agents without MCP. It answers with a responder model from the fact sheet, or holds the
  request until the founder replies (the one real-human check case). It appends one JSONL line
  per contact to its own volume: attempt, step, question, answer, `on_sheet`, and
  sent/opened/replied/closed timestamps, collected as a sidecar artifact. Counting:
  questions = lines; human minutes = the fixed minutes per question (decided 2026-10-14), or
  closed − opened for the founder case. Note: the responder model is an extra paid or
  subscription call, outside the arm's budget.

### e. Pinning agents; tokens and cost

- **CLI version:** `--ak version=<x.y.z>` (`agents/options.py:56-62`). Claude Code installs
  exactly that via npm or the bootstrap script and skips reinstall when the installed
  version matches (`claude_code.py:451-490`). Unpinned, Harbor records the detected version
  (`agents/installed/base.py:1142-1148`).
- **Model:** `-m anthropic/<full model id>` sets `ANTHROPIC_MODEL` and the tier aliases
  (`claude_code.py:1745-1767`). Claude Code can still call other models (subagents,
  background tasks); per-model usage lands in `agent_result.model_usage`
  (`models/agent/context.py:34-41`), so check it to prove the pin held.
- **Recorded:** `result.json` → `agent_info` {name, version, model_info}
  (`models/trial/result.py:39-58`); per step `step_results[i].agent_result` with
  `n_input_tokens`, `n_cache_tokens`, `n_output_tokens`, `cost_usd`
  (`context.py:21-33`, filled at `claude_code.py:1657-1686`); trial totals via
  `compute_token_cost_totals` (`result.py:99-120`). Claude Code cost = the CLI's own
  `total_cost_usd`, else LiteLLM list price (`claude_code.py:1001-1036, 1625-1628`); Codex
  cost = LiteLLM list price (`codex.py:1077-1134`). Subscriptions: Claude via
  `CLAUDE_FORCE_OAUTH=1` + `CLAUDE_CODE_OAUTH_TOKEN` (`claude_code.py:1770-1811`); Codex via
  `auth.json` (not in ACP mode, `codex.py:525`). List-price cost is still recorded, which is
  what PLAN asks for.
- **Budgets are not enforced** by Harbor beyond wall-clock timeouts; token/money caps
  are checked after the run.

### f. Verifier timeouts, multi-metric reward, per-checkpoint scoring

- **Timeouts:** any float. **Trap:** a step's verifier timeout defaults to 600 s and never
  inherits `[verifier].timeout_sec` (`StepConfig.verifier` is a full `VerifierConfig`,
  `models/task/config.py:563, 760-763`; `trial.py:838-848`). Verified with Harbor's model:
  task 3600 + step without timeout → step 600. The draft sets 3600 s on every step.
  Multipliers: `--verifier-timeout-multiplier`.
- **reward.json:** a flat object of finite numbers only; strings, nested objects, NaN are
  rejected (`verifier.py:89-122`). So `test.sh` writes flat metrics to `reward.json` and the
  full judge output to `/logs/verifier/checkpoint.json`, which Harbor archives per step under
  `steps/<name>/verifier/` (`multi_step.py:333-372`).
- **Per-checkpoint scoring is kept:** each step's rewards stay in
  `result.json.step_results[i].verifier_result.rewards`. `multi_step_reward_strategy` only
  derives the trial-level number: `mean` (per key over steps with results; a missing key
  counts 0) or `final` (`trial.py:793-827`). We ignore the trial-level number and analyse
  per step. Do **not** set `min_reward` (it skips later steps). A step whose verifier writes
  no reward file stops the trial (`multi_step.py:200-202`), so `test.sh` always writes one
  (`judge_error: 1` on failure).

### g. Daytona and Docker-in-Docker (from code)

- Compose tasks on Daytona run in **one DinD sandbox** (`docker:28.3.3-dind`, override with
  `--ek dind_image=…`, faster start with `--ek dind_snapshot=…`); Harbor starts `dockerd` by
  hand, uploads the compose files, then `compose build` and `up -d` with a 120 s timeout,
  then waits 60 s for `main` (`environments/daytona/environment.py:444-860`, start at
  `715-807`).
- In compose mode Daytona supports only `public` and `no-network`: no allowlist, no
  per-phase switching (`daytona/environment.py:1107-1121`). Our proxy design does not need
  either.
- Our `main` runs its own `dockerd`, so on Daytona that is Docker inside Docker inside the
  Daytona sandbox, with `privileged: true` requested of the sandbox's daemon. **Nothing in
  Harbor's code says whether Daytona allows that**; that is the one-hour test.
- Sizing: `cpus`, `memory_mb` (rounded down to GiB) and `storage_mb` pass through
  (`daytona/environment.py:1201-1213`). Each separate verifier is a second sandbox per step.
- Images must be pullable from the sandbox (a registry). The judge image contains the hidden
  bench, so for sealed cases it must be private; private-registry pulls inside the DinD
  sandbox are unverified.

## Mapping: our concept → Harbor

| Ours (PROTOCOL / PLAN) | Harbor | Notes |
|---|---|---|
| Attempt | Trial | `-k` attempts per arm; `--n-concurrent` |
| Phase 3 establish + each change scenario | `[[steps]]` | Fresh agent session per step (default) = how A/B/C0 meet a change |
| Change event (diff + deploy line) | Step `instruction.md` + `workdir/` files | Hidden parts (key, judge hooks) only in the judge image |
| Landing a change in the live app | Step `workdir/setup.sh` → `bin/land` | See "Changes land in the box" |
| Checkpoint oracle (30 runs, claims) | Separate verifier per step running `bin/checkpoint` | Fresh bench each time; regradable |
| Guard (`db.sql`/`app.patch`), `claims.json` | Task `artifacts` `/app/guard`, `/app/claims.json` | Copied each step, restored in the verifier |
| Per-checkpoint measures | Step `reward.json` (flat) + `checkpoint.json` | Trial-level mean ignored |
| Arm A / B / C0 | Same task, agent config per job (`-a`, `--ak`, `-m`, skills/MCP) | B/C tools must be in the image or installed per arm |
| Arm C (Unbug lifecycle) | Custom agent (`--agent module:Class`) or Claude Code + Unbug skills/MCP; monitor in `main` | Monitor usage logged by Unbug itself |
| Reference fix / plain Medusa | `-a oracle` (solution/) / `-a nop` | `nop` = no guard → judge uses `guards/none` |
| Model + CLI pin, tokens, cost | `-m`, `--ak version=`; `result.json` | |
| Human channel, human minutes | Custom `responder` sidecar + MCP/CLI | Not Harbor's simulated user |
| Web log (`web.jsonl`) | Custom `webproxy` sidecar on an internal network | Not Harbor's allowlist |
| Calibration / replay of a stored guard | `harbor run -a oracle` / `harbor trial regrade` | |

## Gaps and the smallest workaround for each

| Gap | Workaround |
|---|---|
| Judge needs Docker; Harbor's verifier has none | Docker engine in each box; separate verifier per step (drafted) |
| Contestant needs Docker (CONTESTANT.md) | `main` runs its own `dockerd` (drafted). Privileged = host-root risk; use sysbox on Hetzner |
| Random scenario order per attempt | Steps run in `task.toml` order: generate one task directory per order seed (not built) |
| No "establish" answer key | S0 stands in (only `keep` scores correct at establish); bench agent to add a key |
| Contestant bundle not defined | Box image copies an assumed list (see `images/Dockerfile`); confirm with the bench agent |
| Human responder | `responder` sidecar + MCP tool + CLI, JSONL log as artifact (not built) |
| Web logging | `webproxy` sidecar, internal network, mitmproxy (not built) |
| Monitor compute invisible to Harbor | Monitor writes its own usage log, collected as an artifact; optional pause plugin |
| Token/money budgets not enforced | Check after the run; over budget = flagged |
| "Retry a harness error once" is per checkpoint; Harbor retries whole trials | `test.sh` re-runs `bin/checkpoint` once when any run errored (drafted) |
| Separate verifier rebuilds the bench each step (minutes) | Later: preload the built app image into the judge box |
| `/logs/artifacts` contents are moved out after each step | Keep the guard at `/app/guard` (drafted) |

## What is drafted

```
harbor/
  README.md                  this file
  build.sh                   Phase B: builds both images, stages generated inputs
  .gitignore                 generated inputs
  images/Dockerfile          base (node 22 + Docker CE) → box (contestant bundle) / judge (whole bench)
  images/Dockerfile.dockerignore
  medusa-oversell/
    task.toml                4 steps, separate verifier, artifacts, timeouts
    environment/docker-compose.yaml   main = privileged box with dockerd
    tests/docker-compose.yaml         verifier main = privileged judge box
    tests/test.sh            fresh bench → bin/checkpoint → checkpoint.json + flat reward.json
    solution/solve.sh        oracle: reference guard + all paths protected, keep
    steps/establish/         instruction (points at CONTESTANT.md) + setup.sh (npm ci, bin/setup, shoppers)
    steps/<change>/workdir/setup.sh   bin/land changes/<step> + restart shoppers if stopped
    steps/s0-null/           change instruction
    steps/s2-express-checkout/   change instruction; diff staged by build.sh
    steps/s11-monitor-blind/     change instruction; SQL + change record staged by build.sh; oracle repairs (ENABLE ALWAYS) and claims protected
```

The nop variant needs no files: `-a nop` leaves `/app/guard` absent, and `test.sh` then
judges `guards/none`. Scenario logic is not duplicated: steps name the bench's own
`scenarios/dev/<id>` directories, and `bin/checkpoint` applies them.

Assumptions to check (all unverified): `privileged` works for Harbor's `main` and inside
Daytona; nested `dockerd` on a named volume is stable; 6 CPUs / 8 GiB fit the nested stack
plus image builds; the box bundle is enough for `bin/setup` and `bin/reset`;
`Dockerfile.dockerignore` re-includes `test.sh`; `bin/checkpoint` accepts an absolute guard
path and repeated `--scenario` (`bench.load_scenario` landed in `bench.py` on 2026-10-14;
the absolute-path and repeated-flag cases are still unchecked).

## Phase B results (2026-10-14, boat.dev default sandbox: 4 vCPU Ryzen 9 9950X, 8 GB, KVM)

- Bench as-is on the VM (no Harbor): setup 64 s; plain Medusa 10/10 oversold; reference
  10/10 pass; 0 errors; ~17–25 s per run.
- boat snapshot `bench-ready` (1.3 GB) → new sandbox in 4 s; `docker compose up -d --wait
  postgres redis` first (processes do not survive a snapshot), then runs judge correctly.
- Harbor 0.24.0 needed two fixes: nested dockerd on cgroup v2 (`images/start-dockerd.sh`, the
  docker:dind step) and `guards/none` in the box image. Trial limits: `--override-cpus 4`
  (default sandbox has 4 vCPU; `large` is not allowed on the boat trial).
- `-a nop --disable-verification`: all 4 steps run (artifact-copy warnings are expected).
- `-a oracle --ve UNBUG_RUNS=3`: every step reward 1, 3/3 pass, 0 errors; S11 escalated.
  Whole 4-step trial 17 min.
- `-a nop --ve UNBUG_RUNS=3`: every step reward 0, unsafe 1, 0 errors (legit completion
  0.92). 19 min. boat snapshot `harbor-ready` (550 MB) holds the Harbor install; whether it keeps the built images is unchecked.

## Changes land in the box; shoppers buy (2026-10-14)

Before, a change step only uploaded the change's files to `/app/changes/<step>/`; the
contestant's running shop never changed and nobody shopped there. Now:

- **Landing:** each change step's `workdir/setup.sh` runs `bin/land changes/<step>` before the
  agent's session. `admin.sql` runs as the administrator on the live database; `app.patch` is
  merged into `projects/medusa`, the app image is rebuilt and both instances restart, with
  `/app/guard/app.patch` built on top when present (if it no longer applies, the change deploys
  without it and `bin/land` says so on stderr). No reset: live orders and an installed `db.sql`
  guard stay. Later resets keep the change: the source is merged, and `bench.reset` without
  scenarios re-applies every `changes/*/admin.sql` (absent in the judge box). Only `app.patch`,
  `admin.sql`, `change-record.md` reach the box; the image has no key, judge, hooks or scenario files.
- **Shoppers:** `bin/shoppers` (contestant-visible, independent of the judge traffic), started
  detached by the establish setup and restarted by later setups only if it stopped. About one
  order a minute, 1–2 units of a normal product N1–N5 (100 each), ordered only while at least
  10 more units are available than it takes; half try `POST /store/express-orders` and fall back
  to the cart checkout on 404. It skips while a bench command holds `results/.bench.lock`, so it
  never lands an order inside a reset. Log: `/app/results/shoppers.jsonl`.

Verified on boat.dev `large` (8 vCPU, 16 GB), `--override-cpus 6`:
- `-a oracle --ve UNBUG_RUNS=3`: every step reward 1, 3/3 pass, 0 errors, S11 escalated; 23.5 min.
  In the box: S2 workdir uploaded 14:16:06, both app containers recreated 14:16:40, the express
  route in the source, 4 express orders placed from 14:16:57. At S11 the policy was live with
  14 orders in the database and 0 visible to `arm_monitor`. Shoppers: one process from
  establish to S11, 14 attempts, 14 placed (10 cart, 4 express), 0 refused, 0 errors.
- `-a nop --ve UNBUG_RUNS=3`: every step reward 0, unsafe 1, 0 errors; 12.5 min.
- On the VM bench: `bin/land` with a guard holding `db.sql` + `app.patch` ran the `:guard` image
  with both the express route and the guard's file, guard trigger kept; after S11, `bin/reset`
  passed its baseline and the S11 policy was back.
- One earlier oracle trial lost S11 to the judge box failing its `docker info` healthcheck at
  start (Harbor `up --wait`, before `test.sh`); not reproduced in the next trial or the nop run. Unexplained.

## Phase B test plan (only once Docker is free)

Run from `~/Developer/unbug-bench`. Everything below uses Harbor's own Compose projects and
nested engines; none of it binds host ports 9000/9001. Use `-o /tmp/harbor-jobs` to keep
results out of the repo.

0. Preconditions: the bench agent's scenario machinery is in (`bin/checkpoint` runs);
   `docker info` works.
1. Build: `harbor/build.sh`
2. Box only, no judge: does the nested stack come up and does a background process survive
   between steps?
   `harbor run -p harbor/medusa-oversell -a nop --disable-verification -o /tmp/harbor-jobs --debug`
   Pass: all 4 steps finish; `steps/establish` setup log shows `bin/setup` baseline.
   Then repeat with `harbor task start-env -p harbor/medusa-oversell` and, in the box,
   `bin/reset && bin/check`; record peak memory (`docker stats`).
3. Judge, short: `harbor run -p harbor/medusa-oversell -a oracle --ve UNBUG_RUNS=3 -o /tmp/harbor-jobs`
   Pass: every step has `verifier/checkpoint.json` and a flat `reward.json`; S0/S2 steps
   `unsafe=0`, `reward=1`; S11 `reward=1` with the oracle's unknown/escalate claims.
4. Judge, full (calibration parity, ~4 × 20–30 min):
   `harbor run -p harbor/medusa-oversell -a oracle -o /tmp/harbor-jobs` and
   `harbor run -p harbor/medusa-oversell -a nop -o /tmp/harbor-jobs`
   Pass: oracle `pass_runs = 30` with `error_runs = 0` on S0 steps; nop oversells on every
   base path (per `scenarios/dev/*/key.json` `expected_judge.none`). Then recalibrate on the
   same machine type (`bin/calibrate` inside a judge box).
5. Regrade: `harbor trial regrade --help`, then regrade one finished trial; verdicts must
   match within the Wilson interval.
6. Monitor persistence: copy the task to `/tmp`, make `solution/solve.sh` also start
   `nohup setsid sh -c 'while :; do date >> /app/.heartbeat; sleep 5; done' &`, run
   `-a oracle`, and check the heartbeat has no gaps across steps (Harbor side). Separately,
   with founder approval to spend subscription: one `-a claude-code -m anthropic/<pinned id>
   --ak version=<pinned>` trial to see whether Claude Code kills its background children.
7. Build and test the `responder` and `webproxy` sidecars as
   `--extra-docker-compose` overlays; check the MCP tool appears in Claude Code and that a
   visit to github.com/medusajs/medusa/issues/17032 shows in the web log with its full URL.
8. Daytona one-hour test (needs `DAYTONA_API_KEY` and both images in a registry):
   `harbor run -p harbor/medusa-oversell -a oracle -e daytona --ve UNBUG_RUNS=3 -o /tmp/harbor-jobs`
   Yes if: nested `dockerd` starts in the privileged `main`, `bin/setup` completes, and the
   S0 checkpoint passes 3/3 with reset times near local. No → drop Daytona, run on Hetzner.
