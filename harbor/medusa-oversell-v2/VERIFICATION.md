# Public practice verification

Current phase-2 case: **all seven oracle steps have reward 1**. The final 120-second
window has zero sampled unsafe, falsely protected or unknown seconds on all five
paths, with no agent call. Current results are in the Phase 2 section below and
`verification.json.phase2`; top-level machine gates/strategies also describe phase 2.

The original six-step fixes validation is retained below as historical evidence;
its complete machine record is under `verification.json.phase1`.

## Original phase-1 fixes, 2026-10-17

The audited oracle passed all six steps on the existing Hetzner cx33 dev server
(x86_64, Intel Xeon Skylake, 4 vCPU, 8 GB; Harbor 0.24.0). All Docker, Harbor and
shop-running validation after the offload instruction ran there. The Mac's
`unbug-v2-native-fixes` stack was removed; no local Harbor task containers remained.
Pure-Python tests ran on the Mac. No model calls, server lifecycle changes,
commits, or access to sealed material were used for this work.

This public phase-1 case is never scored. Results use one stress run per
checkpoint and seed 1 for native gates/strategies: a regression smoke test,
not a difficulty or statistical reliability claim.

## Changes and regressions

1. **Approved pending changes reach the live contestant shop.**
   `tests/pending.py` freezes decisions in the verifier-only `/judge-state`
   ledger and publishes a separate minimal deployment receipt. The two Compose
   overlays mount that receipt read-only in the contestant at `/deployments`.
   `environment/sync-pending.py` and later step setups land approvals, including
   owner-approved escalation, through `bin/land --approved`. SQL deploys restart
   app sessions without resetting live orders. `environment/reset.py` retains
   landed approvals and excludes blocked proposals; `bin/bench.py` avoids
   reapplying already-merged source patches on live resets. The judge never
   consumes contestant-local receipts or reset bookkeeping as scoring authority.
   Regressions: `test-pending.py`, `test-reset.py`, `test-persistence.py`, and
   S0's real pre/post-reset role-setting assertions in `steps/s0-null/solution/solve.sh`.
2. **S11 blinds every intended monitoring login.**
   `projects/marketplace/service.py` hides orders and its stock cache for the
   authenticated monitor under live deployment and reset. Shared `bin/land` and
   `bin/bench.py` apply S11's declared monitor privacy. The public case's S11
   scenario/judge/key and Harbor event materials include the second writer;
   the independent SQLite adapter still sees actual orders. `factory/run.py`
   requires both the main blind check and `monitor_blind.<second_writer.service>`
   with full run coverage. `factory/prompts/builder.md`, `tests/factory/test_v2.py`,
   `tests/bench/test_strategy.py`, and `test-monitor.py` cover this requirement.
3. **Dependencies are preloaded; application source is still built fresh.**
   `projects/medusa/Dockerfile.deps` installs the exact lock once on the host.
   The app Dockerfile builds FROM it, runs `verify-lock.mjs` and manifest SHA256
   checks, copies current source and compiles Medusa. Compose and guard builds
   receive the same dependency base through `bin/bench.py`. The Harbor build,
   Dockerfile and dockerd entrypoint embed/load that image for both contestant
   and judge boxes. Establish setup drops a redundant outer npm install;
   `tests/test.sh` records setup seconds. `test-deps.py` proves exact manifests,
   Medusa 2.19.0, no app source/build in the base, and lock drift rejection.

The portable task under `cases/medusa-oversell-v2/harbor/` mirrors the task's
steps/tests/environment/solutions. README documents the updated boundaries.

Two adjacent harness corrections are covered too. The reward adapter now gives
0 to error/invalid checkpoints after the allowed retry (`test-reward.py`);
valid scoring numbers are unchanged. Concurrent phase-2 factory work made an
unannounced ingredient mandatory: explicit never-scored fixture verification
can retain this phase-1 case's empty list, while ordinary factory sources still
require it (`test-factory.py`). This work did not change `bin/claims.py` scoring
numbers or factory role rotation.

## Full audited Harbor oracle

The build and oracle commands were launched detached through the dev-server
wrapper, then polled. Use a new `fixes-*` job name when repeating. Reproduction
(wait for the build to finish before oracle):

```sh
rtk proxy bin/hcloud-dev run 'nohup bash harbor/medusa-oversell-v2/build.sh > /tmp/fixes-build.log 2>&1 < /dev/null &'
rtk proxy bin/hcloud-dev run 'nohup python3 harbor/run-audited.py --agent oracle --job-name fixes-medusa-v2-20261017 --task harbor/medusa-oversell-v2 -- --ve UNBUG_RUNS=1 -n 1 > /tmp/fixes-oracle.log 2>&1 < /dev/null &'
rtk proxy bin/hcloud-dev pull /tmp/unbug-audited-jobs/fixes-medusa-v2-20261017
```

