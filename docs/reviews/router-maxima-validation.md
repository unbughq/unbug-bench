# Router maxima implementation validation

The implementation follows the design/readiness PASS in
`router-maxima-design-4.md`. This is offline implementation evidence, not
production qualification. Murphy rows 2, 3, 4, 20, 47 and 48 remain OPEN.

## Pinned Linux CLI exam

`tests/factory/fixtures/router-maxima-linux-gate.json.gz` saves verbatim commands,
results, binary hashes, source hashes, image configuration hashes and the public
Dockerfile for eight successful probes. Both Linux x64 (production architecture)
and ARM64 ran the exact Claude 2.1.299 public package. The fixture's recorded
source hashes match the tested implementation. Public package provenance is in
`router-maxima-cli-audit.json.gz`.

Every command used Docker `--network none`, the actual ModelRuntime, router
Store/start RPC, wrapper gate, `run_budgeted`, and the isolated-user `sudo` path.
Only public source and public binaries were mounted read-only. No host home,
credential directory, SSH material or Docker socket was mounted. A synthetic
OAuth value reached only a loopback fake provider; no real provider, model,
case or Boat worker ran. The harness replaces the fixed HTTPS connection in
test code only; production has no upstream URL override.

Each architecture passed all four scenarios:

| Scenario | Forwarded | Unknown | Result |
| --- | ---: | ---: | --- |
| Bash tool loop, hosted WebSearch rejected locally, continuation | 3 | 0 | done |
| Actual CLI retries after scripted 503, allowance exhausted | 2 | 2 | model_call_cap |
| Actual reactive client compaction, native compact_boundary | 4 | 1 | done, final_usage_known=false |
| max_tokens stop then continuation | 2 | 0 | done |

The retry scenario deliberately enables retries after the production environment
normalizer to prove they use the same gate. Compaction deliberately reduces the
test context threshold and scripts a context-length rejection. These overrides
are enumerated in the artifact; they are not production settings. Every
forwarded body used the exact allowed model, standard_only tier and at most
32,768 output tokens. Each scenario acquired and started exactly one Lease.

## Focused checks

`uv run --with numpy --with scipy python -B tests/factory/test_model_call_maxima.py`
passes 13 tests, including real-receipt repricing, lost CLI final/unchanged
partial booking, exact near-ceiling float booking, supplied/RPC cap tampering,
one-use start, interruption propagation, sticky exhaustion, close-before-send,
and missing/empty/malformed terminal provider usage retaining the whole W.
Existing router (36), runtime (3), provider routes (4), and launch manifest (2)
tests also pass.

## Full suite

The final implementation SHA and complete runner log are recorded here after
the required full run. Current rotation packages remain unqualified because
their non-Claude routes have no enforceable bound; B's separately authorized
practice-case exam remains required for production qualification.
