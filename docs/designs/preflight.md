# Live preflight: every launch prerequisite checked before any live action

Revision 2, after `docs/reviews/preflight-design-1.md`.

## Problem

The 2026-11-02/03 practice run took 29 hours, stopped 10 times and made zero
model calls. Every stop was a prerequisite that could have been checked before
step 1. Each was found live, one at a time, and each stopped the run.

Evidence: `docs/reports/practice-run-20261102.md`. On `factory-simplify` the
report runs through stop 8; stops 9–10 are on unmerged `t3/batch-service-control-vm`
(sections "Deployment diagnosis and repair" and "Post-window result").

| # | Stop | Covered by |
|---|---|---|
| 1 | Boat auto top-up could not be verified | `founder_decisions` (attestation; no API reads it) |
| 2 | Claude account distinctness unprovable | `founder_decisions` |
| 3 | Router-RAM OpenRouter-key acknowledgement not on record | `founder_decisions` |
| 4 | Workers had no router URL, token or TLS trust | `router`, plus the existing fix in row `new-worker-router-delivery-1` |
| 5 | Mandatory "Go" pause | unchanged; see founder questions |
| 6 | Installed `boat 1.0.87`, pinned `boat 1.0.85` | `boat_cli` |
| 7 | Codex login guard fired on a run with no Codex role | conditional gate (below) |
| 8 | Refreshed bundle not decryptable by the control identity | `credentials` |
| 9 | Deployment hit an interactive sudo password | `deploy_access` |
| 10 | Docker name clash at worker startup | **not this change**: fix and real-Docker test on `t3/batch-service-control-vm` (`tests/factory/test_practice_startup.py`) |

Today `factory/practice_preflight.py` checks only offline files. Its live items
are hard-coded `unproved`, and the live checks are prose that an agent follows by
hand, stopping at the first failure.

## Change

One set of read-only check functions in `factory/practice_preflight.py`, called
from two places. No check reserves anything, starts a worker, calls a model,
writes a ledger or spends money. Every check runs even when an earlier one
fails.

**A. `practice_preflight.py --live`, run by the operator before practice step 2.**
It prints one report in which each check is `pass`, `fail` (with reason) or
`needs_founder`. Exit codes: 0 means all pass, 1 means any fail, 2 means only
`needs_founder`.

| Check | How |
|---|---|
| `founder_decisions` | `factory/batches/<batch>.decisions.json`: a list of `{id, text, recorded_utc}`, committed and pinned with the manifest. The required IDs live in a constant per batch; for practice they are `topup_off`, `accounts_unverified_accepted` and `router_ram_openrouter`. All missing IDs are reported together, so the founder answers once, before pinning. |
| `deploy_access` | `ssh -o BatchMode=yes root@<control> true` succeeds. Step 2 installs through root SSH, as `control/setup.sh` and the 2026-11-03 repair did. Stop 9 came from trying user sudo instead. |
| `boat_cli` | On the VM, exact `boat --version` equals `bin/boat-call` `VERSION`, and `bin/boat-call list` returns `hasMore=false`. |
| `boat_wallet` | Practice only: balance ≤ `LIVE` worker ceiling (5.0). |
| `credentials` | The VM's `secrets.age` decrypts in RAM with the control identity, and it holds every label `launch.sh:333` requires (not just `key_holder.secret_labels`). The report records the bundle's SHA-256. |
| `login_lifetimes` | Codex lifetime covers TTL plus margin, only if a **resolved** role is `codex/` (below). |

**B. Inside `batch_holder.dispatch`, for fresh admission only, before
`dispatch_started=True` is written (`batch_holder.py:812`).** This re-runs
`boat_cli`, `credentials` and `login_lifetimes`, and adds:
- `router`: `router_delivery.pack` succeeds on the in-memory bundle, and the
  three router names are present.
- `r2_openrouter`: R2 read access works, and OpenRouter credit is readable. The
  effective paid ceiling is min(manifest ceiling, observed credit), per
  `practice-run.md:21`.

`dispatch` already runs `secret_labels` and `boat-call list` here
(`batch_holder.py:779-792`). Phase B extends that block; it adds no new stage.
A failure raises a new `PreflightHold(reason)`. It is caught next to
`money.MoneyWait` (`batch_holder.py:826`) and returns `TEMPFAIL`, so the
operation stays pending and retryable. Today, any other exception before
`dispatch_started` marks the operation `failed`/`preflight_refused` for good
(`batch_holder.py:828-833`). Resume and replacement launches use the same checks
inline, so there is no report file and no freshness window.

**Conditional Codex gate.** `codex_login.py` takes the job's launch args and
resolves roles with `model_runtime.select_models`, the way
`practice_preflight.roles()` already does. Rotation defaults count; for example,
`rotation-3writers.json` sets `strong_calibrator = codex/...`. It skips the check
only when no resolved role is `codex/`. If the args can't be resolved, as on the
`factory_auto_resume` path at `launch.sh:514`, it enforces (fail closed). This
applies at `launch.sh:149`, 514 and 654. `launch.sh:333` and `:695` still require
`codex-auth.json` and qualify the codex driver. That's harmless, and left as is.

## Deletes

- The hand-run live checks in practice-run step 1 and the verification half of
  step 2 (ledger, credit schema, R2, hashes). The install actions in step 2 and
  the reservation in step 3 stay.
- The unconditional Codex gate at the three call sites above.

## Tests (real artifacts)

- The retained practice manifest, policy and pinned release. Replay the real
  `boat 1.0.87` refusal and the real `codex_login_expired` refusal from the
  report.
- Three injected failures produce a report that shows all 3, not just the
  first.
- A missing decision ID gives `needs_founder` and exit 2.
- Codex gate:
  - the practice manifest (no resolved `codex/` role) skips it;
  - a job with no `--strong-calibrator` on `rotation-3writers.json` enforces it;
  - unresolvable args enforce it.
- Phase B failure: through the real `dispatch` against a retained practice
  policy, a refused check leaves `dispatch_started` false and the operation
  pending.
- `router` uses the real `router_delivery.pack` and its existing config fixture.
- `deploy_access` and the remote checks are qualified live at the next practice
  attempt. They close no row before then.

## Murphy rows

- Reopen row 31 (Boat CLI drift). Close it with the `boat_cli` replay test, plus
  the phase B call site.
- `new-preflight-1`: Codex login guard stops runs with no Codex role. Close it
  with the gate tests.
- `new-preflight-2`: Live prerequisites found one at a time, each stopping the
  run. Close it with the all-failures-reported and phase B tests.
- `new-preflight-3`: Boat auto top-up state is not machine-readable. Open: an
  attestation only.
- `new-preflight-4`: A refreshed bundle may not decrypt with the control
  identity. Close it at live qualification.
- `new-preflight-5`: Deployment attempted interactive user sudo. Close it at
  live qualification.

## Cost and timeline

$0 provider spend. About one day of implementation, offline, then one round of
diff review. It depends on `t3/batch-service-control-vm` merging for stop 10's
fix and the stop 9–10 evidence.

## Founder questions

1. Boat smoke worker. Should preflight boot one real worker from the pinned
   image, run startup up to the first router request, then delete it? The
   2026-11-03 worker's observed debit was $0.0019. It is the only way to test
   the real sandbox image. Default: no.
2. "Go" pause. Can the founder give "Go" up front, so the run doesn't pause at
   step 4? The Mac-disconnect test itself stays. Default: keep the pause.
