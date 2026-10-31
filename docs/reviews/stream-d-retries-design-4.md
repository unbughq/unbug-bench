# Stream D ordinary retries: design review 4

Reviewer: Claude Opus 5.5. Final report follows verbatim.

**FAIL: 3 blocking findings.**

I reviewed `docs/designs/stream-d.md:2150-2458` (the fourth increment plus the review 2 and review 3 resolutions) against `factory/run.py`, `factory/budget.py`, `factory/model_router.py`, `factory/model_runtime.py`, `factory/durable_checkpoint.py`, `factory/freshness_retrieval.py`, `factory/attack_findings.py`, `factory/prompts/attacker.md` and `bin/run_validity.py`. I used the zoom_out, design_critic and implementation_readiness personas with the Heilmeier and implementation-readiness standards, in Mode: REVIEW. Where review 3 wording conflicts with earlier wording, I read review 3 as the rule. I edited nothing and saved nothing.

All four blockers from review 3 are answered:
- the stress receipt now has a state machine;
- a decision-projection check stops a repair from manufacturing an approval;
- a broad outage no longer charges defect attempts;
- publication retries in place instead of stopping.

I checked these seams in the code and they work as described:
- Several category calls can share one `operation_id`, because `reserve_invocation` keys on the lease (`budget.py:157`).
- Router exclusions use `pool/route`, so reconstructing them from spent route strings is consistent (`model_router.py:213`, `:429`).
- `case_hash` ignores `freshness.jsonl` (`run.py:806`), so refreshing evidence does not invalidate stress coverage.

## Blocking

1. **A category that finishes with unfinished validation has no bound and no next step** (`:2200-2202`, `:2283`, `:2336`, `:2347`).
   - The design deletes the current `unfinished_validation` stop (`run.py:1408`) and says a completed call with unfinished validation "cannot complete its category". It then says unfinished categories "continue". It never says how many times one category may be sent again, or what counts as progress.
   - The round's one diagnostic stays shared across all four categories (`attacker-{round}`). Once the first category uses it, every later call is told "EXHAUSTED … record unexecuted checks in unfinished_validation" (`run.py:420-423`, `attacker.md:47`, `:113`).
   - So a category that needs execution evidence returns `category_complete=false` every time. Each of those calls completes normally: it is not malformed and not a transport failure. The likely implementation therefore pays for repeated calls until the batch money or deadline runs out.
   - The stop for a diagnostic that was claimed but never completed (`run.py:1418`) also stays. Murphy row 13 lists both of these as its failure ("exhausted or unfinished diagnostics can leave an unrecoverable stop"), yet the design claims to close row 13.
   - **Needed:**
     - a bound on continuation (for example, a further call only if the earlier call added coverage or findings);
     - the label used when that bound is hit;
     - what happens to a diagnostic interrupted by a kill (re-grant it, or classify it as transport).

2. **Repairs of undecodable or missing output are guaranteed to fail, and still cost a paid call on every route** (`:2364-2385`).
   - The guard is right that a repair must not invent decisions. But when no trustworthy projection exists, every result is either unresolved or invalid. Both spend the route, so every approved route is called and the path always ends in `malformed_output_exhausted`.
   - These are the commonest malformed cases (undecodable syntax, missing fields, empty output). They pay N calls for zero chance of success and still stop. With diagnosis off, that stop is a pit stop.
   - Row 15's fix says "then retry an approved equivalent model". The design never does a fresh scientific call, yet claims row 15 (`:2232`).
   - **Needed:** when no projection exists, skip the schema-only call. Then either send the original full request to the next approved route under the same identity (a completed malformed answer spends that route), or stop claiming row 15 for this class.

3. **A flagged URL that the runner can never fetch holds the case until the batch deadline, and never tries the archive** (`:2252-2256`, `:2422-2425`, with `freshness_retrieval.py:22-31`).
   - `fetch` sends a bare `unbug-bench-retrieval/1` user agent. Any status other than 200, 404 or 410 (403 bot walls, 401, 451, 429, 5xx) raises `InvalidInfra` immediately. The archive fallback only runs for 404, 410 and DNS failure (`:51-53`).
   - Under the new rule, flagged URLs "remain pending through transport retry until retrievable or the batch deadline". A forum or Reddit-style hit that always returns 403 to this user agent is a fixed, repeatable failure dressed as transport. The case occupies its worker for the whole batch and then retires as `retired_batch_bound`.
   - Today that case at least stops visibly after two attempts. Review 3 accepted holding the slot for URLs that are truly unavailable. This case is different: archive evidence may well exist and is never fetched.
   - **Needed:** after the retry window, a persistent non-404 HTTP failure goes through the existing archive path. Only a failed archive lookup keeps the URL pending. Say whether the deadline hold then still applies.

## Nits

1. Within one run, `pending_call` calls `on_admitted=review_admitted` for every category (`run.py:1442-1450`). As written, each category would rename the aggregate to a superseded file and add a `release_review_attempts` entry. The design forbids this only on resume (`:2346`). State that `review_admitted` runs once per operation.
2. Name the one place the publication barrier is checked. `model_runtime.dispatch` (`model_runtime.py:57`) is the single dispatch point; "before any new model call" (`:2311`) leaves the choice of call sites to the implementer.
3. `_opencode` already runs a throttled `checkpoint_progress` after `on_complete` (`run.py:215-219`). The forced `interval=0` checkpoint can upload twice per category. Say which one is the publication checkpoint.
4. Say whether a "definite blocking finding" from a category call that never completed (partial bytes) may end the round early, or only findings from completed calls.
5. Give the file name for each continuation attempt's category output, so that "interrupted partial bytes remain separately" cannot be met by overwriting `<category>.json`.
6. Say explicitly that batch G2's flagged path stops calling `run_validity.retry` (`run.py:1963`). Otherwise "without changing bin/run_validity.retry" (`:2296`) reads as keeping its two-attempt cap there.

## Author response

All findings accepted. Added a finite fixed-subcheck progress rule for completed incomplete stress calls, recognized operational exhaustion, and explicit non-regrant of interrupted diagnostics. Row 13 remains open for item 7/8 automatic diagnostic recovery rather than overclaiming closure here. Unprojectable output now skips futile repair and tries a full original request on the next equivalent route; projectable answers still get guarded schema repair first. Persistent live HTTP denial attempts archive retrieval without treating archive absence as proof a bot-walled live page is gone. Addressed all six integration nits in the design. No implementation has started.
