# Bench infrastructure status — 2026-10-14

Scope: the six operator tasks authorized after the provider switch to Codex.
No Claude call, full contestant practice attempt or scored experiment was started.
The founder's clean-room build and the existing sealed case build were left alone.

1. **Ask-human: passed inside Harbor.** The CLI reached the separate canned
   responder in deterministic and actual Codex probes. Sidecar artifacts were
   collected. The two-session probe logged two questions charging ten simulated
   human minutes. That is a configured charge, not time spent by the founder.
   Live/model-backed answering has not been exercised.

2. **Monitor lifetime: passed with actual Codex.** Same process identity across
   both sessions; 341 heartbeats, maximum gap 0.303 seconds. Fifty-two heartbeats
   span the first separate verifier's 13.253-second lifetime. The final step stops
   the contestant environment before its separate verifier. Background usage must
   be logged separately. See [public builder contract](BUILDER-CONTRACT.md).

3. **Boat stress recalibration: passed.** Dedicated default VM, 4 vCPU/8 GB,
   separate from the sealed builder. Plain app oversold 30/30; refuse-all passed
   0/30 and allowed normal orders in 0/30; reference protection passed 30/30.
   All ninety runs had zero harness errors and zero invalid results. The four core
   source fingerprints in every record match the local source. Runtime image IDs,
   full run records, summary and verified evidence archive are retained under
   `results/infrastructure/2026-10-14-boat-calibration/` and `results/runs/`.

4. **Codex adapter: passed.** Harbor 0.24.0, Codex 0.162.1, actual session model
   gpt-6.1-sol/high, ChatGPT subscription auth. Simple tool-action smoke and combined
   two-session smoke passed; zero exceptions in the completed combined trial.
   Hosted search is disabled. The model is an alias, not an immutable weight
   snapshot. [Commands and sanitized evidence](codex/README.md).

5. **Web audit: passed.** Trusted HTTPS paths, stripped query secrets, API/support
   TLS passthrough, direct main/nested egress denial, proxy-down failure, and Harbor
   sidecar artifact collection. A discovered CONNECT/SNI bypass was fixed and
   independently regression-tested. An immutable staging copy prevents addon hot
   reload during a run. Actual Medusa npm install, image build, migrations, seeding,
   two resets and both health endpoints passed through the proxy (400.36 seconds;
   1,074 npm HTTP requests audited). [Network scope and probes](webproxy/README.md).

6. **Freeze mechanism: passed; binding experiment lock pending.** Source archive
   and hashes include directories/permissions and empty guards. Verification rejects
   added, removed or changed inputs, inconsistent archives and runtime image-ID
   changes when `--check-images` is used. A guarded command checks before and after
   execution. Eight automated checks and independent focused checks passed; a real
   whole-repository snapshot and runtime-image check also passed. The repository
   has no commit yet. [Commands and remaining lock conditions](FREEZE.md).

## Evidence and repeatable checks

- `results/infrastructure/2026-10-14-lifecycle/`: oracle lifecycle and question log.
- `harbor/codex/evidence/combined-20261014.json`: actual two-session Codex result.
- `harbor/codex/evidence/combined-infrastructure-failure-20261014.json`: initial
  proxy hot-reload interruption, retained separately from the successful retry.
- `results/infrastructure/2026-10-14-medusa-proxy/`: full Medusa network/build proof.
- `tests/live/harbor/test_audited.py`: real no-model launcher, health, network and artifacts.
- `tests/integration/test_freeze.py`: drift/archive checks; eight tests passed.
- `tests/live/harbor/webproxy/test_webproxy.py` and `test_harbor.py`: network regressions and
  collection, no model calls. `test_medusa.py` runs a cold full application setup.

Raw Codex logs and credentials are not in this repository. Sanitized smoke evidence
is retained; live credential files were removed by Harbor teardown. Infrastructure
tests used independent disposable Compose projects and did not reset the host bench.

## Before scored runs

The clean-room Unbug build, accepted sealed cases, final thresholds/budgets/tools,
model/CLI configuration and independent outside review still need to be fixed into
the full experiment manifest. Capture deployed images on the scoring host and retain
those images. Commit/tag the agreed source and publish the final digest externally.

The proxy audits the supported network path, not privileged container escapes,
provider-side retrieval, cached knowledge or arbitrary external tools. Model API
payloads and owner facts remain private. Custom agent wrappers must disable hosted
retrieval just as the native launchers do. Local Docker/Codex/Medusa integration was
tested on arm64; the native bench and oracle lifecycle were tested on boat amd64.
Full scored multi-arm integration is not established by these infrastructure smokes.


Factory continuation update (2026-10-14): the local `bench-20261014` freeze candidate predates
factory budget/resume changes and must be regenerated before any binding experiment lock.
The core traffic/checker calibration files were not changed. The sealed worker's benchmark
fingerprint was separately matched to a fresh `bench-env` template before continuation.
