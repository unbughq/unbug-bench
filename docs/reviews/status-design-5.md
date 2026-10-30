**Verdict: FAIL.** One blocker and three majors are open. The PASS4 design and your required calls column both hold. The new staged-core adapter section leaves the implementer to decide which state each journal row is in.

---

# Goldfish design review 5: docs/designs/status.md (de70d12 vs 16c5943)

Reviewer: fresh Claude Opus subagent, personas zoom_out, design_critic and implementation_readiness, Mode: REVIEW, read-only. I used the heilmeier and implementation-readiness standards. I read only `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, with no live queries, decryption or cloud access. Verbatim.

**FAIL.** One BLOCKING finding and three MAJOR findings.

What holds up:
- The PASS4 content is unchanged: sealed/rejected definitions, the 5 h rule, Boat failure leading to `boat unreadable`, and the deferred wallet rule.
- **Calls column:** "calls N or calls —, no denominator, no call near-limit rule" matches the requirement. All 51 local real cards that have `continuation_budget` store `calls` as an int. 40 of them are above the historical `max_total_calls=300` (`factory/budget.py:500`), so the "above historical max, no alert" test uses real numbers.
- **Selection:** a unique entry, or a verified `current/<case>.json` pointer, otherwise unreadable. No dict order, mtime or filename chronology. This fails closed correctly against a core that writes no pointers.
- **Bounded reads:** one bounded Boat list, one `cat` per running worker confirmed present, no writes, no spend.

1. **BLOCKING: row classification against the real staged core is undecided.** (Affects "The read adapter also accepts…" and "For each manifest root…".)
   - **"Pending" means two different things.** `batch_service._load` (`factory/batch_service.py:89-112`) only accepts entries with exactly `{job, case, generation, manifest_sha256, state, facts}` and `state == 'pending'`. In the core, "pending" means collected and waiting for diagnosis planning. In the umbrella (`batch-service.md:44-48`), "pending" means a launch was submitted and not yet accepted. The design says "a core pending entry's own verified snapshot is its collected card" and also "pending/failed rows with no card show that state". It never says how to tell a core entry from an umbrella one.
   - **Resume rows get two answers.** An umbrella resume row keyed `case/G` has a verified snapshot G. One rule reads it as "stopped on card G", the other as "pending". Both readings fit the text.
   - **Cases with no journal entry have no rule.** In the current core, a case that launched but hasn't been collected has no entry at all. That is the most common case today. The design gives no display, no count bucket, and no rule interaction (worker gone, launch stuck) for it.
   - **Fix:**
     - An entry with exactly the core key set is stopped, using its own snapshot.
     - An entry with any umbrella field uses umbrella semantics. A pending or failed row shows that state, and its generation card supplies only "last card" spend, rounds and calls, never stopped-case rules.
     - A manifest root or recorded derived job with no entry shows as `not collected`. It gets its own count, never `worker gone`, never `launch stuck`.

2. **MAJOR (zoom_out, reuse): the adapter's optional umbrella fields contradict the only journal validator.** (Affects "The read adapter also accepts…".)
   - `_load` rejects any extra entry key. So "accepts optional fields state, worker_id, pending_since, collected_generation" needs a second, lenient journal parser. That duplicates schema validation for fields no producer writes yet ("fresh launch/operation fields wait for the holder addendum", `batch-service.md:894-895`). That is YAGNI.
   - **Simplest fix:** reuse `_load` and `resolve_job` read-only. Treat umbrella fields as `unreadable` until the holder addendum extends `_load`. This also removes most of finding 1.
   - **Absent journal:** `_load` returns a default empty state when `journal.json` is missing. Status must treat a missing journal as unreadable, not as "zero entries".
   - **No lock helper:** status must not call `batch_money.locked`. It runs `mkdir` and creates a `lock` file, which breaks "writes nothing".

3. **MAJOR (source consistency): Data sources section 4 contradicts the new section.**
   - Section 4 still says the card is `sealed/<case>.scorecard.json`, matched against "the journal's latest collected generation".
   - The new section reads only the card pinned by the snapshot manifest, and says never fall back to a flat card "with an unrelated generation". That wording implies a flat card with a matching generation is allowed.
   - The umbrella keeps legacy flat files as read-only compatibility inputs (`batch-service.md:195`).
   - Source 1 also still uses umbrella `launched`/`failed` wording that the core never produces.
   - **Fix:** pick one rule (snapshot-pinned card only, or flat card only when its sha equals the selected generation). Rewrite sources 1 and 4 to match it.

4. **MAJOR (implementation readiness, old real card fields): the release binding means no real saved card passes unchanged.**
   - None of the 53 local real cards in `sealed/` carry `batch_release_sha256`. The adapter requires the card to match the release.
   - So "use the existing real public-card corpus for sealed/rejected/old-card tests" can't go through the real read path without editing the cards. That breaks the real-artifacts rule without saying so.
   - **Fix:** state the split:
     - test the classification and rendering function on unmodified real cards: 5 sealed, 13 rejected, all 53 lack `case_budget`;
     - test snapshot, manifest, release and case binding on an authored snapshot;
     - disclose the authored snapshot in the test.

Nits:

5. **`calls` typing:** a value that is not an int, a bool, or negative should render `?`, so it can't print as "calls True".

6. **Known stop list:** it is still not enumerated. Local real cards carry `provider_limit:*` (8 of 53), `total_call_limit`, `call_limit`, `stalled`, and one free-form `Budget ledger stopped: …`. Say which of these get plain words and which show `unknown stop, check case`. Without that, `provider_limit:*` fires `check case` on about 15% of cards.

7. **Pointer file:** say it must be a regular non-symlink file with exactly `{generation, manifest_sha256}`, and that the selected entry's case must equal the pointer's filename case.

8. **Pagination:** `pageInfo.hasMore == true` gives a permanent `boat unreadable` once the inventory goes past one page. That is acceptable as fail-closed, but the design should say so as a known limit.

Fix finding 1, and either fix or accept findings 2–4, before implementation starts.

---

I made no edits. If you want the record kept, save this verbatim to `docs/reviews/status-design-5.md`.

---

## Elephant resolution

All findings accepted. Reuse batch_service._load with an explicit missing-file
check and a shared read lock opened read-only; no second lenient journal parser.
Core entries are stopped; jobs without entries are not collected and cannot
trigger worker-gone/launch-stuck. Future umbrella entries remain unreadable until
the holder addendum extends the shared validator. The pure formatter and injected
transport tests cover the reviewed running/pending/failed view, but the production
adapter cannot infer that view from current core entries. This limitation is
explicit, not a fabricated running claim. Sources now name snapshot-pinned cards
only. Separate unmodified saved-card classification from authored binding fixtures.
Enumerate known stops, strict call display, pointer schema and pagination limit.
No rejected findings, launch enablement, VM changes, spend or Murphy closures.

