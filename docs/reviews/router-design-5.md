**BLOCKED**

This review was read-only, and I didn't run or edit anything. I read the three reviewer roles, both standards, `docs/designs/router.md`, the committed `docs/designs/interfaces.md` (9699e5d + c49c754) and router reviews 1–4. One blocker is left, plus two majors and a few nits.

Everything raised in review 4 is fixed:
- **Public API:** `await_lease -> Lease` is the only public entry and `admit` is private (`router.md:29-30`).
- **New calls:** `capacity(route)` is added (`:34-35`).
- **Finish:** it is `finish(lease_id, outcome, receipt)` and books nothing (`:33-34`).
- **Lease timing:** leases renew every 60 seconds and are reclaimed after 180 (`:32`, `:116-117`).
- **Record:** it has no generation or checkpoint hash (`:211`), and its fields match the contract (`:207-211`).
- **Flag off:** the wait stays in the worker and never exits (`:190-193`).
- **Archival:** a settled record is archived before the resumed worker is admitted (`:216-218`).
- **Earlier fixes still hold:** the chain table, the main-handler-only writer, the concurrent-wait merge and the Codex RAM source.
- **Scope:** D keeps reservations and settlement. B keeps lifecycle, credentials and row 20. Rows 2, 3, 4, 47 and 48 are honestly left open.

## Blocker

**BL1. Once the router blocks the wallet for `credit` or an account for `credential_expiring`, nothing ever clears it, so the contract's recovery path can't work.** (`router.md:130-132`, `:139-141`, `:107`, against `interfaces.md:177-178`)
- The design says both blocks stay "until an explicit healthy observation" and never clear with time.
- A healthy observation only comes from a successful call. While the pool is blocked, no call is admitted, so the block can never lift. Only time-based limits get a "leased readiness attempt" (`:129-130`).
- The contract allows one relaunch after B detects a top-up, and says `credential_expiring` clears once B renews Codex. Under this design, that relaunched worker is refused again straight away. It writes a second wait, and the case ends as `provider_wait_unrecoverable`.
- There is also a side effect. An expired Codex token reported by one worker blocks the shared Codex account for every worker, and that block is permanent too.
- **Why it blocks:** this is A's admission contract. The implementer would have to design the clearing call and decide who is allowed to make it. That breaks the Zero-Decision rule, and B would have to change A's contract later.
- **Required (one sentence plus a test):** pick one of these.
  - (a) The `observe` RPC accepts a `healthy(pool)` observation that B sends after a top-up or a Codex renewal. Say which token authorizes it.
  - (b) At `retry_after`, `credit` and `credential_expiring` get the same single leased readiness attempt as other limits. B's relaunch caps already limit how often this can repeat.
- Then test blocked → cleared → admitted.

## Majors

**M1. The design gives restart-count ownership to the wrong stream.** (`router.md:252`, against `interfaces.md:190`)
- The design says "D owns counters".
- The contract (§5) names `restart.py` as A's, and says a `provider_wait` never uses up a restart count.
- **Fix:** say that A's `restart` change does not count `provider_wait` stops and relaunches, and test it.

**M2. Where the record goes on the public card is not pinned down.** (`router.md:196-198`, `:210-211`, against `interfaces.md:149`)
- The contract requires the card's `provider_wait` object to be written in the same scorecard write that sets `terminal_stop: provider_wait`.
- The design lists the card fields but never says which write carries them.
- **Fix:** add one line saying the main stop handler writes both in the same scorecard write. B reads only the card.

## Nits

- **Generation wording:** `router.md:231` and `:239` say `launch(batch, job, checkpoint)` and "same-generation". The contract says `launch(batch, job, collected_generation)`, relaunched from the collected generation. Use the contract's wording.
- **Unsettled record:** `router.md:218` says an unsettled record "blocks admission". Name what `await_lease` does in that case, for example raise a fixed sanitized error and never wait.
- **Codex path:** `/dev/shm/secrets/codex-auth.json` is still missing from `interfaces.md`, which review 4 also asked for. "B is notified" (`:158`) is not a contract.
- **Heilmeier timeline:** the phases are listed but have no time estimate (`:286-289`).
- **Readiness:** the test files are not named. Line 135 is still too long and should be re-wrapped.

## Verdict: **BLOCKED**

BL1 is the only blocker. The fix is one sentence choosing (a) or (b), plus a test. M1 and M2 are one-line fixes for the same revision. With those three changes, I'd expect the next review to pass.


## Elephant response

BL1: explicit observe(pool,healthy=True,observation_id) RPC authorized by the batch token, idempotent on renewal/top-up receipt, clears credit/credential blocks. Test blocked->cleared->admitted. M1: restart exemption belongs A. M2: terminal_stop plus public wait projection share one scorecard write. Fixed generation wording, named unsettled error/tests/time estimate. Parent explicitly accepted per-call uncached RAM Codex reader and authorized removing launch copy; matching interfaces update is parent-owned. Fresh review requested; no findings rejected.
