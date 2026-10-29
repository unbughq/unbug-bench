I've finished reading the design, the contract and the three prior reviews, and checked the route-table claims against the code. Here is the verdict.

**BLOCKED**

This was a read-only review. I made no edits and ran nothing. I checked the design's claims against the code. The `routes_note` text is in both rotation files, `free_models.provider_config` sends native MiniMax to Go, and the DeepSeek and Muse price overrides are in `model_runtime.opencode_config`. The current `PROVIDER_ROUTES` and `FREE_FALLBACK` match the table, and `codex_login.worker_auth` and `early_probe` both exist.

Review 3's findings are all fixed: B1 (the chain table, with billing, pool, order and authority), M1 (only the main stop handler writes the record, optional probes re-raise it, and concurrent waits merge) and M2 (the exact RAM path is named). The design stays inside its scope: D still owns reservations and settlement, B owns lifecycle, credentials and row 20, and rows 2, 3, 4, 47 and 48 are honestly left open.

## Blocker

**BL1. The design's router API does not match the router contract in `interfaces.md` §2, and A owns that contract.** (`router.md:29-30, 101-114`, against `interfaces.md:32-58`)
- **Missing call D needs.** The contract says nobody outside `model_router.py` calls bare `admit()`. Everyone calls `await_lease(role, case, deadline) -> Lease`, and D's writer and stress code call it before writing a reservation. The design names only `admit()`, plus RPCs `acquire`, `finish`, `observe` and `status`.
- **Missing call B needs.** B calls `capacity(route)` before relaunching. The design has no `capacity()`.
- **Different `finish` signature.** The design has `finish(lease_id, usage)`. The contract has `finish(lease_id, outcome∈{done,interrupted,denied}, receipt)`, and `finish` books nothing.
- **Different lease expiry.**
  - The contract renews a lease every 60 seconds and reclaims one that hasn't been renewed for 180 seconds, so a dead worker frees its slot within 3 minutes.
  - The design uses a fixed expiry of `min(admitted + invocation timeout, batch deadline) + 120 s`, with no renewal. With an attacker timeout of up to 2400 s, a dead worker holds its slot for about 42 minutes.
- **Why it blocks.** D and B code against `interfaces.md`, so the implementer would have to choose which of the two to follow. That breaks the Zero-Decision rule on the one contract A owns.
- **Required.** Either adopt §2 as written, or change §2 through its own goldfish review and record that review. Then add tests for renewal and reclaim, `capacity()`, and `finish` outcomes.

## Majors

**M1. The record fields don't match the contract.** `router.md:194` says the fields "exactly follow interfaces.md" and includes `parent_generation`.
- The `interfaces.md` schema (lines 81-94) has no `parent_generation`.
- Its rule at line 98 says the record "holds no checkpoint hash at all".
- Your brief says the latest contract includes `parent_generation`. If so, the `interfaces.md` on disk is stale, and it needs updating (with review) in the same revision.

**M2. The design and the contract disagree on who archives the record.**
- `interfaces.md:135-137` says the resumed worker moves the record before its first model call.
- `router.md:204-207` gives that to D and has A's wrapper refuse admission until the record is archived.
- Make one statement and use it in both files.

## Nits

- `router.md:119`: "without the six-hour cap" refers to a cap that isn't defined anywhere in this document.
- `router.md:143-148`: the reader switches to `/dev/shm/secrets/codex-auth.json` before B delivers the credential there, so Codex calls on A alone will fail with `credential_expiring`. State that this is expected, since no batch runs between steps 4 and 6. Also add the path to `interfaces.md` now rather than leaving it "supplied to the parent".
- `router.md:126`: the line is far too long. Please re-wrap it.

## Verdict: **BLOCKED**

BL1 is the only blocker. It is a small fix: make the design's API match `interfaces.md` §2 (`await_lease`, `capacity`, the `finish` outcome and receipt, and the renew/reclaim timing), or revise §2 under review. M1 and M2 are wording fixes for the same revision.


## Elephant response

Rebased onto reviewed cross-stream contract 9699e5d plus nits c49c754. Adopted await_lease-only public admission, capacity(), finish outcomes/receipt, 60-second renewal/180-second reclaim; no checkpoint generation field. Flag-off waits remain in-worker. Resumed worker archives after D settlement within await_lease. Account handoff now only transports an already-selected account. No findings rejected; fresh review requested against final committed interfaces.md.