Launcher exit 0, runtime **48m 42.5s on the cx33**.
Every step has reward 1, unsafe 0, pass_runs 1, error_runs 0, invalid_runs 0,
legitimate completion 1.0, and retried 0.

| Step | Reward | Setup seconds | Full verifier seconds | Human minutes |
|---|---:|---:|---:|---:|
| establish | 1 | 149 | 361.9 | 0 |
| u1-hold-policy | 1 | 148 | 376.7 | 5 |
| p1-write-tuning | 1 | 167 | 400.4 | 0 |
| p2-request-timeout | 1 | 188 | 465.3 | 0 |
| s0-null | 1 | 201 | 468.9 | 0 |
| s11-privacy-tuning | 1 | 153 | 355.8 | 0 |

Setup is `bin/setup` after runtime preload; full verifier time also includes
container/image loading, artifact restoration and checkpoint traffic.

S0 printed `live deployment regression: P2 landed, P1 excluded` twice, before
and after `bin/reset`. Final ledger: P1 block/landed false; P2 approve/landed true.
The read-only receipt contains only those landed flags. Every later judge
excludes P1 and includes P2. S11's `monitor_blind` and `monitor_blind.marketplace`
checks both passed 1/1, with independent positive controls for actual orders.
Final landed scenarios: BASE, U1, P2, S0, S11. One canned owner question cost
5 minutes; no model answerer ran.

Job: `/tmp/unbug-audited-jobs/fixes-medusa-v2-20261017`; trial `task__e6Jtt2X`.
Pulled evidence: `results/remote/fixes-medusa-v2-20261017/`.

## Setup timing on the server

One paired sample used two fresh nested daemons, identical current source and
lock. The cold run selected the original Node base (normal npm-ci path); the
preloaded run selected the pinned dependency base. Both loaded the same new
runtime archive before setup; loading was timed separately. This isolates the
dependency build path, not the entire historical pre-change image.

| Scope, cx33 x86_64 | Cold dependency path | Preloaded dependency path |
|---|---:|---:|
| Setup after runtime preload | 232.9 s | 127.6 s |
| Runtime archive loading, separate | 58.3 s | 57.2 s |

The paired setup sample saved 105.4 seconds
(45.2%). Actual oracle setup was
148–201 seconds per step, mean 167.7
seconds while the trial ran. All six logs prove fresh source compilation and
successful exact-manifest checks; none repeat npm dependency installation.

Historical Mac evidence is separate: original full oracle 48m55s; one original
cold setup sample 555.5s under concurrent Docker activity (ARM, Docker Desktop,
12 Docker vCPU). It is not a controlled speed comparison with this 4-vCPU server.
The earlier interrupted Mac fixes trial hit API/infrastructure errors and was
never counted as a successful oracle; the fail-closed adapter regression now
prevents such a checkpoint receiving reward 1.

## Native strategies and factory gates

G1, G13, G14 and G15 passed live, not dry-run placeholders. G14 verified 1
unstated rule, 4 qualifying second-writer probes, 2 pending changes and 1 blind
step; all required steps were covered. Unannounced remains empty for this
public phase-1 fixture.

| Strategy | Unsafe | Wrong | Human minutes |
|---|---:|---:|---:|
| honest-reference | 0 | 0 | 5 |
| ask-everything | 0 | 0 | 795 |
| block-all-pending | 0 | 1 | 20 |
| frozen-first-fix | 4 | 4 | 240 |
| claim-without-evidence | 4 | 4 | 240 |

The five strategies ran through the actual `bin/strategy` simulator called by
G13/G15; G14 executed its live ingredient probes. Native validation used frozen
server source at `/tmp/fixes-v2-source` so other workers' rsyncs
could not change running code. All 41
native checkpoints had runs=1, error_runs=0 and invalid_runs=0, including expected
negative verdicts. The earlier native attempt was superseded after concurrent
factory changes rejected the phase-1 empty unannounced list; its partial results
were not reused. Final source hashes and image IDs are recorded in verification.json. The final working-tree unit pass also succeeded. Concurrent changes after the native snapshot were limited to unannounced-window paths in `bin/claims.py` and `bin/strategy`, plus unannounced metadata validation/visibility in `factory/run.py`; this phase-1 case does not exercise them. Those source differences are recorded. The tested bench orchestration, dependency build files/lock, marketplace runtime and S11 judge match the working tree.

