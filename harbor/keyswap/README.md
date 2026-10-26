# Subscription key swap

Contestants use HTTP `keyswap:8090` and dummy credentials; real credentials are
bind-mounted only into a separate sidecar. The relay uses Python stdlib in the
existing pinned mitmproxy image, verifies upstream HTTPS, and allows only the
method/path pairs in `ROUTES`. No configurable upstream, CONNECT, redirect,
generic auth endpoint, or host/header-selected destination is exposed.

Claude uses `/anthropic/v1/messages` and `/anthropic/v1/messages/count_tokens`.
The relay replaces `Authorization`, drops `x-api-key`/cookies, preserves the
client's beta headers, and adds `oauth-2025-04-20` if absent. Verified by inspection
of the published **2.1.299** native bundle: `ZU()` reads the env token as the OAuth
access token; `wxs()` selects `apiKey:null, authToken:oauthAccessToken` for
subscribers, and the SDK constructs Bearer authorization. See also
[Claude gateway authentication](https://code.claude.com/docs/en/llm-gateway).

Codex uses `/chatgpt/backend-api/codex/{models,responses,responses/compact}`.
`codex.toml` supplies both provider and ChatGPT base URLs and disables WebSockets,
using HTTP SSE. Harbor uploads `auth_mode=apikey` with a **dummy** API key in
`auth.json`; no real API key is used. Keyswap replaces Bearer authorization and
supplies `ChatGPT-Account-Id` from the real subscription auth file. This is an
API-compatible local transport shim, with subscription auth only at the relay.
Sources: pinned [provider implementation](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/model-provider-info/src/lib.rs),
[auth/refresh implementation](https://github.com/openai/codex/blob/rust-v0.162.1/codex-rs/login/src/auth/manager.rs),
and [official auth documentation](https://developers.openai.com/codex/auth).
The pinned binary's ChatGPT mode first requires workspace discovery and an HTTPS
backend origin; dummy ChatGPT auth plus a plain-HTTP base URL fails before a model
request. API transport mode avoids that discovery and was checked with the pinned
binary on loopback in a network-disabled container. Codex emits `store:false` in
its Responses body in either mode. Live backend acceptance of this wire format
with a real subscription still needs the smoke below; this is not claimed tested.

Keyswap refreshes at JWT expiry minus 60s or on one upstream 401, using JSON
`client_id`, `grant_type=refresh_token`, `refresh_token` at the fixed
`https://auth.openai.com/oauth/token`. It persists rotated credentials before
retrying; a repeated 401 becomes 502, keeping auth recovery in the relay.
Threads and sidecars sharing the same auth file inode serialize via locks.

Responses stream with `HTTPResponse.read1`, flush each available chunk, and use
connection-close framing. Requests are capped at 32 MiB; chunked uploads and
duplicate content lengths are rejected. Only safe request/response headers pass.
Non-2xx bodies/headers and exception text are discarded, preventing auth echoes.

The relay appends fixed upstream method/path metadata (no queries, auth or bodies)
to the same project `webproxy-log:/log/web.jsonl` volume before forwarding,
including refresh requests. Audit failure prevents forwarding. This records direct
local relay traffic without sending secrets through another TLS terminator.
The contestant has neither the audit volume nor secret mounts. Ordinary web
traffic continues through webproxy; boat.dev and its subdomains are explicitly
blocked for HTTP and CONNECT and removed from TLS passthrough.

## Host setup

Put a `claude setup-token` token in a private plain-text file and/or a dedicated
copy of ChatGPT subscription `auth.json` outside this repo. Never pass token
contents via argv or environment. Set paths only:

```sh
export KEYSWAP_CLAUDE_TOKEN_FILE=/secure/keyswap/claude-token
export KEYSWAP_CODEX_AUTH_FILE=/secure/keyswap/auth.json
```

Claude's file is read-only. Codex's file **must be writable** by the relay and
must be owned exclusively by this relay deployment: don't share with a logged-in
CLI that atomically replaces the inode. Refresh rotation changes the host file;
keep a secure backup/re-login path. A single-file bind mount requires in-place
write + fsync rather than rename; a crash during writing can corrupt it. Mounting
a whole personal `.codex` directory would expose unnecessary host data.

`run-audited.py` stages immutable relay code/config, mounts only the relevant
secret for each agent, removes inherited provider auth overrides, and passes
only placeholders to Harbor. Oracle/nop require no keyswap or secret file.
`bin/run-exam --codex-auth PATH` also selects the relay-owned auth file; the env
path is its default. All A/B/C/C0 Claude arms use the same local OAuth wiring.
Old launch scripts must provision these files/paths; raw token env vars from
boat are no longer accepted by the audited launcher. No launch scripts changed.
The older `harbor/codex/run.py` standalone launcher still uploads real auth;
use `run-audited.py` for this boundary.

## Offline checks

```sh
rtk proxy python3 -m unittest discover -s tests/harbor/keyswap -v
rtk proxy python3 tests/live/harbor/keyswap/test_docker.py
rtk proxy python3 tests/live/harbor/webproxy/test_webproxy.py
rtk proxy python3 tests/bench/test_run_exam.py
```

Optional pinned CLI wire check (Linux binaries must be downloaded separately):

```sh
rtk proxy python3 tests/live/harbor/keyswap/test_clients.py /absolute/linux/codex /absolute/linux/claude
```

Checks versions 0.162.1/2.1.299, dummy auth, request URLs and OAuth beta headers
against loopback with Docker `--network none`. It deliberately returns synthetic
503 responses after observing the request; it does not claim model completion.

Docker test: both networks are `internal`, fake TLS peers own the three allowed
DNS names, and only a public test CA reaches the relay. It exercises the generated
compose overlay, both model routes, host-file refresh persistence, shared audit,
boat denial, and missing secret files in the contestant. No provider is called.

## One live check still required (each subscription)

Not executed automatically. These spend subscription usage, use only the tiny
shell-write smoke, and require the bench box image + Harbor 0.24.0. From repo root,
after setting the two file paths above:

```sh
rtk proxy python3 harbor/run-audited.py --agent claude-code --job-name keyswap-claude-live \
  --task harbor/keyswap/smoke -- --model claude-opus-5-5 -n 1 -k 1 \
  --ak version=2.1.299 --ak reasoning_effort=high
rtk proxy python3 harbor/run-audited.py --agent codex --job-name keyswap-codex-live \
  --task harbor/keyswap/smoke -- --model openai/gpt-6.1-sol -n 1 -k 1 \
  --ak version=0.162.1 --ak reasoning_effort=high
```

Use unique job names on retries. Add `--dry-run` before `--` for configuration
validation without usage. Inspect `/tmp/unbug-audited-jobs/JOB/*/result.json` for
reward 1 and pinned CLI/model, and collected `web/web.jsonl` for model-route
requests. Never publish the real auth file. A naturally expired dedicated Codex
auth file also tests real refresh; synthetic expired-token/401 rotation is covered
offline. Account policies, backend/client header changes, and OAuth acceptance
with a local base URL need this live check. Additional model endpoints/WebSockets
fail closed until explicitly implemented.

The relay is a subscription capability: a contestant can make allowed calls and
consume quota. It cannot read the token through this API. It has no per-agent
budget enforcement. Existing privileged DinD/host-kernel escape risks remain;
this is container mount separation, not a hardened hostile-code VM boundary.
