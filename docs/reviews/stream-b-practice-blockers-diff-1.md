# Goldfish diff review: `stream-b-practice-blockers`, c32e884..HEAD (3ed4fe8)

**Verdict: PASS. No blocking findings.**

Mode: REVIEW. Personas: `zoom_out` and `implementation_readiness`. Standard: `implementation-readiness-standard.md`. I compared the diff with `docs/designs/stream-b-practice-blockers.md` and `docs/reviews/stream-b-practice-blockers-design-1.md`.

## Scope

- Only three files outside `docs/` changed: `factory/account_handoff.py`, `tests/factory/test_account_handoff.py`, and `factory/batches/b-practice-20261031.json`.
  - The manifest came in with 6ac450e, the earlier preparation increment. It is dormant: `batch_money.py:69` only resolves it by explicit batch id.
  - This increment's production change is limited to `launch_accounts`, which matches the design.
- These are untouched: `model_router.py`, `model_runtime.py`, `key_holder.py`, `batch_holder.py`, `docs/murphy-register.md`, and all deploy and systemd files.
- 274084a..HEAD adds only the suite JSON and log, so the tested head and the reviewed code are the same.

## B1 (choose baseline for missing metadata): resolved

- `account_handoff.py:78-82`: the selection is built in this order:
  1. the policy's OpenCode default and Claude 1;
  2. then `initial_accounts`;
  3. then the checkpoint's `provider_accounts`.
- `choose` now gets `initial_state(card, policy, {**selected, opencode or 1})`. Before, it got a hard-coded 1/1 baseline.
- `initial_state`, `choose`, `current`, `prepare` and `apply` are unchanged, as the design says.
- The design's failure case is now fixed. With no `provider_accounts`, `initial_accounts {claude: 2}`, and a held, authorized `claude-token` wait:
  - the baseline is 2;
  - `choose` switches to 1.
- `test_bootstrap_and_missing_metadata_use_initial_account_defaults` asserts this case, and also the bootstrap case where `{}` selects 2.

## B2 (both callers, reversed test): resolved

- The router selection now always applies, and the explicit request is applied last (`:85-87`). Before, `initial_accounts` could block a router selection. The new precedence is: defaults < checkpoint < held, authorized router selection < explicit request.
- **Batch caller** (`batch_holder.py:671`): passes `{}`. It still refuses any label that is not held.
- **Non-batch caller** (`key_holder.py:655`): passes `req`. Its explicit override wins, and the round-trip test checks this with `{'claude_account': old}`.
- After the selection, key_holder still checks that the account is authorized and held, so the new precedence fails closed.
  - Example: a checkpoint records Claude 2, but the job does not authorize account 2. key_holder now refuses the launch instead of silently swapping to another account.
- key_holder's validation text ("invalid explicit initial account selection") is unchanged.
- The paused-card assertion is reversed from (2, 2) to (1, 2), as the design specifies.

## Test coverage against the design's test contract

All of these are covered:
- fresh account 2;
- restored account continuity;
- authorized 2→1 and 1→2;
- a requested label that is not held, or not authorized;
- paused, non-`provider_wait` cards;
- explicit request precedence;
- repeatability;
- unchanged inputs, checked with deepcopy, including after the returned history is mutated;
- public history passed through.

These tests prove selection only. They do not prove authentication, and the design says so.

## Suite

- `docs/reviews/stream-b-practice-blockers-suite-20261031T093541Z-4b078b48.json` records:
  - head 274084a;
  - integrated base c32e884;
  - the required command;
  - exit 0;
  - "156 test scripts run; 0 failed."
- The log's sha256 (`b61f32ee…a84a3e`) matches the recorded value, and the log ends with that same summary line.
- The earlier run, 67f4a1e3 at 289b07f, has exit −9. Its record marks it as interrupted and superseded, not a pass. That is correct.

## Safety and claims

- No change touches the Claude reservation. The USD 50 Claude invocation reservation is explicitly kept.
- No change to `select_models` or to the production family and calibration rules. The design records the cheap-profile conflict as part of blocker 8, still open.
- HOLDER_ENABLED and DIAGNOSIS_ENABLED stay false. No code or config in the diff sets them, and the design and plan restate this.
- No Murphy rows closed. No launch readiness claimed.

## Non-blocking

- **Nit:** `factory/batches/b-practice-20261031.json` (from 6ac450e) still has `--rotation-slot 0` and `--dry-run`. The addendum says slot 0 is invalid and that this manifest must be replaced by the reviewed fresh-launch candidate (step 5). It is dormant, so this is not blocking. Be careful that nothing activates it before the replacement.
- **Nit:** the pins in `docs/reports/stream-b-practice-release-20261031.json` still record the old `account_handoff.py` hash. The design already calls the staged pins obsolete, so this is expected. Do not reuse them.
- **Nit (zoom-out):** `initial_state` is built twice in `launch_accounts`. It is cheap and clear, so no change is needed.

I made no edits, launched no workers, ran no paid probes, read no secrets and delegated nothing.

## Elephant response

Accepted PASS. B1 and B2 are verified resolved; no blocking findings rejected. Keep the dormant slot-0 preparation candidate and obsolete pins unactivated, as the addendum requires. Replacement policy/release review remains deferred. No extra refactor for the duplicate cheap initial_state call. The only post-suite changes are validation/review records; tested production code remains unchanged. No Murphy rows closed and no live run authorized or performed.