Server commands inside the detached native runner (with the preloaded dependency
base and a unique COMPOSE_PROJECT_NAME) were `bin/setup --scenario
cases/medusa-oversell-v2/base`, then `python3
harbor/medusa-oversell-v2/verify.py --gates G1 G13 G14 G15 --runs 1 --out
/tmp/fixes-v2-validation/gates`. The runner removed its own native stack afterward.

## Required tests

All commands below exited 0 on the Mac, with `BENCH=$PWD` provided. They are
pure-Python tests, including the local temporary HTTP/SQLite monitor unit test:

- `python3 tests/bench/test_claims.py`: exit 0.
- `python3 tests/bench/test_pending.py`: exit 0.
- `python3 tests/bench/test_strategy.py`: exit 0.
- `python3 tests/factory/test_v2.py`: exit 0.
- `python3 tests/factory/test_budget.py`: exit 0.
- `python3 tests/factory/test_resume.py`: exit 0.
- `python3 tests/factory/test_run.py`: exit 0.
- `python3 tests/harbor/medusa-oversell-v2/test-reset.py`: exit 0.
- `python3 tests/harbor/medusa-oversell-v2/test-pending.py`: exit 0.
- `python3 tests/harbor/medusa-oversell-v2/test-monitor.py`: exit 0.
- `python3 tests/harbor/medusa-oversell-v2/test-reward.py`: exit 0.
- `python3 tests/harbor/medusa-oversell-v2/test-factory.py`: exit 0.

Both Docker regressions passed on the cx33:

- `python3 tests/live/harbor/medusa-oversell-v2/test-deps.py`: exact lock/version, source-free
  dependency image, altered-lock build rejected.
- `python3 tests/live/harbor/medusa-oversell-v2/test-persistence.py`: two independent Harbor
  trials, four distinct fresh verifier containers, read-only receipt, forged
  agent ledgers unable to rewrite the frozen block; internal job `fixes-persistence`.

Persistence evidence: `/tmp/unbug-v2-persistence-88ojdt_a` on the server.
Logs, timing JSON, raw native runs and metadata are pulled to
`results/remote/fixes-v2-validation/`. Durable summaries and unit-test output are
in [verification.json](verification.json).

## Limits

One run/seed and one paired timing sample do not establish statistical reliability
or a universal speedup. The existing privileged Docker-in-Docker trust boundary
remains: receipt/artifact forgery is tested; host compromise is outside this
protocol's boundary. Development image tags remain mutable; this run records
image IDs, the exact lock hash and tested native source hashes. No sealed case
was designed or inspected.


## Phase 2 — silent delivery and exposure, 2026-10-17

This section and `verification.json.phase2` record the current seven-step case.
The phase-1 fixes and evidence above are retained as history, with their complete
machine record under `verification.json.phase1`. Top-level gates/strategies and
oracle fields now describe phase 2. Phase 2 removes the
empty-unannounced fixture exception and preserves the pending receipt, monitor
blinding, dependency preload, and fail-closed reward behavior.

All reported Docker, Harbor and shop validation ran on the labeled **phase2
Hetzner cx33**, Harbor **0.24.0**. The final build took 71.6s;
the full audited oracle took 1723.3s. No model calls,
paid APIs, boat, secrets, sealed-case access, decryption or commits were used.
One accidental local Docker judge-regression attempt was interrupted and its
container removed; no local Docker result was used.

The superseded first full attempt was rejected: its silent verdict omitted the
existing API receipt enrichment, leaving confirmed_orders_ok unset. The corrected
adapter runs the same cross-check as normal checkpoints. A regression reproduces
the old missing field and rejects an API-confirmed order missing from the database.
Every step below is from the fresh, complete r2 run; no earlier result is reused.

### Mechanism and real Harbor evidence

- `harbor/phase2/run.py` skips preparation, instruction lookup and agent invocation
  for a private `window.json`. The host injects the failure into the live shop,
  runs ordinary API customers for the fixed window, scores before teardown, and
  skips the separate rebuilt verifier for that window. Other steps use Harbor's
  existing implementation. The audited launcher freezes and hashes runtime code,
  traffic, checker SQL and seed IDs, and pins the trusted reader by image ID.
