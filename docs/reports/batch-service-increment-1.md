# Batch service increment 1: founder migration command

Implementation reviewed at 8b3ed75 on factory-simplify a3bb9dc.
Design PASS: batch-service-design-4.md / interfaces-design-9.md.
Diff PASS: batch-service-diff-2.md; new installer contract also approved there
and copied verbatim to interfaces-design-10.md. No blocking findings remain.

Validation: `uv run --with numpy --with scipy python -B tests/run.py` —
135 scripts, zero failures. Focused migration script: 13 tests pass.
Real inventory --dry-run passes without prompt or writes. No real decryption.
No Murphy rows closed. Live-test spend: $0 model / $0 incremental infra.
Reviewer-agent usage is outside the live-test receipts and unmeasured here.
No VM mutations: only ciphertext/public metadata were read. The divergent VM
ciphertext and three encrypted wrappers/public cards were staged in Mac cache
with digest checks; no private identity left either host.

## Founder command after parent merge

From repo root, first dry run:

```sh
tools/migrate-legacy-checkpoints.sh \
  --plan docs/reports/batch-service-migration-plan-20261030.json \
  --plan-sha256 bac461d88e3b7f413c28ea55a5e70aa83a1fe56b336153d965ac23c3e1707aa6 \
  --dry-run
```

Then repeat without --dry-run. Python3.11+, age, age-keygen and Mac caffeinate
are required. One hidden founder identity prompt; never enter a key in chat.
The plan has 48 unique archives across30 unkeyed prefixes plus16 key rewraps.
All originals and active pointers stay unchanged. Summary is migrated/failed/
skipped; exit0 complete, exit1 per-entry failures, exit2 invalid preflight or
interruption. Rerun the exact command after a partial failure.

The absent-card 9d2b0e input stays non-current. Both divergent18681d checkpoint
versions stay historical; its card-bound final is the eligible source. Every
new record carries vm_unwrap_verified:false until agent-owned VM qualification
proves unwrap/decryption, R2 integrity and catalog activation in a later increment.
No founder migration or activation has run yet. No batch enablement yet.

Next: B money authority/context installer and generation/journal core; then
reviewed holder/restore addendum and Codex addendum. D can use interfaces§8's
exact job_config.install(c,args) attributes/verified RAM config contract now;
the implementation remains a fail-closed prerequisite. G10 double-pool checks
and owner-wait/conservative-charge evidence remain required in live E2E.
