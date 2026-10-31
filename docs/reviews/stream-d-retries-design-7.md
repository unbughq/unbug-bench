# Stream D ordinary retries: design review 7

Reviewer: Claude Opus 5.5. Final report follows verbatim.

**FAIL: one blocking finding.**

I reviewed `docs/designs/stream-d.md:2150-2679`, through review-6 resolutions, in worktree `t3-21bef30c` at `b500db9` plus the uncommitted design edit. Where later amendments conflict with earlier wording, I treated the later amendment as the rule. Scope was item 4, batch only; row 13 closure is deferred and the row 15 claim covers only approved chains. I read it with the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW, against the Heilmeier and implementation-readiness standards. I checked it against `factory/freshness_retrieval.py`, `run.py` (`g2`, `confirm_hits`, `checked_freshness_verdict`, `ensure_freshness`), `admission.py` (`search_binding`, `search_evidence_error`), `model_router.routes`, `model_runtime.dispatch`, `durable_checkpoint.checkpoint_progress` and `recovery.py`. I saved nothing.

The review-6 blocker is resolved on paper. Projecting the evidence without `at`, filenames, the archive API body and non-200 bodies, using a semantic search-row digest, and reusing even an unresolved verdict, together close the loop that the timestamp caused. The item 1, 2 and 5 nits are also handled.

## Blocking

**1. Archive snapshot bytes change on every fetch, so the stable judgment digest still changes every cycle and the paid loop comes back** (`:2626-2648` with `freshness_retrieval.py:63-72`).
- **What the code does:** `retrieve` fetches `closest['url']` exactly as the Wayback availability API returns it. That URL is the ordinary replay form `/web/<ts>/<url>`, not `/web/<ts>id_/<url>`.
- **What that returns:** Wayback replay HTML includes the injected toolbar and a trailing comment. The comment holds the request's own retrieval time ("…RETRIEVED FROM THE INTERNET ARCHIVE ON <now>") and per-request "playback timings (ms)". This is from general knowledge of how Wayback serves pages. No fixture in the repo contains a replay page, so I could not confirm it locally.
- **The consequence:** the projection hashes "actual retrieved archive snapshot 200 response" bytes, so `judgment_digest` differs on every recheck. For a held 403 + archive URL with a `same_bug=false` or unresolved verdict, every 5/10/20/40/60-second cycle is a new identity and buys a new paid confirmation call until the deadline. That is exactly the review-6 failure.
- **Why the planned test misses it:** the two-cycle test uses authored snapshot bytes that are identical by construction (`:2650-2654`, `:2610-2612`). It would pass while the real path fails.
- **Needed:**
  - Retrieve and hash the raw snapshot by rewriting the selected URL to the `<ts>id_/` form. Keep `archive_snapshot_url` as the selected URL, so `agrees` and the `archived` regex are unchanged (the regex already accepts `id_`). Alternatively, say explicitly which normalised bytes are hashed.
  - State that a change in the availability API's `closest` timestamp is legitimate new evidence.
  - Make the test cover the replay-wrapper difference. For example, give the two cycles bodies that differ only in the Wayback trailer, with the authored-input label, and assert the raw `id_` URL is the one requested.

## Nits

1. **Receipt shape for `archive=False`:** define the receipt a live-only access or network failure produces (`retrieved_from`, `archive_available`, `responses`). Today `g2` marks a row unfetched when `retrieved_from == 'none'` (`run.py:1977`), and `load` rejects an empty `responses` list (`freshness_retrieval.py:95`). An implementer would have to pick values that keep both checks working.
2. **Where the hold loop lives:** `ensure_freshness` currently raises `freshness_review_unavailable` on any `review_unresolved` (`run.py:643`). Name the predicate that turns this into a backoff hold: a blocked flagged row whose current receipt has an `access_failure` status, or whose archive lookup failed. Everything else, such as an unresolved verdict on a live 200 page, still raises. `recovery.py:83-87` should stay consistent with it.
3. **Live 200 pages:** dynamic pages (CSRF tokens, nonces) will also produce a new content hash on each fetch. No loop follows from this today, because a resolved live verdict either clears or confirms, and an unresolved one raises rather than holding. One sentence saying so would stop a later reader from extending the hold to live pages.

## Author response

Accepted the blocker and all three nits. Specify raw id_ snapshot fetching and test the requested URL; retain selected snapshot identity, treat changed timestamps as new evidence. Defined live-only failure receipt shape and the precise G2 transport hold predicate. These small corrections are implemented without another design delegate, per orchestration instruction. No findings are rejected; fresh diff review remains required.
