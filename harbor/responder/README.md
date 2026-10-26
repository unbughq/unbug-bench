# ask-human responder

Minimal "ask the human" channel. Contestant runs `ask-human "question"`;
a `responder` sidecar answers, logs, and charges human minutes.

## Run

```sh
# responder (canned answers for dry runs)
ANSWERER=canned CANNED_MAP=canned.json RESPONDER_LOG=/tmp/questions.jsonl \
  python3 harbor/responder/responder.py
# ask (another shell)
RESPONDER_URL=http://127.0.0.1:8080/ask ./harbor/responder/ask-human "question text"
# self-test
python3 tests/harbor/responder/test_responder.py
```

With Harbor (overlay only adds the sidecar; contestant sees
`http://responder:8080/ask`):

```sh
RESPONDER_DIR="$PWD/harbor/responder" harbor run -p harbor/medusa-oversell \
  --extra-docker-compose harbor/responder/docker-compose.responder.yaml ...
```

`RESPONDER_DIR` must be absolute: Harbor sets the Compose project directory to
the task environment, so a relative bind would mount the wrong directory. The
sidecar healthcheck gates Harbor startup. Declare the sidecar artifact in the task
to collect charged minutes:

```toml
artifacts = [{source = "/logs/responder/questions.jsonl", destination = "responder/questions.jsonl", service = "responder"}]
```

`ask-human` is on PATH in the box image (`harbor/images/Dockerfile`, box stage).

Live owner: `ANSWERER=model` with `FACT_SHEET=/path/to/fact-sheet.md` (the model
sees the sheet; the contestant never does) and any OpenAI-compatible endpoint:
`ANSWER_BASE_URL`, `ANSWER_API_KEY`, `ANSWER_MODEL` (pinned id), temperature 0.
`harbor/run-audited.py --answerer model` defaults them to DeepSeek on OpenRouter
(`https://openrouter.ai/api/v1`, `deepseek/deepseek-v4-pro`, key read from the host file
`$ANSWER_API_KEY_FILE`). Moved off OpenCode Go on 2026-10-16: Go's weekly cap stalls
runs, and its key came through boat's paid relay. The OpenRouter route is not yet called.
Model answers add `model` and `usage` to the log line.

## Logging / minutes

Each answered question appends one JSON line to `$RESPONDER_LOG`
(default `/logs/responder/questions.jsonl`):
`{ts, step, question, answer, minutes_charged}`.
Human minutes = sum of `minutes_charged` = count x `$MINUTES_PER_QUESTION`
(default 5). Failed/unknown-responder calls log nothing and exit non-zero.

## Unverified

See `../smoke-lifecycle/README.md` for the deterministic Harbor lifecycle probe.
Live answerer on Go checked 2026-10-15 on host, in the compose overlay and behind
the webproxy (`results/infrastructure/2026-10-15-live-answerer/`); a full Harbor
run with `ANSWERER=model`, OpenRouter, and MCP registration are unchecked.