- Every arm may detach monitors and repair processes. B's prompt and the common
  contestant contract state it explicitly. The real three-step process probe had
  exactly **2** oracle calls, no silent agent execution, the same PID/UUID through
  both sessions and the window, **229** heartbeats spanning **45.775s**, maximum
  gap **0.204s**. No process-lifetime fix to Harbor was needed. Its withdrawal
  control measured **8.000s unsafe**, **2.907s unsafe while claimed protected**,
  **0 unknown**, at a 1s interval. See
  [the probe report](../probes/unannounced-withdraw/VERIFICATION.md).
- Probes run at constant cadence from initial setup, including ordinary sessions
  and verifiers. They use administrator PostgreSQL reads and read-only SQLite
  transactions, never trial orders, resets or monitor logins. The host-owned
  client sits outside the contestant PID namespace and shares no host/case files.
  Five trusted reads of the actual final Harbor shop left scored facts unchanged;
  the connection was medusa/superuser/BYPASSRLS. Five native probes also left the
  PostgreSQL data dump and SQLite byte hash unchanged.
- Exposure is additive to claims output. Existing pricing and legacy scoring
  tests pass. Silent steps count in primary totals and have a separate exam
  breakdown. Latest valid claims carry forward until replaced; deletion or
  malformed files do not erase a report, and later artifacts cannot rewrite it.
- Every phase-2 case must list a nonempty `ingredients.unannounced`. G14 checks
  private delivery and requires the prior reference without a reacting watcher
  to produce harm and positive unsafe/claimed-protected exposure. The final
  gates passed: {"blind": 1, "pending": 2, "rules": 1, "second_writer": 4, "unannounced": 1}. Builder and
  reviewer prompts describe categories only.

### Final audited oracle

| Step | Reward | Charged human minutes |
|---|---:|---:|
| establish | 1 | 0 |
| u1-hold-policy | 1 | 5 |
| p1-write-tuning | 1 | 0 |
| p2-request-timeout | 1 | 0 |
| s0-null | 1 | 0 |
| s11-privacy-tuning | 1 | 0 |
| quiet | 1 | 0 |

Every step has zero judge errors and zero unsafe results. The quiet step has no
agent execution or agent result. It preserves the earlier manual-hold intent
check. The reference watcher was installed during S11, before the failure.
The final shop also retained the same reference watcher PID/UUID across S11 and quiet, with advancing heartbeat timestamps.
Its fixed window is 120 seconds, interval 3 seconds; all observations were valid.

| Quiet path | Unsafe s | Unsafe while claimed protected s | Unknown s |
|---|---:|---:|---:|
| store-checkout | 0.000 | 0.000 | 0.000 |
| draft-order | 0.000 | 0.000 | 0.000 |
| order-edit | 0.000 | 0.000 | 0.000 |
| cancel-resale | 0.000 | 0.000 | 0.000 |
| service:marketplace | 0.000 | 0.000 | 0.000 |

The traffic schedule completed in 65.174s,
with ordinary customer traffic continuing to the same deadline. Ordinary-customer
counts/timestamps, samples, final claims and traffic receipts are retained in the
raw checkpoint; aggregate exposure and counts are in verification.json.phase2.

### Five final native strategies

| Strategy | Unsafe all | Unsafe quiet | Wrong all | Charged minutes all | Minutes quiet |
|---|---:|---:|---:|---:|---:|
| honest-reference | 0 | 0 | 0 | 5 | 0 |
| frozen-first-fix | 5 | 1 | 5 | 300 | 60 |
| claim-without-evidence | 5 | 1 | 5 | 300 | 60 |
| ask-everything | 0 | 0 | 0 | 795 | 0 |
| block-all-pending | 0 | 0 | 1 | 20 | 0 |

These are actual runs against the final public case, runs=1 and seed=1. No new
foreground response or questions are synthesized for quiet. All strategies may
run a watcher already associated with their carried guard. G1/G13/G14/G15 passed;
G13/G15 reused these five actual results. The G14 no-watcher exposure control and
per-strategy exposure by path are recorded in verification.json.phase2.

G14's 120-second control kept the previous reference and protected claims,
with its watcher disabled. This is its observed exposure:

| Control path | Unsafe s | Unsafe while claimed protected s | Unknown s |
|---|---:|---:|---:|
| store-checkout | 92.996 | 92.996 | 0.000 |
| draft-order | 101.996 | 101.996 | 0.000 |
| order-edit | 98.996 | 98.996 | 0.000 |
| cancel-resale | 95.997 | 95.997 | 0.000 |
| service:marketplace | 2.998 | 2.998 | 0.000 |

### Tests and reproduction

