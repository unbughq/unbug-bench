# Case factory

`run.py` builds one case, runs the qualification gates and seals the evidence.
[FACTORY.md](../FACTORY.md) defines the scientific rules;
[ARCHITECTURE.md](../ARCHITECTURE.md) maps the runtime modules.

## Entry points

- `python3 factory/run.py --help`: one worker's case build and gate options.
- `unbug status [BATCH]` / `unbug report [BATCH] --json`: read the controller's scorecard.
- `bin/unbug --config CONFIG --help`: controller-local administration through its private socket.

Use the approved batch manifests and release qualification when launching real
workers. A source change does not update deployed pins or authorize paid work.

## Failures and alerts

The campaign guard (`factory/durable/guard.py`) runs every minute. A failed check is retried
and marks the batch degraded, which pauses new attempts and stops nothing. Only the deadline,
the money ceiling and a confirmed Boat allowance or rate breach are hard stops.

A hard stop pauses new attempts and gives steps in flight a checkpoint grace to record (10
minutes; set `UNBUG_CHECKPOINT_GRACE_S` in `/etc/unbug/alerts.env`). The guard then stops the
controller and deletes the workers, at once if nothing is in flight. Unrecorded work becomes an
ordinary retry and is never scored. To resume, fix the cause, delete
`<state_dir>/guard/status.json` and start the controller.

`unbug status` shows guard health, recent failures and every `NEEDS YOU` line. To also get
each alert as a message, put `UNBUG_ALERT_WEBHOOK=<url>` in `/etc/unbug/alerts.env`, mode 600.
The guard POSTs `{"text": "..."}`, which Slack-style incoming webhooks accept.

`bin/failure-drill` proves the batch survives these failures offline, with no money spent.

## Operator client

`python3 bin/install-unbug` installs a standalone read-only client in `~/.local/bin`.
It is independent of the source checkout and needs only Python 3 and SSH. Save this
connection shape in `~/.config/unbug/client.json`, replacing the example paths, and
set its permissions to `600`:

```json
{
  "ssh": ["ssh", "-i", "/path/to/key", "-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes", "user@controller"],
  "command": ["/path/to/venv/bin/python", "/path/to/bin/unbug", "--config", "/path/to/controller-config.json"],
  "batch": "b-current"
}
```

The profile contains connection arguments and paths, never credential contents or
the controller configuration itself. `unbug --connection FILE status` selects another
connection. On the controller, existing `--config` operator commands are unchanged.
Status/report read persisted records even when the controller is stopped. The
controller configuration may set `status_service_unit` for a custom service name;
otherwise service-state checks use `unbug-durable.service`.

## Execution

`run.py` retains scientific gate criteria. `gate_pipeline.py` owns sequencing and
reuse; `gate_attempt.py` handles operational attempts; `calibration.py` owns
calibrator receipt reuse and completion. `case_contract.py` validates the case
structure and declared ingredients. `model_runtime.py` handles model calls, while
`run_artifacts.py` collects, seals and cleans up evidence.

Factory bench parallelism is opt-in with `--bench-workers N` (default 1).
Additional slots use separate Compose projects, databases, ports and seed IDs.
Eligibility checks memory limits and service isolation; unsupported layouts stay
serial. Each trial still resets its own database and verifies the baseline.

G10's strong and easy calibrators can run concurrently on Linux when separate
identities, homes, bench slots and firewall walls are available. Strategy steps
and information-sensitive reviews retain their sequencing. A completed atomic
receipt counts as an attempt; an interrupted workspace does not.

## Check changes

```sh
python3 tests/run.py factory bench integration
```

See [tests/README.md](../tests/README.md) for the full suite and explicit live
probes. Offline checks do not prove Docker behavior, model-provider behavior or
release readiness. Preserve the pinned deployment and holder authentication
boundaries when qualifying a new release.
