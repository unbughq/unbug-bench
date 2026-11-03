# Live preflight: every launch prerequisite in one read-only pass

## Problem

The 2026-11-02/03 practice run took 29 hours, stopped 10 times and made zero
model calls (`docs/reports/practice-run-20261102.md`). Every stop was a
prerequisite that could have been checked before step 1. Each was found live,
one at a time, and each one stopped the whole run:

| # | Stop | Kind |
|---|---|---|
| 1 | Boat auto top-up could not be verified | founder attestation |
| 2 | Claude account distinctness unprovable | founder decision |
| 3 | OpenRouter-key-in-router-RAM acknowledgement not on record | founder decision |
| 4 | Workers had no router URL, token or TLS trust | code gap (`new-worker-router-delivery-1`) |
| 5 | Mandatory "Go" pause | founder decision |
| 6 | Installed `boat 1.0.87`, pinned `boat 1.0.85` | environment drift |
| 7 | Codex login lifetime guard fired on a run with no Codex route | over-broad guard |
| 8 | Refreshed credential bundle not decryptable by the control identity | environment |
| 9 | Deployment needed an interactive sudo password | environment |
| 10 | Worker died in 3 minutes on a Docker name clash (`unbug-bench-postgres-1`) | code/image (fix on `t3/batch-service-control-vm`) |

`factory/practice_preflight.py` checks only offline files; its live items are
hard-coded `unproved`. The live checks live in a prose table that an agent
follows by hand, stopping at the first failure.

## Change

Add a `--live` mode to `factory/practice_preflight.py`, run on the control VM.
It performs every check below, **continues after failures**, and prints one
report: each check `pass`, `fail` (with reason) or `needs_founder`. Exit 0 only
if all pass. Every check is read-only: it makes no reservation, no worker, no
model call, writes no ledger, and spends $0.

| Check | Covers stop | How |
|---|---|---|
| `founder_decisions` | 1, 2, 3, 5 | The manifest lists the decisions it needs, such as top-up-off attestation, account waiver, router-RAM acknowledgement, Go and money cap. Each must be present in one decisions file with its text and date. Every missing one is listed together, so the founder answers once, up front. |
| `boat_cli` | 6 | Exact `boat --version` equals the `bin/boat-call` pin, and `boat-call list` returns a full inventory. Reuse `bin/boat-call`'s own check. |
| `boat_wallet` | 1 | Balance at or below the manifest's infrastructure cap. Top-up state comes from the attestation (no API reads it). |
| `sudo` | 9 | `sudo -n true` succeeds for the operator account that installs units (non-interactive escalation). |
| `credentials` | 8 | Every label the manifest's roles need decrypts in RAM with the control identity. Nothing is written or printed. |
| `login_lifetimes` | 7 | Lifetime covers TTL plus margin, **only for providers the manifest's routes use**. |
| `router` | 4 | Router service active, TLS reachable with the pinned trust. Build the exact worker environment `batch_holder.dispatch` would send, and verify it carries URL, token and trust. |
| `r2_openrouter` | — | R2 read access. OpenRouter credit at or above the manifest's paid ceiling. Both are existing step-2 checks, moved here. |
| `image_startup` | 10 | Boot the pinned worker image's Compose project in local Docker under a unique project name. Run `run.py` startup to the point just before the first router request, against a refusing stub router. Must reach that point. |

The launcher refuses a release unless a preflight report passed for the **same
release pin within the last hour**. Practice-run steps 1–3 become "run
preflight; all pass".

## Deletes

- The live checks in practice-run steps 1–3 that agents run by hand. They become
  one command.
- The unconditional `codex_login_gate` at `factory/launch.sh:149-151`. It runs
  only when a manifest route starts with `codex/`. Lines 514 and 654 get the same
  condition.

## Tests

- Real artifacts: the retained practice manifest and policy. Replay the real
  `boat 1.0.87` and Docker-conflict messages from `docs/reports/practice-run-20261102.md`
  and `tests/factory/fixtures/practice-startup-conflict-20261103.json`.
- Each check fails independently, and the report still lists all others. A
  report with 3 injected failures shows 3 fails, not 1.
- The Codex gate is skipped for the practice manifest (no `codex/` route) and
  enforced for a manifest with one.
- The launcher refuses a missing, stale (>1h) or different-pin report.
- `image_startup` runs against real local Docker (no simulated Docker replies).
  With the old early-Compose code it fails on the clash, and with the fix it
  passes.

## Murphy rows

Add before fixing (taken at merge):
- `new-preflight-1`: Boat auto top-up state is not machine-readable.
- `new-preflight-2`: Boat CLI drifts from its pin between pinning and deployment.
- `new-preflight-3`: Codex login guard stops runs that use no Codex route.
- `new-preflight-4`: A refreshed credential bundle may not decrypt with the control identity.
- `new-preflight-5`: Deployment needs an interactive sudo password.
- `new-preflight-6`: Live prerequisites are found one at a time, each stopping the run.

Closes 2, 3, 5 and 6 with the tests above. Rows 1 and 4 move to
`needs_founder` / `fail` before launch rather than mid-run.

## Open founder decision

`image_startup` uses local Docker, which does not reproduce the Boat sandbox's
exact metadata. A real Boat smoke worker that boots the pinned image, runs
startup to the first router request and is deleted at once would close that gap.
The 2026-11-03 worker's observed debit was $0.0019. Default without approval:
local Docker only.

## Out of scope

Fixing stop 10 itself, which is already on `t3/batch-service-control-vm`. Stops
4's code fix, which is row `new-worker-router-delivery-1`. Pilot admission.
