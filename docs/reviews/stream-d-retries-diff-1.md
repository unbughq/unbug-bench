**FAIL: 2 blocking findings are open.**

I reviewed `b500db9..c22dbd6` against `docs/designs/stream-d.md` from "Fourth increment" to the end of the file, using Mode: REVIEW, the `zoom_out` and `implementation_readiness` personas, and the implementation-readiness standard. I read the files only. I did not run tests or edit anything.

### Blockers

**1. A bot-walled URL next to a changing live page buys a new paid reviewer call on every hold cycle, until the batch deadline or the money runs out.**
- **Where:** `factory/ordinary_freshness.py:107-112` and `:39`; `factory/run.py:2179-2183` and `:2239-2241`; `factory/freshness_retrieval.py:146-153`.
- **How it happens:** say a case has two flagged URLs. One returns HTTP 403 and has an archive snapshot. The other is a normal live page, such as a GitHub issue, whose HTML changes on every request.
  - The 403 row can never be cleared, so `checked_freshness_verdict` sets `freshness_transport_pending`.
  - `ensure` then backs off and sets `freshness_force_refetch`.
  - The next pass of `confirm_hits` calls `obtain` again for both URLs. `obtain` returns early only if every row is live, so it re-fetches the live page too.
  - The new live bytes change `judgment_digest`, so the retained-answer identity changes and a new paid reviewer call is made.
  - Nothing limits how many times this loop repeats.
- **What the design says:** review 7 says changing live-200 pages "never enter this hold loop". Review 5 says there is "no additional model call before new retrieval evidence". Review 2 says "Successful fetches are reused".
- **Tests:** no test covers the real hold loop. `test_identical_access_failed_snapshot_reuses_unresolved_judgment` replaces `obtain`, and `test_broad_outage_retries_without_buying_topup` replaces `_g2`. Row 12 still claims that held flagged URLs are proven.
- **Fix:** reuse the receipts already fetched for rows that came back live during a hold, or hold before asking the reviewer again. Add a real-orchestration test with one 403 URL and one live URL whose body changes, and assert the reviewer is called once across several cycles.

**2. In category mode, an interrupted diagnostic can still end in the old `stress_review_unresolved:unfinished_diagnostic` stop, which diagnosis does not recognise.**
- **Where:** `factory/stress_progress.py:83-84` and `:137` call `completed()` without checking `attack_diagnostic_unfinished`. `factory/run.py:1525` then runs the old branch on the normal path, and `:1353` does the same on resume.
- **How it happens:** the round's one diagnostic is claimed during the last category (`v2_strategies`) and then times out. The model can still honestly finish every inspection subcheck, because executing the diagnostic is optional. The category completes, the aggregate completes, and `write_and_attack` raises `unfinished_diagnostic`.
- **What the design says:** review 4 says "The old unfinished_diagnostic and unfinished_validation terminal branches in category mode are replaced by that single recognized exhaustion." `diagnosis._trigger` (`factory/diagnosis.py:46-47`) does not list this label, so the stop would need a person.
- **Fix:** before each `completed()` in `stress_progress.run`, raise `stress_validation_exhausted` if the diagnostic is unfinished. Add a test where the diagnostic is claimed and timed out during the last category.

### Major (not blocking)

**3. A kill between two writes lets the next category call run before the last finished category is published.**
- **Where:** `factory/stress_progress.py:130-133`.
- The category state is saved at line 130, but the pending-publication marker is written in a separate file at line 132.
- If the process dies between the two, resume finds no marker (`:81` does nothing), so the next category call runs before the completed category is checkpointed to remote storage. This breaks "Missing remote publication blocks next paid call."
- **Fix:** write the marker before `save()`, or inside `state.json` as the design says. An extra checkpoint is harmless.

**4. The batch confirmation prompt contradicts the receipt rules for access failures.**
- **Where:** `factory/run.py:2217` still limits `live_failure` to `http_404|http_410|dns_failure|deleted|null`, and the base text still says "access errors ... remain unresolved". The text appended at `:2233-2235` never tells the model to record `live_failure: http_403` or `network_error`.
- A model that follows the listed values fails `agrees()`. Because that unresolved answer is reused for the same evidence, the URL then stays held until the deadline.
- **Fix:** make the allowed values and instructions conditional on batch mode.

**5. Several tests the design lists are missing.**
- Changing the snapshot body, the page coming back live, or the case context changing must each require a new judgment (review 6).
- A 403 URL with no archive must stay pending until live recovery or the deadline. Today only `checked_freshness_verdict` is unit-tested for this, not the hold loop or the recovery.
- Changed binding must not reuse category coverage, under the real orchestrator. The only rebind test uses the single-call adapter.
- Cancellation must work during `backoff`. The tests either replace `backoff` or cancel before the call is made.
- The `freshness-repair.json` v1 migration.

