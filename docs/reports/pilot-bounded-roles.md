# Pilot bounded roles: offline report

Land17 `5b3cd0b` was merged before this work. A real batch-runtime/Store test
with synthetic authenticated authority returns `ProviderWait('unbounded_route')`
for Codex before CLI execution. The parent chose non-Codex pilot roles; Codex's
safe batch refusal remains, and a real bounded Codex gate is a later increment.

For future batch ID `b-real-pilot`, holder admission checks all three job
templates and the selected resolved job before replay or money/operation writes.
Every job must use the five exact flags/routes in `pilot-bounded-roles.md`; the
easy calibrator is DeepSeek, independent of the MiniMax writer. A malformed
plan receives `pilot roles must use pinned bounded routes` from the offline
qualifier. The legacy money authorizer refuses that batch ID so it cannot bypass
the holder check while the holder is disabled. The future pilot manifest and its
activation do not exist yet; they must use that ID and these pins. Practice,
other IDs, the existing shared paid cap, and the proposed $20/case and $60/batch
model caps are unchanged. No Murphy row is closed; row 30 remains open.

The expected **whole-case** cost delta is unknown: saved receipts do not provide
matched complete role work across models. One retained Codex preflight receipt
prices at $0.0042488; pricing identical token counts at Opus 4.5 compact rates
gives $0.012894, a hypothetical +$0.0086452 for that invocation, not a case
estimate. DeepSeek instead of MiniMax for easy calibration raises its maximum
reservation by $0.48440512 per invocation, not its expected charge. The paid
OpenRouter roles can consume the existing shared credit cap; no top-ups are
authorized. Real usage, cache behaviour and model quality may differ.

Offline targeted results: `test_pilot_bounded_roles.py` 5 tests passed,
including real role selection, Store leases, dedup and the parser alias matrix;
`test_model_call_maxima.py` 26 tests passed. Provider/authority bindings in
these tests are synthetic, except for the retained public receipt/text. No model,
worker, cloud, paid call, credential, or practice deployment was used.

Claude and the free OpenCode reviewer hit usage limits. A fresh Codex
gpt-6.1-sol reviewed the design because the writer is gpt-6.1-terra; design
round 2 passed, with both review files under `docs/reviews/`.
The full parallel suite and fresh diff review follow.

## Full-suite validation

Source 191337eb52646013fc83c90ebb46dbf94c2362b1 passed the parallel full suite:
186 scripts, zero failed, exit 0, from 2026-11-03T19:54:37Z to 20:02:18Z.
Record: pilot-bounded-roles-suite-20261103T195437Z-7b2839a0.json and .log.gz.
The source tree and compressed/uncompressed log hashes were checked. No lockf,
pass-cache reuse, test-limit changes, live calls, workers, or credentials.
The fresh diff review is the remaining gate.

Fresh diff review round 1 passed with no blockers or majors; saved verbatim in
`docs/reviews/pilot-bounded-roles-diff-1.md`. Claude and the free OpenCode model
were rate-limited, so the approved fresh Codex gpt-6.1-sol fallback reviewed the
gpt-6.1-terra writer. One optional test nit remains open: duplicate identical
role pins are rejected by production, as the reviewer checked, but the committed
duplicate test uses a different route and does not isolate that condition.
No Murphy row closes. The separate practice preflight branch must land before
any re-pin or retry, and a bounded Codex gate remains follow-up work.
