# Smoke stop-capture focused handoff

Base957fdf1 includes merged82c1617 in the existing prepared worktree. No production
source edit/deployment, control-VM/provider/model call, secret access/decryption,
worker launch, ledger/debit/writeoff, push/main or factory-simplify integration.
Root's public smoke observations were read locally and left unchanged.

The live stage remains UNKNOWN: stop request was saved, meter files absent and
ordinary deletion followed within15s of the original120s window. Stop-request is
an allowlisted projection, not a saved full action response. Pre-existing stopped
DTO does not establish fresh-stop behavior. Wrapper/FD/RPC/shape hypotheses cannot
be distinguished retrospectively from these artifacts. No live root cause claimed.

Confirmed OFFLINE defects: immediate info.stop.id dereference fails on authored
async null identity; immediate stopped assertion fails on delayed state. Regressions
were red. Capture now polls within the same original deadline, reuses a saved stop
request without another stop, and rejects superseded identity at first observation,
by-ID status or subsequent info. No force/new generation/window/billing fallback.

A bounded atomic capture-stage.json records only fixed stage/outcome/error_class,
worker/retirement identity and observed_at. No exception string, provider diagnostics,
environment, commands or arbitrary response keys enter it. First failure persists
across original-window retries; diagnostic receipt grants no authority. Existing
proof validation/retained-proof refusal, exact deletion intent and unknown holds stay.

Focused: retirement21 Mac (3 explicit Linux-only skips), local Linux21 with real
wrapper/kernel WRITE FD plus AUTHORED fresh-stop transport; settlement14 passed.
Tests cover id-only request, null identity, pending status, delayed stopped state,
null/malformed DTO, transitional supersession, saved-request no-repeat and fixed
public error labels/no secret sentinel. Real retained stopped DTO is only the final
observation; fresh transitions are AUTHORED. No raw bytes reconstructed as real SHA.
Design reviews1/2 and diff reviews1/2/3 saved verbatim. All blockers accepted/fixed.
No full suite run, per root request to diagnose contract before another long cycle.

Remaining: root integrates and decides full suite/qualification; actual live failure
stage still unproven. Future authorized qualification must show freshly requested
stop through same-ID completed/stopped meter/recheck before deletion and exact
settlement. This task authorizes no third worker, practice or replacement.
bx_bykfqbyn's reserved0.036 remains UNKNOWN with no meter proof; no conservative
debit is authorized for it. Existing bx_z4wktrbn approval is not generalized.
new-boat-stop-capture-1 and all prior relevant Murphy rows remain open.