**6. Row 11's "Closed by" cites `tests/factory/test_stream_d_runtime.py` as a whole file.**
- The batch bypass of the restart limits (`restart.py:57/:83`) and the holder limit (`key_holder.py:185`) is backed only by the grep-count test `test_every_max_cost_occurrence_is_classified`. That is not a behaviour test, and the design asked to "prove that boundary".
- **Fix:** name the specific tests, or narrow the row's claim.

**7. A broad outage that returns HTTP error codes can still buy one paid top-up.**
- **Where:** `factory/run.py:2052-2058` and `:2087`.
- A row that comes back 403 or 5xx with no archive copy does not raise `InvalidInfra`, so it is not counted in `transport_failures`. As a result `all_transport_failed` stays false even when every row is unfetched.
- The design (review 3) says no model top-up should launch in that case. The `last_topup` check limits the damage to one extra purchase.

### Nits
1. `freshness_force_refetch` is set on `c` and never cleared (`ordinary_freshness.py:111`). Every later G2 pass re-fetches everything and repeats the 120-second windows.
2. Flagged rows are fetched twice per pass: once in `_g2` per row and again in `confirm_hits`. That means two live windows per cycle.
3. The calls run on a `copy.copy(c)` (`ordinary_retry.py:175`), so runtime attributes set during a call, such as `budget_resumed` and newly created `router_waits` lists, never reach the original `c`.
4. If the binding changes while a stress call is running, the code raises the new `stress_case_changed` label (`stress_progress.py:123`). The existing `case_changed_during_review` label already covers this.
5. Partial findings are kept on disk but not put into the continuation prompt (`stress_progress.py:100`). The model can only find them through the `attacks/` directory, although the design says they are included.
6. `transport` failure counts persist for each identity, so later first failures wait the full 60 seconds.
7. Small style issues: `__import__('time')` (`stress_progress.py:117`), an import inside a function (`ordinary_freshness.py:56`), and a v1 migration that raises `KeyError` if `statement_sha256` is missing.
8. The G2 confirmation `deadline` is computed once (`run.py:2251`), so a repair after a long first call can time out immediately.

### Verified as matching the design
- **Schema repair (`ordinary_retry`):**
  - each attempt is persisted with its kind, route and completion marker;
  - a repair must keep the exact same decision fields as the original answer;
  - output with no usable decision skips repair and goes to the next equivalent model;
  - the "all routes used" check happens before admission;
  - an interrupted repair stays pending without using up a route.
- **Category state:** the category state machine uses one operation for the whole round, keeps completed categories (tested), and the aggregate re-checks each category's digest.
- **Stress bounds:** the no-progress and last-subcheck limits, and the rule that a blocking finding takes precedence, are tested.
- **Publication:** the barrier runs inside the dispatch lock, and a configuration with no recipient fails closed.
- **Archive retrieval:**
  - raw `id_` archive bytes are fetched;
  - replaced retrieval directories are renamed, not overwritten;
  - the judgment identity leaves out access-error bodies;
  - `run_validity.retry` has been removed from batch flagged retrieval.
- **Labels:** diagnosis only gains the three new exhaustion labels.
- **Row 13:** stays open.
- **Suite:** the record `docs/reviews/stream-d-retries-suite-2.md` is present. I did not re-run the suite.

## Author response

All findings are accepted. Blocker 1 is fixed by a shared per-URL retrieval cache: held URLs refresh once per hold cycle while live successes retain their authenticated bytes. Real G2 orchestration tests cover a bot wall beside a changing live page, archive absence through live recovery, and broad HTTP outages without paid top-ups. Blocker 2 is fixed at aggregate completion and the saved-report resume boundary; a last-category timed-out diagnostic raises stress_validation_exhausted on both entry paths.

The publication marker now precedes the category-state commit, with a crash-between-writes test. Batch confirmation instructions accept exact access-failure statuses, and access failures with no archive count as transport outages. Added tests cover changed snapshot bytes and case context, changed category binding, cancellation during backoff, v1 freshness migration, five stress interruptions and the batch bypass of legacy restart/holder bounds. Row 11 cites these specific behavior tests.

The force-refetch flag is replaced by a per-cycle URL set, and shared retrieval avoids duplicate flagged fetches. Dispatch state is initialized before copying call contexts; scalar budget state and newly observed outage exclusions propagate back. Backoff starts anew for each transport invocation while retaining cumulative telemetry. Partial report paths are explicit continuation inputs, the existing case_changed_during_review label is reused, imports are ordinary module imports, malformed v1 state fails explicitly, and each G2 repair gets its own runtime timeout. No findings are rejected. Full-suite and fresh re-review results are recorded separately.

