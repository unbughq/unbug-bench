**Verdict: PASS**

I found no blockers. This was a read-only review: I read the three reviewer roles, both standards, `docs/designs/router.md`, the committed `docs/designs/interfaces.md` and `docs/reviews/router-design-5.md`. I didn't run or edit anything.

## Review 5 items

- **BL1 (credit and credential blocks never clear): fixed.** `router.md:139-145` keeps credit and `credential_expiring` blocked until B sends `observe(pool, healthy=True, observation_id=<receipt ID>)`. The call uses the batch-scoped `FACTORY_ROUTER_TOKEN`, clears the block once per `observation_id`, and is tested as blocked → B observe → capacity → admit. This fits the relaunch caps in `interfaces.md:177-178`. Time-based limits still get their single leased readiness attempt (`:129-130`), so the two paths don't contradict each other.
- **M1 (restart-count owner): fixed.** `router.md:261-263` puts the `provider_wait` exemption in A's `restart` change, matching `interfaces.md:190`.
- **M2 (where the record goes on the card): fixed.** `router.md:218-220` writes `terminal_stop` and the public `provider_wait` object in one atomic scorecard write. The card's field list matches `interfaces.md:146-149`.
- **Nits from review 5: fixed.** The launch wording is now `launch(batch, job, collected_generation)` (`:241`). An unsettled record raises `BudgetError(provider_wait_unsettled)` straight away (`:227-228`). The test files are named (`:304-307`), and there is a time estimate (`:302`).
- **Codex: matches what the parent accepted.** The runtime re-reads the RAM file on every call with no cache and no `~/.codex` fallback. A missing or expired file becomes `credential_expiring` through `await_lease`. The `launch.sh` edit is named as an edit in another stream's area, and updating `interfaces.md` is left to the parent (`:158-168`).
- **API: matches the final contract.** `await_lease` is the only public entry and `admit` is private. Leases renew every 60 seconds and are reclaimed after 180. `capacity(route)` is there, and `finish(lease_id, outcome, receipt)` books nothing (`:29-35`). The RPC list (`:107`) now includes `observe` and `capacity`.
- **Scope: held.** D keeps settlement and reservations, and B keeps lifecycle and Codex renewal. Rows 2, 3, 4, 47 and 48 stay open until B's end-to-end test, and row 20 moves to B (`:251-253`, `:277-282`).

## Actionable findings (all Nits)

1. **Workers can technically clear a block themselves** (`:143-145`). The token that authorizes `observe(healthy=True)` is the same one sent to every worker (`:27`, `:48`). "Workers never generate healthy observations" is a rule in the text, not something the server enforces, so code inside a worker could clear a credit block. The harm is small, because the next 402 blocks the pool again. Still, it would be safer to accept `healthy=True` only from the control VM's own address, or to say outright that this risk is accepted. Either way, add one test: a healthy observation for a pool that isn't blocked does nothing.
2. **The reason for a missing non-Codex credential isn't named** (`:149-151`). When a selected Claude, Go or OpenRouter account has no credential, the design starts a `provider_wait` but doesn't say which `reason` it uses. Say it is `credential_expiring` and that B's healthy `observe` clears it after installing the credential. Otherwise the implementer has to choose.
3. **"May defer Codex" is ambiguous** (`:167-168`). It's unclear whether A builds the RAM reader and the `launch.sh` edit now, or leaves them for later. Say it plainly, for example: "A implements both; Codex routes resolve to `credential_expiring` until B provisions the file."
4. **Some text is repeated** (`:158-166`). The RAM path, "CODEX_HOME supplies config.toml only" and the missing-file rule each appear twice. Merge them into one paragraph.
5. **Long lines.** Lines 28, 107, 116, 135, 145, 162, 189, 201, 218 and 220 go past the file's normal wrap width. Re-wrap them.

None of these change the verdict. With no blockers, the design is clear to implement as the authorized unit-tested slice.
