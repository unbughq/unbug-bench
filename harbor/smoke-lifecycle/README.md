# Harbor lifecycle smoke

Python stdlib only; oracle agent, canned responder, no model calls and no Medusa.
Run from the repository root on a Linux Docker host with Harbor 0.24.0:

```sh
rtk proxy env RESPONDER_DIR="$PWD/harbor/responder" harbor run \
  -p harbor/smoke-lifecycle -a oracle \
  --extra-docker-compose harbor/responder/docker-compose.responder.yaml \
  -o /tmp/lifecycle-jobs --job-name lifecycle-oracle
rtk proxy python3 harbor/smoke-lifecycle/summarize.py /tmp/lifecycle-jobs/lifecycle-oracle/<trial-directory>
```

The two oracle steps execute `ask-human` against the real Compose sidecar and
record its answer. Establish starts a detached Python monitor with redirected
stdio and `start_new_session=True`; observe checks the existing PID. Each step
has a fresh separate verifier whose test waits five seconds. The second
artifact contains heartbeat timestamps spanning the first verifier, including
its environment startup/shutdown. The summary checks identity, heartbeat gaps,
verifier isolation, both rewards, and the collected sidecar minutes log.

Separate verifier tests are baked by `tests/Dockerfile`. A plain explicit
`verifier.environment.docker_image` suppresses test upload: it must already
contain `/tests/test.sh`. The first probe run found that packaging requirement;
only the corrected second run passed.

## Observed 2026-10-14

Boat VM `bx_xc2d62xx` forked from `harbor-ready`, Harbor 0.24.0, Docker 29.7.0.
Two rewards 1; zero exceptions. Both questions reached the sidecar; final log
contains two records charging 5 minutes each. The monitor retained PID 34 and
its UUID, with 88 heartbeats, maximum gap 0.251s. It produced 74 heartbeats
through the first separate verifier's full 18.480s interval. Trial took 66s.
Evidence: `results/infrastructure/2026-10-14-lifecycle/summary.json` plus the
sanitized trial result, per-step artifacts and verifier logs.

## Contract for the cleanroom builder

- Put `ask-human` on PATH inside the contestant image; set `ASK_STEP` for every
  agent step. Its default URL is `http://responder:8080/ask`. Pass the absolute
  host `RESPONDER_DIR` to the overlay; keep fact sheets on the responder only.
- Declare the sidecar artifact `/logs/responder/questions.jsonl` with
  `service = "responder"`. It is cumulative across steps. Count the final
  snapshot once, or deduplicate records; summing every step snapshot double
  counts previous questions. This smoke has one then two records, 10 total
  charged human minutes. Five minutes per question is a configured charge,
  not measured wall time.
- Start the monitor detached with stdio redirected to files, preserving its
  identity and usage/actions timestamps under a declared `/app` artifact.
  Harbor keeps the contestant environment alive through nonfinal separate
  verifiers. Artifact snapshots are collected before verification; activity
  during verification first appears in the next step's artifact.
- The last step stops main before sidecar evidence collection and its separate
  verifier. Do not expect the monitor to run during that final verifier or
  after trial teardown. No promise is made across VM snapshots/reboots.
- Monitor work during nonfinal verification is real work outside the agent
  CLI's token window: budget its calls and record wall time/action timestamps.
  The smoke deliberately tests continuing operation; pausing would require an
  explicit policy/hook.

This proves an oracle-spawned detached process and the CLI channel. Codex CLI
child cleanup, MCP tool registration, live/model owner answering, and a nested
Docker monitor remain separate checks. The probe makes no claim about them.