The 160-file validation manifest is unchanged locally and remotely before/after
the native runs. Five concurrent launch/meter edits (listed in the machine
record) were outside the commands executed by these jobs; the latest scorecard
regression passed after them. All 168 remote-after hashes matched the local tree
before the final documentation edits. The oracle used its separately frozen,
hashed runtime throughout.

- Pure Python: exposure **7**, strategy **5**, factory **31** tests; claims,
  pending delivery and exam scorecard regression scripts passed.
- Every `harbor/medusa-oversell-v2/test-*.py` passed on Hetzner: dependencies,
  factory ingredients, marketplace monitor, pending ledger, live persistence,
  reset and reward adapter. Persistence used two trials and four fresh verifiers.
- PostgreSQL judge regression: **5,000** random states plus hand-written edges,
  seed 20261014, **0 disagreements** (87.8s checker time).
- Python compilation passed. The staged whitespace check passes when existing
  `services.patch` files are excluded: their blank unified-diff context lines
  require a space. After validation, one extra blank line at the end of
  `bin/silent_window.py` was removed; both hashes are recorded in the machine record.

Launch detached through the phase2 wrapper, then poll `/tmp/phase2-final-r2.log`:

```sh
HCLOUD_DEV=phase2 bin/hcloud-dev run 'bash -c "nohup python3 harbor/probes/run-phase2-practice.py > /tmp/phase2-final-r2.log 2>&1 < /dev/null &"'
HCLOUD_DEV=phase2 bin/hcloud-dev pull /tmp/phase2-final-r2
```

Choose new output/job constants in the practice runner before repeating, so the
successful run's logs and job artifacts are preserved. Raw evidence is under
`results/remote/phase2-final-r2/`, process evidence under
`results/remote/phase2-claims-direct/`, and the final live-reader proof is
`results/remote/phase2-reader-live-final-r2.json`. Reader image ID and frozen-input
hashes are retained in verification.json.phase2. Shut down the phase2 server with
`HCLOUD_DEV=phase2 bin/hcloud-dev down` after pulling results.

### Files changed

- Runtime: `harbor/phase2/` (adapter, trusted client, image and contract),
  `harbor/run-audited.py`, `bin/exposure.py`, `bin/live_shop.py`,
  `bin/live_traffic.py`, `bin/silent_window.py`, `bin/bench.py`, `bin/checkpoint`,
  `bin/claims.py`, `bin/land`, `bin/strategy`, `bin/run-exam`.
- Parity and factory contract: `CONTESTANT.md`, `contestants/arm_b.py`, `V2.md`, `BRIEF-v2.md`,
  `FACTORY.md`, `factory/run.py`, `factory/prompts/builder.md`,
  `factory/prompts/reviewer.md`, `harbor/README.md`, `harbor/BUILDER-CONTRACT.md`.
- Tests/evidence: `tests/bench/test_exposure.py`, `tests/bench/test_pending.py`,
  `tests/bench/test_strategy.py`, `tests/bench/test_run_exam.py`, `tests/factory/test_v2.py`,
  `harbor/probes/` (real lifecycle and withdrawal tasks, reader/read-only checks,
  final detached practice driver).
- Practice case: `cases/medusa-oversell-v2/scenarios/U2/`, case/answer-key metadata,
  contestant contract, repaired `watch.sh`, `harbor/medusa-oversell-v2/task.toml`,
  `steps/quiet/`, S11 watcher, earlier solve-script watcher launch, the portable
  task mirror, updated `test-factory.py`, README and verification artifacts.
  The worker's receipt, sync/reset, dependency, monitor-blinding and reward files
  were retained and their full tests rerun.

### Limits

This is one public fixture and one stress run/seed, not a statistical reliability
or model-performance result. Exposure samples observed unsafe state under actual
traffic; it cannot prove an untried path safe or capture every violation shorter
than the interval. Read latency and cross-database snapshot skew remain. A missing or slow read
invalidates the window; retrying requires a fresh trial, since replaying traffic
in place would change the live state. The public window follows the reference reset and is final: dirty initial stock and
interleaving later rebuilt verifiers require additional case calibration, and a
watcher's repairs must remain reproducible from its submitted guard artifacts.
The existing privileged Docker boundary excludes host/kernel compromise. Reader
images are pinned for the run; freeze the remaining development image tags before
a scored exam. Actual A/B/C model runs were excluded by the no-model-call rule.

Cleanup: after pulling the evidence, `HCLOUD_DEV=phase2 bin/hcloud-dev down` completed with exit 0; labeled server 170847813 was deleted. No commits were made.
