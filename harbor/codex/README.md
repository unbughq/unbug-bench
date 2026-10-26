# Codex contestant infrastructure

Uses Harbor **0.24.0** native `codex` adapter, Codex CLI **0.162.1**, model
**openai/gpt-6.1-sol**, reasoning effort **high**, hosted web search **disabled**. These are explicit run pins, not
a claim that an alias is an immutable model snapshot. No Claude settings change.

```sh
rtk proxy uv tool install harbor==0.24.0
rtk proxy python3 harbor/codex/run.py --job-name codex-smoke-unique
```

The default task is only a tiny infrastructure smoke: one instruction asks Codex to
write and read a file through its shell tool, then Harbor runs a byte-exact verifier.
It never starts Medusa, a practice attempt, or an exam. Results stay outside the repo
at `/tmp/unbug-codex-jobs`. `--dry-run` validates the resolved setup without model calls.

The launcher requires an existing `~/.codex/auth.json` with `auth_mode=chatgpt`,
tokens, and no API key (override path with `--auth`). It removes inherited OpenAI,
Codex, Azure OpenAI and LiteLLM overrides from the Harbor child environment and
sets only `CODEX_AUTH_JSON_PATH`. Harbor copies that file into an ephemeral
`/tmp/codex-secrets/auth.json`, symlinks it under its isolated `CODEX_HOME`, then
removes both locations in a `finally` cleanup. Docker teardown also deletes the
container. Credentials are never put in command arguments, config, images or this
repository. The host credential file is not modified. No host Codex config or
skills are passed. Avoid debug dumps of environment or auth; raw agent logs belong
outside the repository. Subscription limits still apply.

Harbor uses `codex exec --model gpt-6.1-sol` and `--ak version=0.162.1` installs
that CLI release or verifies a matching preinstallation. The adapter enables
`unified_exec` and bypasses approvals/sandbox inside its isolated task container.
It captures CLI session model/version and token counts in `agent/trajectory.json`
and `result.json`. Harbor cost is a LiteLLM list-price estimate when available;
it is not the subscription charge and may be absent for an unknown model.

For a completed smoke trial, a sanitized evidence helper is available:

```sh
rtk proxy python3 harbor/codex/summarize.py /tmp/unbug-codex-jobs/JOB/TRIAL
```

Inspect the helper output before saving it: it includes tool arguments, which are
safe for this fixed smoke but may contain task data for other tasks. It is not a
general secret scrubber. The tiny smoke proves basic integration only; full bench
setup, nested Docker, proxy egress and between-step behavior need separate checks.

A future approved practice run can explicitly select `--task harbor/medusa-oversell`.
That spends subscription usage and runs the full case; do not use it as a smoke.
The launcher keeps the same fixed CLI, model and effort pins for either task.

Authentication reference: [official OpenAI documentation](https://developers.openai.com/codex/auth).
Harbor behavior above was checked against the locally installed 0.24.0 adapter.

The smoke image tag and Harbor’s nvm/apt installation are not digest-pinned; freeze
those inputs before a scored run. The benchmark box image already has Node, but
Harbor still invokes its installer unless the exact Codex version is preinstalled.


## Executed smoke, 2026-10-14

Local Docker Desktop (Docker 29.7.2, Linux arm64), one Harbor trial, **reward 1,
zero exceptions**, 2m49s total including image/setup. Codex wrote the exact file,
read it back, and the verifier passed. Actual session and result both report
Codex 0.162.1 / gpt-6.1-sol. Tokens: 28,633 input (26,368 cached), 121 output.
Harbor estimated $0.0083768 at list price; subscription auth was used, so this is
not an API bill. Only this one model turn was run; the dry-run spent no model usage.

[Sanitized result, actual tool call and usage](evidence/smoke-20261014.json) and
[verifier output](evidence/verifier-20261014.txt) are retained. Raw result directory:
`/tmp/unbug-codex-jobs/codex-smoke-20261014/smoke__C3BWp9a`.
Harbor logged removal of its temporary credentials and Codex home; the trial
container was gone after completion. No full practice/exam run or Claude call ran.
The CLI emitted a harmless warning about helper aliases under `/tmp`; its shell
write/read still succeeded. Launcher dry-run, Python compile and API-key rejection
checks also passed.

Hosted web search is disabled with `--ak web_search=disabled`: model-hosted retrieval
would occur outside the audited contestant network. Public retrieval must use local
tools through the logging proxy. This hardening was dry-run validated after the
recorded smoke; it did not trigger another model call.


## Combined two-step smoke

This additionally uses the actual Codex child process to start a detached heartbeat,
asks the canned human CLI once each step, and curls `https://example.com`. A fresh
separate verifier waits five seconds at each checkpoint. The second step checks
the heartbeat identity survived the first CLI exit and verifier window. It reuses
the lifecycle probe scripts; the benchmark application never starts.

```sh
rtk proxy python3 harbor/codex/run_combined.py --job-name codex-combined-unique
```

The wrapper freezes sidecar sources into a unique temporary directory and records
SHA256 hashes before startup. This prevents mitmproxy auto-reload if repository
files change during a run. It then places the final joint overlay last: it attaches the responder only to the
isolated network and adds its hostname to `NO_PROXY` for direct local CLI contact.
The responder has no egress, uses canned answers, and receives no OpenRouter key.
This image derives from the existing bench box, which must already be built; it
preinstalls the pinned Codex release and includes only the small action/heartbeat
helpers. Start it only for an approved infrastructure smoke: it makes two model
sessions. Its results can be validated with `summarize_combined.py TRIAL_DIR`.

Executed 2026-10-14: the stable combined trial passed **both rewards 1, zero
exceptions**, 2m35s total. The same heartbeat PID/run UUID survived both real CLI
sessions and the first separate verifier: 52 beats inside its 13.253s Harbor
window, 341 total beats, largest gap 0.303s. Both fresh verifiers waited at least
five seconds. Two canned questions charged 10 simulated human minutes; both
example.com HTTPS GETs were collected as sidecar artifacts. Live OpenAI/ChatGPT
and oaiusercontent model-support traffic was CONNECT-only, with no paths/bodies
in the audit. Both sessions report CLI 0.162.1 / gpt-6.1-sol. Input 84,122
(63,104 cached), output 490; Harbor list-price estimate $0.0532464, subscription auth.

[Combined evidence](evidence/combined-20261014.json) and
[frozen sidecar hashes](evidence/combined-sidecar-hashes-20261014.json) are retained.
Raw trial: `/tmp/unbug-codex-jobs/codex-combined-stable-20261014/combined__WbiKNMZ`.
Own containers and injected credentials were removed after completion. No Medusa,
practice or exam run, Claude call, or live responder model call occurred.

An earlier combined attempt was cancelled after the proxy addon was edited through
its live bind mount, auto-reloaded and exited via its fail-closed audit gate during
the second Codex turn. This was an infrastructure hot-reload failure; its
[failure record](evidence/combined-infrastructure-failure-20261014.json) and raw
logs remain, and the retry uses frozen source copies. It is not omitted from the
execution history. The final focused proxy Docker regression also passed,
including TLS SNI/CONNECT and HTTP Host mismatch attacks:
[review evidence](evidence/webproxy-review-20261014.json).
