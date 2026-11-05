# Case factory

`run.py` builds one case, runs the qualification gates and seals the evidence.
[FACTORY.md](../FACTORY.md) defines the scientific rules;
[ARCHITECTURE.md](../ARCHITECTURE.md) maps the runtime modules.

## Entry points

- `python3 factory/run.py --help`: one worker's case build and gate options.
- `python3 factory/batch.py --help`: build a pinned public batch release.
- `bin/control-vm --help`: provision and operate the control VM.
- `factory/launch.sh`: launch or resume an approved worker through the holder.
- `factory/collect.sh`: collect worker evidence through the existing control path.

Use the approved batch manifests and release qualification when launching real
workers. A source change does not update deployed pins or authorize paid work.

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
