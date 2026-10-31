**Goldfish design review: `docs/designs/stream-b-practice-blockers.md`, Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness.**

**Verdict: no PASS. Two blocking findings are open.**

The scope is right and small. The design is correct about A at 1fff453 and about how batch dispatch calls the helper. The precedence it proposes still cannot be implemented exactly as written: the existing `choose()` uses a different starting account, and one caller of `launch_accounts` is not named.

## What I checked against code

- `factory/account_handoff.py:76-87` (`launch_accounts`). Today `overrides` merges `policy['initial_accounts']` with the request. It sits on top of the accounts recorded in the checkpoint, and it also stops a `provider_wait` change from applying. The design is right to call this a bug, and the precedence it wants fixes it: initial accounts as defaults, then the checkpoint's recorded accounts, then a held and authorized `provider_wait`, then an explicit request.
- `factory/batch_holder.py:671`. Dispatch calls `launch_accounts(card, job, {}, labels)`, so the request really is empty. It then refuses any selected label that isn't held (lines 672-673). This matches lines 87 and 92 of the design.
- 1fff453 (`model_router.py`, `docs/designs/router-account2.md`). `Store.rpc` only lets account 1 in while account 2 has an unexpired rate or quota observation. If the router grants a lease for a key the worker doesn't hold, `await_lease` turns it into `Wait('credential_expiring', account=<lease account>)`. That gives `choose()` a `provider_wait` that names the needed account in both directions. So 2 -> 1 -> 2 can be reached through `provider_wait` alone, and "selection is not admission" holds. The design does not claim A is integrated here. That is correct: the diff from e63a8aa to 1fff453 touches only `model_router.py` and the batch manifest.
- `run.py:3060-3063`. `provider_accounts` is written only when `FACTORY_ACCOUNT_STATE` is set. Batch dispatch always sets it. Legacy cards and the retained fixture `tests/factory/fixtures/opencode-failover/input-scorecard.json` have no `provider_accounts`.

## Blocking findings

**B1. Blocker: the `choose()` starting account conflicts with "initial accounts are defaults for missing metadata".** Design lines 83-87 and 101-104; `account_handoff.py:62-73` and line 84.

- `launch_accounts` calls `choose(card, initial_state(card, policy), ...)`. `initial_state` fills a missing account with a hard-coded `{'opencode': 1, 'claude': 1}`, and `choose` returns `None` when the requested account equals that `old` value.
- **Failure case:** a card with no `provider_accounts`, a policy with `initial_accounts: {claude: 2}`, and a held, authorized `provider_wait` asking for `claude-token` (account 1).
  - The default makes the selection 2.
  - `choose` sees old=1 and requested=1, so it returns `None`.
  - Account 2 is launched again. That breaks the stated rule that the `provider_wait` choice overrides both.
- The design's own test plan uses that fixture, which has no metadata, for "authorized 2 -> 1 -> 2". So the implementer either hits this or has to make an unstated design choice.
- **Fix:** state that `choose()` starts from the selection already resolved from defaults plus recorded accounts. Then say how `choose` gets it: either pass an `initial_state` built from that selection, or an explicit baseline argument. Also say whether `initial_state`'s hard-coded 1 defaults change. `prepare` and `apply` use the same `choose` through `current()`, which has its own defaults. The design must state whether those paths are unchanged.
- Add a test: missing metadata, `initial_accounts` set to 2, and `provider_wait` asking for 1, which should select 1.

**B2. Blocker: the second caller and the reversed existing test are not named.** Design lines 82, 92 and 94.

- `launch_accounts` is also called by `factory/key_holder.py:654-655` for non-batch founder jobs, which pass a non-empty `req`. key_holder validates `initial_accounts` as an "explicit initial account selection" (lines 166-169).
- The design changes that meaning for key_holder jobs without saying so. After the change, a founder job's `initial_accounts` no longer replaces the checkpoint's recorded account.
- The existing test `test_fresh_launch_keeps_collected_accounts_unless_explicitly_overridden` (`tests/factory/test_account_handoff.py:164-165`) asserts the old behaviour: `initial_accounts {'opencode': 2}` beats a paused card's recorded opencode 1, giving `(2, 2)`. That test will fail.
- **Fix:** state that the change applies to both callers, and that key_holder's explicit `req` override is the remaining way to force an account. Alternatively, explain why the key_holder path is out of scope.
- Say that this assertion is reversed (it should become `(1, 2)`) or rewritten. Also say whether key_holder's error message ("explicit initial account selection") changes.

## Non-blocking findings

- **Major, wording (line 91).** "Missing requested credentials never manufacture an account switch" can be read as contradicting A. In A, a missing credential is exactly what produces the `provider_wait` that drives the switch. Rephrase it: a requested label that is not in the held bundle never produces a switch, and the launch stays on the resolved account.
- **Nit, Heilmeier.** The one-function increment has no cost or timeline line. Lines 5-30 cover the objective, current state and risks well enough for an addendum.
- **Nit, Murphy rows (line 114).** "No rows closed" is acceptable. The five launch blockers (4-8) have no `new-<topic>-<n>` row identifiers, though, so they could be dropped after this branch. Add rows, or state where they are tracked.
- **Nit, zoom-out.** "Ordered change" steps 1-5 are contracts for later increments, not instructions for this one. They are clearly marked as later work, so I did not review them as ready to implement. Each will need its own design.

## Next step

Once B1 and B2 are answered in the design text, I see no further blockers for this increment. I made no edits and ran no tests, secrets, workers, probes or delegation. The writer still needs to save this report under `docs/reviews/`.

## Elephant response

Accepted B1 and B2. The addendum now passes choose the resolved default/observed baseline, leaves initial_state/current/prepare/apply unchanged, and explicitly covers both callers and the reversed paused-card assertion. Added the missing-metadata regression to the test contract. Clarified held-bundle wording, cost and blocker tracking. No findings rejected. Fresh diff review must verify these resolutions.
