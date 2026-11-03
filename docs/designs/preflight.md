# Live preflight: every launch prerequisite checked before any live action

Revision 3, after `docs/reviews/preflight-design-1.md` and `-2.md`. Round 2 was
the last design round. The parent accepted its four blockers, which are fixed
below, and the diff review confirms them.

## Problem

The 2026-11-02/03 practice run took 29 hours, stopped 10 times and made zero
model calls. Every stop was a prerequisite that could have been checked before
step 1. Each was found live, one at a time, and each stopped the run.

Evidence: `docs/reports/practice-run-20261102.md`. On `factory-simplify` the
report runs through stop 8. Stops 9 and 10 are only on the unmerged
`t3/batch-service-control-vm` (sections "Deployment diagnosis and repair" and
"Post-window result").

| # | Stop | Covered by |
|---|---|---|
| 1 | Boat auto top-up could not be verified | `founder_decisions` (attestation; no API reads it) |
| 2 | Claude account distinctness unprovable | `founder_decisions` |
| 3 | Router-RAM OpenRouter-key acknowledgement not on record | `founder_decisions` |
| 4 | Workers had no router URL, token or TLS trust | `router`, plus the existing fix in row `new-worker-router-delivery-1` |
| 5 | Mandatory "Go" pause | unchanged; see founder questions |
| 6 | Installed `boat 1.0.87`, pinned `boat 1.0.85` | `boat_cli`, plus pinning the installer in `control/setup.sh` |
| 7 | Codex login guard fired on a run with no Codex role | conditional gate |
| 8 | Refreshed bundle not decryptable by the control identity | `credentials` |
| 9 | Deployment hit an interactive sudo password | `deploy_access`, plus step 2 installs via root SSH |
| 10 | Docker name clash at worker startup | **not this change**: fix and real-Docker test on `t3/batch-service-control-vm` (`tests/factory/test_practice_startup.py`) |

Today `factory/practice_preflight.py` checks only offline files. Its live items
are hard-coded `unproved`. The live checks are prose that an agent follows by
hand, stopping at the first failure.

## Change

One set of read-only check functions lives in `factory/practice_preflight.py`
and is called from two places. No check reserves anything, starts a worker,
calls a model, writes a ledger or spends money. Every check runs even after an
earlier one fails.

### A. `practice_preflight.py --live`, run by the operator before practice step 2

It prints one report with each check as `pass`, `fail` (with reason) or
`needs_founder`. Exit codes follow the existing `code()`: 0 means all pass, 1
means any fail, and 3 means only unproved or `needs_founder` items.

| Check | How |
|---|---|
| `founder_decisions` | `factory/batches/<batch>.decisions.json` holds a list of `{id, text, recorded_utc}`. It joins `pins()`/`files()`, so it is pinned at step 0 and a new decision means a repin. Required IDs are a per-batch constant; for practice they are `topup_off`, `accounts_unverified_accepted` and `router_ram_openrouter`. All missing IDs are listed together, so the founder answers once, before pinning. |
| `deploy_access` | Root SSH with `bin/control-vm`'s own `ssh_options()` (key, `IdentitiesOnly`, per-server `known_hosts`) and `BatchMode=yes` runs `true`. |
| `boat_cli` | On the VM: exact `boat --version` equals `bin/boat-call` `VERSION`, and `bin/boat-call list` returns `hasMore=false`. |
| `boat_wallet` | Practice only: balance ≤ the `LIVE` worker ceiling (5.0). |
| `credentials` | The same function as phase B, run against the VM's bundle. |
| `login_lifetimes` | The same function as phase B. |

### B. Inside `batch_holder.dispatch`, before `dispatch_started=True` (`batch_holder.py:822`)

This covers every `dispatch()` call, including checkpoint and replacement
launches. `resume_controller` is excluded. The bundle is decrypted **once, in
memory**. Labels, `codex-auth.json`, `openrouter-key` and `r2-env` all come from
that one decryption.

- `credentials` **replaces** the `secret_labels` call and the label check at
  `batch_holder.py:783-789`. A decrypt failure or a missing label raises
  `PreflightHold` instead of `ValueError`. Labels are built the way `dispatch`
  and `launch.sh` build them:
  - the Claude label from `launch_accounts`;
  - the OpenCode label, defaulting to `opencode-go-key`;
  - `openrouter-key` and `codex-auth.json`.

  The router names are added by `pack` and are not required in the bundle. The
  recipient check (`:781`) and the code-fingerprint check (`:774`) stay terminal.
- `login_lifetimes`: `codex_login.validate` on the bundle's `codex-auth.json`,
  only when a resolved role is `codex/` (see below).
- `router`: `router_delivery.pack` on the bundle, filtered as at
  `launch.sh:320-324`, succeeds and yields the three router names. `pack` reads
  a 0600 config file and makes one `status` RPC. The packed output is thrown
  away. Also check that `status['paid']` is well-formed with
  `outstanding_usd == 0`, which replaces step 2's hand-run "ledger" check.
