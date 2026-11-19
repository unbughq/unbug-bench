# Diff review 6: neuralwatt-routes confirm on 55997892 (goldfish)

**PASS.** I found nothing blocking. I made no changes to the worktree.

**1. Safety of the looser check.** I read all of `answer()` (`factory/ordinary_retry.py:113-235`).
- **Wrong chain or tampered state:** still rejected. A saved route has to be in `models[0]`'s own chain, and the binding check still runs first, so a route from another model's chain or a made-up string fails as before.
- **What the old check also did:** it rejected a route that is in this chain but on an account not offered now. That only mattered as a "has this lane been tried" record. Nothing leases from `spent_routes`.
  - `approved` and `routes` are still built from the accounts offered now.
  - `excluded` only takes routes from `routes`.
  - `exhausted()` is `approved <= spent`, so an extra spent route that isn't offered changes nothing.
- **cae763 reset:** unaffected. The new test goes through it: with the key gone, `approved` is just the OpenRouter lane, which is spent. So the stuck answer resets and the spent Neuralwatt route moves into `exhausted_attempts`.
- **Putting the key back later:** the Neuralwatt route stays spent and excluded. Spending stays bounded.

**2. Test.** I ran it in a scratch copy of 55997892.
- At head, it and the cae763 test pass.
- With line 132 put back to `accounts`, it fails with `ordinary_retry_state_invalid`.
- It goes through the real snapshot path (`fresh_context`, the saved `state.json`, a new engine attempt).
- One limit: the Neuralwatt spend is written into `state.json` by hand, not made by a real call. That's acceptable for this fixture.

**3. Rollback doc.**
- `worker_step.py:470-471` (in `factory/durable/`) is correct: the `supervise` parent books `infra:step_crashed` when the child leaves no result. Killing the parent leaves the forked child running, as the doc says.
- `helper_link.py:213` is correct: the helper takes `router_accounts` from the job, which `helpers.py:131` copies from the parent.

**Nits:**
- **Kill the whole attempt, not just the child.** If you SIGTERM only the Python child, any agent programs it started keep running. They may still hold a Neuralwatt lease after the retry starts. The doc should say to stop every process in the attempt, the way `stop(key)` does (it sends SIGTERM, then SIGKILL, to all processes `processes(key)` finds, at `worker_step.py:172-180,338-347`).
- **File paths.** The doc writes `worker_step.py` and `helper_link.py`, but both are under `factory/durable/`. Spell out the path.

## Elephant response (2026-11-19)

Both nits taken in rollback step 2: SIGTERM every process of the attempt (as `stop(key)` finds them), not only the Python child; full `factory/durable/` paths.
