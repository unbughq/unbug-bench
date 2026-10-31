# Stream D ordinary retries: design review 6

Reviewer: Claude Opus 5.5. Final report follows verbatim.

**FAIL: one blocking finding.**

I reviewed `docs/designs/stream-d.md:2150-2612` in worktree `t3-21bef30c` at `b500db9`, including the uncommitted edits. Where later amendments conflict with earlier wording, I treated the later amendment as the rule. Scope was item 4, batch only. Items 5 and 6 belong to the other lane, and items 7 and 8 come later. Row 13 closure is deferred, and the row 15 claim covers only routes with an approved equivalent chain. I read it with the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW, against the Heilmeier and implementation-readiness standards. I checked it against `factory/run.py` (`g2`, `confirm_hits`, `checked_freshness_verdict`), `factory/freshness_retrieval.py`, `factory/model_router.py` and `factory/prompts/attacker.md`. I saved nothing.

The two review-5 blockers are resolved:
- **Stress coverage list:** every subcheck ID maps to existing prompt text. `prior_families` maps to `attacker.md:29`, and the rest match section 1, the four checks in section 2, the five rules in section 3 and the V2 strategies and checks. The continuation rule now has one reading, the first call is compared against an empty set, and a completed blocker ends the round first. The number of calls is finite.
- **Archive predicates:** these now live in `checked_freshness_verdict` (`run.py:2183-2190`), which is the right place. `dead` stays narrow, `access_failure` is separate, and `unreachable` still requires `dead`. A bot-walled snapshot can confirm a match but cannot clear it.
  - In the existing code, a valid `same_bug=false` that is not cleared is added to `blocked` without incrementing `freshness_confirmed_hits`. `g2` then reports `review_unresolved` with `invalid-infra`, which matches the pending hold the design wants.
- **Claude routes:** the single-route claim is correct. For `claude/` models, `routes()` gives one route on two accounts (`model_router.py:96-116`).

## Blocking

**1. The held-URL recheck loop can buy a new paid confirmation call on every cycle, because "new retrieval evidence" is never defined** (`:2589-2594` against the caller identity at `:2435-2436`).
- **What the design says:** a held flagged URL rechecks the live page and the archive every 5, 10, 20, 40, then 60 seconds until the deadline, with "no additional model call before new retrieval evidence".
- **What the code does:** the G2 caller identity is defined as "confirmation_contract binding plus trusted retrieval digest". `freshness_retrieval.digest` hashes the whole receipt list, and each receipt has a fresh `at` timestamp (`freshness_retrieval.py:45`, `:107-108`). Retained-verdict reuse in `confirm_hits` also keys on that digest (`run.py:2064-2086`).
- **The consequence:** every recheck produces a new digest, even when the result is the same 403 and the same snapshot. As written, the identity rule says each cycle is a new identity, so `confirm_hits` makes a new paid reviewer call about once a minute until the batch deadline. On a page with a 403 and an archive copy, a reviewer answer of `same_bug=false` keeps the URL pending forever, so this becomes a steady paid loop. Only the batch money bound stops it. The two rules contradict each other, and the implementer has to choose between them, which breaks the zero-decision rule.
- **Needed:**
  - Define an evidence projection that leaves out `at`, response directory names and other volatile metadata. It should contain the URL, `retrieved_from`, `live_failure`, `archive_available`, `archive_snapshot_url` and the sha256 of each snapshot or live 200 body.
  - Say whether the body of an access-failure response is kept, and if so leave it out of the projection. Bot-wall pages often carry per-request nonces, which would make every recheck look new.
  - Key G2 reuse on that projection: unchanged evidence reuses the retained verdict with no model call.
  - Add a test with two consecutive identical 403 + snapshot cycles: the second must make no reviewer call.

## Nits

1. **Unflagged URLs with access failures:** say whether an unflagged 403/5xx URL also tries the archive after its 120-second window, and whether an archived copy then counts toward the search minima. Today, any receipt where `retrieved_from != 'none'` counts as fetched (`run.py:1975`). `:2525` and `:2571` can be read either way.
2. **Name the two-phase retrieval interface:** today `fetch` raises `InvalidInfra` for 403 and the like, which loses the status (`freshness_retrieval.py:31`), and `retrieve` asks the archive as soon as the status is not 200. The design needs live-only attempts during the window, then the archive. Name the change, for example a returned status plus an `archive=` flag on `retrieve`, so the implementer does not invent it.
3. **State the call bound per round:** each category gets at most as many calls as it has subchecks, so 7 + 4 + 5 + 7 = 23 stress calls per round, plus repairs. Stating this gives item 8 a concrete admission ceiling to measure against.
4. **Shared diagnostic causes false exhaustion:** the diagnostic allowance (`attacker-{round}`) is shared across categories. If one category uses it, another category that wants it will report `unfinished_validation` and end in `stress_validation_exhausted`. This follows from deferring row 13, but saying so stops a later reader from treating it as a bug in this increment.
5. **Who decides completeness:** a report with every subcheck done and no unfinished validation, but `category_complete=false`, is exhausted under the current wording. Consider having the runner work out category completeness from the subchecks and the completion marker, rather than trusting the model's boolean. That is one less thing the model can get wrong.

## Author response

All findings accepted. Added a stable normalized judgment projection separate from full receipt integrity, content-identical unresolved verdict reuse, and a two-cycle 403/snapshot no-extra-call test. Specified two-phase retrieval, unflagged archive behavior and the 23 completed-call stress bound. Kept category_complete as an explicit conservative assertion and documented shared diagnostic exhaustion. No implementation has started.