- `openrouter`: `model_router.available_credit()` with the bundle's
  `openrouter-key`. `None` fails. The effective paid ceiling is
  min(`LIVE` cap, credit), per `practice-run.md:21`.
- `r2`: one read-only HEAD on the batch's R2 prefix, with the bundle's
  `r2-env`, using the client `factory/r2_upload.py` already uses.

`boat_cli` is not repeated, because `dispatch` already runs `boat-call list`
through its version guard (`:792`). A mismatch already returns `TEMPFAIL`, with
the operation left pending (stop 6).

**`PreflightHold(reason)`** is caught next to `money.MoneyWait` (`:830`) and
returns `TEMPFAIL`, so the operation stays pending. Today any other exception
before `dispatch_started` marks it `failed`/`preflight_refused` for good
(`:832-838`). The reason goes to stderr, which lands in the per-spawn log.
`key_holder` retries dispatch every 60 s (`key_holder.py:454`). Each retry costs
$0, and `batch_status` already flags a stuck launch.

### Conditional Codex gate

At `launch.sh:149`, 514 and 654, the launcher runs
`eval "set -- $args"` and then
`codex_login.py --ttl-hours H --job-args -- "$@"`. `codex_login.py` parses the
args with `parse_known_args` (batch args carry `--factory-job-config` and
others), honours `--rotation-table` and `FACTORY_ROTATION`, and resolves roles
with `model_runtime.select_models`. Rotation defaults count: both rotation files
give `codex/gpt-6.1-sol` a role in every slot. It skips the lifetime check only
when no resolved role is `codex/`, and enforces it when the args don't parse.
This is a new resolver, because `practice_preflight.roles()` raises on missing
flags. `launch.sh:333` and `:695` still require `codex-auth.json` and qualify the
codex driver; that's harmless and left as is.

### Root causes fixed alongside

- `control/setup.sh:39` downloads the latest Boat CLI. Pin it to the exact
  `boat-cli-v1.0.85` Linux asset and check its SHA-256 (`5d7933a2…`, recorded in
  the report).
- Practice-run step 2 states that installs run as root via `bin/control-vm`,
  never through user sudo.

## Deletes

- Practice-run step 1's hand-run checks and the verification half of step 2
  (ledger, credit schema, R2, hashes). The install actions in step 2 and the
  reservation in step 3 stay.
- The unconditional Codex gate at the three call sites.
- The separate `secret_labels` decrypt in `dispatch`, replaced by the single
  in-memory decryption.

## Tests

- **Real artifacts:** the retained practice manifest, policy and pinned release;
  the real `router_delivery` config fixture; the real `boat 1.0.87` refusal text.
- **Authored:** the Codex expiry replay uses a JWT written for the test. The
  report keeps only labels, so no real token exists to replay.
- A report with 3 injected failures shows all 3. A missing decision ID gives
  `needs_founder` and exit 3.
- **Through the real `dispatch`, against a retained practice policy:**
  - an undecryptable bundle, a missing label, a `pack` failure, `None` credit
    and a nonzero `outstanding_usd` each leave `dispatch_started` false and the
    operation pending;
  - a recipient mismatch still marks it failed.
- **Codex gate:**
  - the practice args skip it;
  - a job without `--strong-calibrator` on `rotation-3writers.json` *resolves* a
    `codex/` role and enforces it;
  - unparseable args enforce it.
- `control/setup.sh`: a test replaces the download with a non-matching file, and
  setup refuses on the SHA-256 mismatch.

## Murphy rows

- Row 31 (Boat CLI drift): stays closed for the wrapper. Its open note, "VM
  install pin remains a deployment prerequisite", is fixed by the `setup.sh` pin
  and closed by its SHA test.
- `new-preflight-1`: Codex login guard stops runs with no Codex role. Closed by
  the gate tests.
- `new-preflight-2`: Live prerequisites are found one at a time, each stopping
  the run. Closed by the all-failures and real-`dispatch` hold tests.
- `new-preflight-3`: Boat auto top-up is not machine-readable. Stays open as an
  attestation only.
- `new-preflight-4`: A refreshed bundle may not decrypt with the control
  identity. Closed by the undecryptable-bundle hold test, then qualified live.
- `new-preflight-5`: Deployment attempted interactive user sudo. Closes at live
  qualification of `deploy_access`.

## Cost and timeline

$0 provider spend. About one day of offline implementation, then a diff review
of at most 2 rounds. It depends on `t3/batch-service-control-vm` merging, for
stop 10's fix and the stop 9–10 evidence.

## Founder questions

1. **Boat smoke worker.** Should preflight boot one real worker from the pinned
   image, run startup up to the first router request, then delete it? The
   2026-11-03 worker's observed debit was $0.0019, and it's the only way to test
   the real sandbox image. Default: no.
2. **"Go" pause.** Can the founder give "Go" up front, so the run doesn't pause
   at step 4? The Mac-disconnect test itself stays. Default: keep the pause.
