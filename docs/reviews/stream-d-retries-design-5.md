# Stream D ordinary retries: design review 5

Reviewer: Claude Opus 5.5. Final report follows verbatim.

I found two blocking gaps. Writing up the verdict now.

**FAIL: 2 blocking findings.**

I reviewed `docs/designs/stream-d.md:2150-2537` in the worktree as of `b500db9`, with the uncommitted design edits included. Where review 4 wording conflicts with earlier wording, I read review 4 as the rule. I used the zoom_out, design_critic and implementation_readiness personas in Mode: REVIEW, against the Heilmeier and implementation-readiness standards. I checked the design against `factory/run.py`, `factory/freshness_retrieval.py`, `factory/model_router.py`, `factory/model_runtime.py`, `factory/prompts/attacker.md` and Murphy rows 11–15. I edited and saved nothing.

The four review 4 blockers are mostly answered:
- **Unbounded continuation:** there is now a progress rule, and the outcome when it runs out has a label.
- **Repairs that could never succeed:** unprojectable output now skips repair and sends the original full request to the next route.
- **403 and similar responses:** these now try the archive.
- **Row 13:** the design now says honestly that it stays open.

The scope cut is fine. Diagnostic-exhaustion recovery is left to item 7/8 and does not block this review. The dispatch barrier is placed correctly: `model_runtime.dispatch` holds `model_dispatch_lock`, an RLock, for the whole call (`model_runtime.py:57-74`). So a check after taking the lock does guarantee that no category call is active during publication.

## Blocking

**1. The stress continuation bound is not defined well enough to implement, and its own text contradicts itself** (`:2463-2478`).
- **The list of subchecks the bound counts doesn't exist.** The bound counts "explicit completed subchecks from a fixed list in that category's prompt". `attacker.md` has no such list, and the design doesn't supply one.
  - The implementer would have to write the coverage contract for the stress gate. That is bench logic, and it decides when a category counts as covered.
  - The prompt's existing bullets could serve, for example the wrong-fix families in §1, the four checks in §2, the five rules in §3 and the four V2 strategies. The design has to name them and give them stable IDs.
- **Contradiction:** "only if it added a new fixed subcheck or substantive finding" conflicts with "only new completed subchecks grant continuation". Pick one.
- **"One continuation is allowed":** this can be read as one continuation per category in total, or one more call after each step that makes progress. The phrase "finite subcheck set" implies the second reading. Say so, and say that the first call is measured against an empty state.
- **What counts as finished is unclear:** say whether `category_complete=true` also requires every fixed subcheck to be reported done. If it doesn't, a category can claim coverage while skipping listed subchecks.

**2. The archive fallback names the wrong place to change, and the obvious edit breaks the design's own invariant** (`:2509-2523`).
- **The design names the wrong code.** It says "extend only the retrieval-agreement validator's accepted failure status syntax". But `agrees` (`freshness_retrieval.py:110-116`) only checks that the answer matches the receipt. It has no list of allowed statuses. The real gate is in `g2` (`run.py:2183-2190`): `archived` requires `dead`, and `dead` is limited to 404/410/DNS failure/deleted.
- **The obvious edit clears bot-walled pages.** An implementer who widens `dead` to include `http_403` and the others also widens `unreachable`. A 403 page with no archived copy would then be counted as `unreachable_hits` and skipped. That is the exact clearance `:2516-2519` forbids.
- **Needed:** split the two predicates. `archived` accepts dead statuses plus access failures. `unreachable` stays limited to dead statuses. Also update the status list in the confirmation prompt (`run.py:2123`).
- **Needed:** name the `live_failure` value for network errors that have no HTTP response. `network_error` would do.
- **Needed:** decide what `same_bug=false` from an archived copy means when the live page is only bot-walled. The design's own argument is that the live page may still be public and current. By that argument, an old snapshot could miss later comments that match the bug. Either a snapshot behind an access failure can only confirm a hit, or the design states that clearing on a snapshot is accepted and gives the reason.

## Nits

1. **Order of outcomes:** a completed category can report both a blocking finding and `unfinished_validation`, or make no progress while blockers already exist. State that the blocker ends the round before `stress_validation_exhausted` is raised. This matches the legacy `not findings` order (`run.py:1244`, `:1447`), and "as before" at `:2196` implies it.
2. **Claude models get no second route:** `routes()` returns two accounts but only one model route for `claude/` models (`model_router.py:96-116`), and account changes don't count. So unprojectable output from a Claude-routed caller goes straight to `malformed_output_exhausted`. Say this, and say that the row 15 claim covers only models with an equivalent chain.
3. **The test list (`:2221-2230`) predates review 4.** Add tests for:
   - stopping on no progress, and on using up all subchecks;
   - an interrupted diagnostic becoming exhaustion;
   - an unprojectable answer leading to a full request on the next route;
   - a 403 followed by an archive copy, and a 403 with no archive copy staying held.

   `invalid-runs-http.json.gz` holds only one 200 response. So the 4xx/5xx and archive bodies will be authored, and the design should label them as authored, as it already does for stress reports (`:2455-2458`).
4. **Deadline hold:** say how often the runner re-checks the live page and the archive while a flagged URL is held until the deadline. Each re-check is another archive API request.
5. **Row 13 wording:** `:2232` still lists row 13 as "targeted". The narrowing at `:2490` overrides it, but editing the line itself would stop a later reader from claiming the row is closed.

## Author response

All findings accepted. Enumerated fixed category subchecks, required all for completion, and made continuation depend only on new subchecks after each completed call. Completed blockers take precedence. Split archive access-failure handling from dead-page clearance in checked_freshness_verdict; access-failure snapshots can confirm but never clear. Named network_error, the retry cadence, single-route Claude limitation and added the requested tests with authored transport provenance. Row 13's original target wording is corrected. No implementation has started.

