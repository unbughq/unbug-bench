# Cheap-route maxima validation

Implementation base: e26afc6 (accepted Claude tariff and gate wall). No production
Claude rates, D accounting modules, pilot_wall, historical ledgers or launch path
are changed. No merge, paid provider call or new Boat worker.

## Focused and native proof

- `test_router_cheap_maxima.py`: 7 tests, passed (raw quote fidelity and exact
  profiles, real sessions/$3 accountant fit, closed request schema/provider
  controls, response completeness/unknown retention, concurrent refund waiting
  and platform guards, saved native evidence, real loopback key custody).
- `test_model_call_maxima.py`: 21 passed; `test_model_call_gate_wall.py`: 8 passed;
  `test_stream_d_runtime.py`: 21 passed; `test_model_runtime.py`: 3 passed.
- OpenCode **1.19.0**, actual Linux arm64 binary, actual ModelRuntime, router Store,
  gate and D accountant, isolated `pilot` UID. Twelve Docker `--network=none`
  probes passed: basic, Bash tool continuation, automatic compaction and repeated
  503 exhaustion for each paid route, plus Exa for writer/stress_tester on both.
  Every model request went through the gate to a synthetic upstream. No model
  credential was read and no real inference request ran. Synthetic upstream key
  never enters the CLI environment; config uses a random invocation token.
- MiMo retries forward exactly 3 requests, DeepSeek exactly 2; the next request
  hits model_call_cap without forwarding. Every prior failed attempt remains
  unknown. D retains **1.710490600 / 1.174406120**, then ordinary reconciliation
  charges that entire unknown gap; repeating reconciliation is byte-identical.
  Normal/tool/compaction/search paths have no unknowns and settle their actual
  synthetic CLI usage. Invocation IDs and lease IDs remain bound throughout.
- Native Exa checks use only test-local DNS (`mcp.exa.ai` to loopback) and a
  test-only trusted synthetic certificate (`NODE_EXTRA_CA_CERTS` injected after
  validating the production environment). Actual CLI HTTPS requests reach
  **https://mcp.exa.ai/mcp**, call `web_search_exa`, carry no Authorization and
  use no API-key query parameter. No proxy or production destination override
  was added. The stub returns a synthetic search result before the next gated
  model request. External networking stays disabled.
- Native firewall subprocesses are explicitly faked here. This proves runtime,
  CLI, protocol and accounting wiring, not another live wall proof; actual Linux
  wall isolation is independently recorded in router-gate-wall-linux.json.gz.
  No claim is made about real provider acceptance or live model behaviour.

The durable `router-cheap-native.json.gz` contains the complete probe source,
its hash, binary hash, source hashes, commands, timestamps, synthetic transcripts,
request observations, receipts and before/after reconciliation ledgers. All twelve
runs used identical final probe and production sources. `router-cheap-maxima-evidence.json`
records SHA-256 for that archive and all real quote/source/card fixtures. Prices
and provider contracts were checked 2026-10-30; source evidence now also freezes
`tool/mcp-websearch.ts`, including the exact credential-free Exa URL.

## Real receipts and limitations

The saved paid sessions remain unchanged. Conservative gate replay fits every
session with one further worst request; longest MiMo has29 steps/1611966 input,
DeepSeek34/2568428. At the checked cached/uncached list prices, separate example
D ledgers fit $3: e15450 total0.8515172860, peak prior+next lease2.4924907220;
873d7f total0.6516037902, peak2.2841285566. This does not establish that an entire
historical case including Claude writers fits $3, nor authorize B's live run.

Provider controls and token contracts rely on saved primary evidence; offline
replies cannot establish provider enforcement. DeepInfra's discounted max_price
matching remains an availability risk. Nonzero cache-write quote invalidates
these profiles. Exact endpoint tags exclude flex/priority tiers. Provider changes
need requalification. Free OpenCode DeepSeek has no verified token contract and
no profile; existing paid-family fallback is preserved (documented in router.md
and interfaces.md). No batch override is introduced and no Murphy row is closed.

## Diagnostic failures retained honestly

The first native probe stopped with money_wait before any request because its
synthetic job binding used a case ID without `case-` and two different deadlines.
Correcting that test fixture made the real admission path pass. Initial legacy
model_runtime test expected the removed shared config and old .02/1.0 DeepSeek
rates; its config seam now uses the production inline builder, and expected
accounting uses current .14/.42 rates (1.12 for two synthetic steps). The D runtime
synthetic owner-cost assertion similarly changes from .02002 to .01956. Production
routing and accounting were not loosened to make either test pass.

## Full suite and review

Pending on the frozen implementation commit. Command:
`uv run --with numpy --with scipy python -B tests/run.py`.
Do not infer a full-suite pass from focused/native evidence. Fresh goldfish diff
review is also pending; design rounds1–3 and responses are already saved.
