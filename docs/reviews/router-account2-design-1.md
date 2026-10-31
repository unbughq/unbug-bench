# Goldfish design review: `docs/designs/router-account2.md`

**Verdict: FAIL.** Two blockers and five major findings are open.

The router half of the design is sound. The plan breaks in the step that puts a Claude key on the worker, which the design leaves unchanged. Each worker gets exactly one Claude token, and every launch path still defaults to account 1. The founder's rule ("workers default to account 2") would only hold inside the router, while every worker still starts on account 1.

The persona instructions say goldfish don't write files. I wrote nothing, so you need to save this review to `docs/reviews/router-account2-design-1.md`.

## What checks out
- **The rate-limit signal is real.** Claude's `rate_limit_event` with `status: rejected` becomes `quota` evidence (`budget.py:1015-1021`). It is published to the router before the lease is released (`model_runtime.py:475-480`). Per-call failures are not published. Credit failures are classified before rate and quota (`budget.py:36-42`).
- **Placing the rule in the router is right.** Putting eligibility in `Store.rpc` gives capacity, acquisition and queue-order checks one place to share it.

## Blockers

**B1. Workers still launch with the account-1 key, so "default account 2" is never true on a worker.**
- **Where:** design lines 7-10 and 25; `launch.sh:317-320`; `account_handoff.py:39-41,56,82`; `key_holder.py:659-660`; `batch_holder.py:671-673`.
- **What happens:**
  - The VM receives one Claude token, and it defaults to `claude-token` (`launch.sh:318`).
  - `launch_accounts` defaults to account 1 (`observed.get('claude', 1)`).
  - The key holder accepts account 1 without any policy check, but requires policy and a held key for account 2.
  - Once the router puts account 2 first, the worker gets an account-2 lease and has no key for it. The lease fails `_credential_ready` and becomes a `credential_expiring` wait. After 60 seconds the case checkpoints and parks.
  - The relaunch is delayed about 900 seconds (`retry_at`), then `choose()` hands off the key. That only works if the policy's `claude_accounts` includes 2 and the key is held. Otherwise `choose()` returns `None` and the case loops until its deadline.
  - Result: every case takes an automatic stop of 15 minutes or more on its first Claude call, or hangs.
- **Fix:** the design must pick one of these, list the files, and add tests:
  - (a) Default the launch to account 2 in `launch_accounts`, `launch.sh` and the key holder's check, with account 1 only by handoff.
  - (b) Require `initial_accounts.claude=2` and `claude_accounts=[1,2]` in every batch policy, and reject policies without them.

  Line 25 ("no new … account configuration path") rules out neither option as written, so the design must also say which one it means.

**B2. Switching to account 1 and back is not designed.**
- **Where:** design lines 13-25; `run.py:3062`; `account_handoff.py:62-73,80-85`.
- **What happens:**
  - When account 2 is rate-limited, the router admits account 1. The worker only holds the account-2 key, so it goes through the same park-and-handoff cycle.
  - That handoff only works if account 1 is in the policy's `claude_accounts`. The design doesn't say so.
  - After the handoff, the scorecard records `provider_accounts.claude=1`, and later launches reuse it (`launch_accounts` keeps the recorded account).
  - When the account-2 limit expires, a worker on account 1 gets account-2 leases it can't use, which forces another park.
- **Fix:** state when a worker returns to account 2 and what transport does it. State whether the recorded `provider_accounts` is overridden. Add a test of the full round trip using a real handoff card.

## Major findings

**M1. A request with no eligible lane looks like an outage.**
- If account 1 is the only allowed Claude lane, or the router config `accounts` has no account 2, the candidate list is empty.
- `model_router.py:247-250` then returns an `outage` wait of now+900, repeated until the batch deadline.
- That is a configuration error reported as an outage. Define it as a refusal (`ValueError`) and test it.

**M2. The account check has no defined method and comes too late.**
- **Where:** lines 34-37.
- The whole rule depends on two labels: `claude-token` is account 1 and `claude-factory-token-2` is account 2 (`key_holder.py:35`). Line 5 admits labels are not identity.
- An OAuth token says nothing about its account when inspected offline. Proving identity likely needs a call to the provider, which is outward-facing and touches credentials.
- The design doesn't name the check, the command, where results go, or whether it gates merge or launch.
- **Fix:** make it a founder-owned step that must pass before the first batch, or move it out of this design. Either way, state the label assumption explicitly.

**M3. Not ready to implement: the exact changes are missing.**
- **Which ordering gets deleted?** `_account_order` (`model_router.py:339-343`) also orders OpenCode lanes and is fixed per request ID. Say whether it is deleted, or kept for non-Claude lanes only.
- **Predicate:** spell it out as `reason in {rate, quota} and blocked_until > now` on the account-2 pool. `model_router.py:179` keeps `reason` after a block expires, so a check on `reason` alone would be wrong.
- **Capacity:** the capacity count changes from 2 to 1 when account 2 is healthy. Name the callers of `capacity()` and the new expected value.
- **Existing test:** `test_model_router.py::test_real_claude_reset_shared_switch_expiry_and_restart` asserts account 1 first and 2 slots. The design must say it will be rewritten.
- **Target scope:** there is no list of files to change.

**M4. The Murphy row and test inputs are not written down.**
- The text of `new-router-account2-1` is missing: the problem, the evidence, and which real run showed it.
- The design should name the fixture, `tests/factory/fixtures/router-provider-limits.json.gz`.
- Those saved cards come from whichever account hit the limit. If the tests relabel them as account 2, the design should say that openly.

**M5. Fails the Heilmeier standard.**
- Cost, timeline, risks and payoff, impact, and success checks are all missing.
- The objective is written in jargon ("FIFO older request competition", "applicable route", "busy denial").

## Nits
- Line 25: nothing in production sends `observe(healthy=True)` for Claude, so only expiry closes the fallback. Drop the claim or name the sender.
- Line 15: Claude `rate`/`quota` evidence is only stored per account, never per route. "or applicable route" adds nothing.

## Simplicity check
There is no over-building, and nothing already in the code is being re-implemented. Once the launch default is fixed (B1), the change is small: a fixed account order and one eligibility check in `Store.rpc`. The existing handoff code is enough for switching to account 1 and back, as long as B2 sets the rules for it.

## Elephant response

M2-M5 and B2 are addressed by the design clarification: explicit activation
prerequisites, round-trip test, exact predicate/files, real fixture attribution,
and cost/risk/success checks. M1 uses a credential_expiring wait instead of an
outage; a ValueError would be flattened to router_unavailable by the HTTP client.
Nits addressed by using account-level evidence only; healthy is merely an
existing administrative reset path tested defensively, not a production sender.

B1's demand to change legacy transport defaults is disputed as a merge blocker
for this router-only increment. The founder explicitly requested the smallest
router enforcement and named B's plan, which already owns initial_accounts=2
and [2,1] activation configuration. Model execution remains guarded even when
transport has only account 1. This does not claim activation readiness or zero
handoff latency. Sent to a different-family goldfish for independent ruling;
not rejected unilaterally. B2 transport timing is documented and tested rather
than introducing another account scheduler.

Final disposition: design review 2 upheld the B1 rejection and accepted M1.
Its B2 correction supersedes the response above: no automatic transport
round-trip is claimed or tested here; controller integration and its real
round-trip test are explicit B pre-activation work. Design corrected accordingly.
