# MiniMax and small-profile isolation merge resolution

Merge: beb5aa7e131c6124041ad081db72fae738de88a2.
Parents: 893d268 and 6ffec7c. Review manual integration only with
`git show --remerge-diff beb5aa7`. A separate design is skipped for this small
mechanical resolution of already reviewed coverage; the merge message specifies
intent. No production conflict-resolution changes.

Preserved self.responses and saved real HTTPSConnection initialization; the
upstream retains optional Content-Length and per-mode release deadlines. The
shared helper retains model, real_cli and content_length; incoming MiniMax and
Claude-specific account, maximum, hold and provider mapping remain authoritative.
The cancellation event is attached before runtime.call for both modes.

HTTP tests cover every CLAUDE_PROFILES entry plus MiniMax across three framing
variants. TLS tests cover every Claude profile, including the new USD 3/USD 5
profiles, across four framing variants and execute the real local CLI process.
MiniMax remains the incoming simulated-CLI, plain-HTTP local protocol test; no
MiniMax TLS/real-CLI qualification is claimed. No provider call or spend occurs.

The TLS client request explicitly uses the selected underlying provider model;
the first focused run caught an incorrect body(model=...) call because body()
already defines model. It was corrected to dict(body(),model=provider), preserving
the helper's existing behavior. The passing focused run is 25 tests, 23.732s,
exit 0. Both existing and new profile hold/maximum assertions remain intact.
The Linux platform patch is limited to the MiniMax simulation; real Claude TLS
processes use the actual host platform. Real startup is still reported by
run_budgeted, and only the simulated branch calls on_started directly.

The register retains the scoped router TLS evidence, open escaped-descendant
row and incoming new-batch-auth-inputs-1 row. No row closes in this merge.
The full-suite log/JSON are uniquely named isolation-minimax-merge-suite-* and
record the tested commit plus unchanged test-module hash.


Full suite: exit 0, 165 scripts, zero failures, 1923.339 seconds.
Evidence: isolation-minimax-merge-suite-20261031T180428Z-3732a7ea.{log,json}.
The module hash was captured before execution and verified unchanged afterward;
all 25 model-call tests passed inside the full run (24.636 seconds). Three
unrelated suite skips are preserved in the evidence; this module has none.
