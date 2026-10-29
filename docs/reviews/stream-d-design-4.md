# Goldfish review, round 4: Stream D design (`docs/designs/stream-d.md`)

**Mode:** REVIEW, read-only. I made no writes, launches, decryption, credential reads or paid calls.
**Personas:** zoom_out, design_critic, implementation_readiness.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.
**Binding contract:** `/Users/bugsincode/Developer/unbug-bench/docs/designs/interfaces.md`, read in full (history 9699e5d, c49c754, 4a10966).

**Scope read:**
- `stream-d.md` in full, `extensions.md`, and `stream-d-cost-evidence.json`.
- The `docs/factory-single-path.md` diff. A keyword search found no stale "two replacements", "three retries", "$15" or "max-cost" text in that file.
- `stream-d-design-{1,2,3}.md`, including the elephant resolutions.
- `docs/ENGINEERING.md` and Murphy rows 8, 9 and 11.
- Code, to check the design's claims:
  - `run.py` (916–970, 1076–1190, 1949–2060, 2145–2170, 2290–2315, 2400, 2499, 2532), `budget.py` (48–110, 190–310, 350–355), `model_runtime.py` (178–215, 335–360).
  - `restart.py`, `key_holder.py`, `coordinator.py`, `ttl_continuation.py`, `g11_review.py`, `carry_over.py`, `gate_state.py`, `late_recovery.py`, `recovery.py`.
  - `exam_responder.py`, `bin/run-exam`, `factory/README.md`, `tests/`.

## Verdict: NOT PASS

**One blocking finding is open (B1).** It is a new problem in D's own scheduling rule, not a repeat. The round-3 fixes hold. The B1 deletion inventory and M1–M8 are all resolved, and every cited line number matches the code. The notes below are optional and should not delay the merge.

## Round-3 fix verification

| Round-3 finding | Status | Evidence |
|---|---|---|
| **B1** paid-cap inventory | **Fixed.** | Every live site is now named and the line numbers match. |
| M1 exhaustion stops, ruling retirement | **Fixed.** | Four stops are listed. |
| M2 single effective money source | **Fixed.** | One source feeds all four read sites. |
| M3 totals remainder | **Fixed.** | Full observed sums come first. |
| M4 serialization | **Mostly fixed, but see new B1.** | Lock approach and `concurrent_roles` are right; the lock does not cover the nested owner call. |
| M5 zero-work chain | **Fixed.** | Zero-work exhaustion retires the chain. |
| M6 receipt v2 and clamps | **Fixed.** | V2 is additive; the clamp is bypassed only for an active extension. |
| M7 route-maxima prerequisite | **Fixed.** | A writer maximum above the ordinary limit blocks enabling D. |
| M8 test list | **Fixed.** | The files are listed. The list is partial (see O3), and the search exam covers the rest. |

**B1, paid-cap inventory.** The design now names:
- `restart.py:57/72/76`: the three-retry limit, the `--max-cost` check, and the original `--case-budget` read.
- The D-owned allowance sites at `run.py:916/936/1027/1110`.
- `key_holder.py:185–196`: the cohort cap, as a B-owned minimal edit.
- `carry_over.py:37–39/242/330–340`.
- `ttl_continuation.py:192/194/281`, as B-owned.
- `bin/run-exam:250/270/279`, retained with its $5 owner cap through an optional shared-runner `max_cost`.

Passing `None` is allowed only with authenticated job authority. A `None` without authority is rejected, and the design says so.

Before moving on, I checked that no unlisted live `max_cost` enforcement remains. The whole `factory/` and `bin/` grep gives these sites. Each is either named in the inventory or the retained exam-owner path:
- `budget.py:190/204/217/263/307`
- `model_runtime.py:345`
- `run.py:1949/2400/2499`
- `gate_state.py:124/141`
- `coordinator.py:28/162`
- `ttl_continuation.py:34/155/175/243–244`
- `key_holder.py:311`
- `g11_review.py:100–119/169`
- `restart.py:72`
- `bin/run-exam`

**M1, exhaustion stops.** The four stops map to the code:
- `budget_exhausted` and `stress_review_unresolved:rounds_exhausted` are the stops at `run.py:1078/1187`.
- `late_defect_needs_ruling:<gate>` is raised at `late_recovery.py:107` and refused at `recovery.py:164`.
- The fourth is the active extension's completed gate-still-failing outcome.

The keep/delete split of `run.py` ~1155–1186 is correct. Lines 1155–1179 write the `final_repair` receipt and emit the stop, so they stay. Lines 1180–1186 are the `builder-precheck` call and the G1 and early checks, so they go. That is exactly the writer call that makes "one writer per extension" true.

**M2, one effective money source.** The four read sites are covered:
- `update_case_budget`'s `limit_usd` (`model_runtime.py:181`).
- `model_runtime.py:351`.
- `budget.py:255`.
- `recovery_config` at `run.py:2499` and the `coordinator.py:162` equality check.

**M3, totals remainder.** I checked `budget.py:72–75`. The remainder is `total − observed`. If the observed sums include the classified events, the remainder is zero. Only the role breakdown then excludes them. The example works: $12 observed, $4 classified, case $8, waste $4, total $12.

**M5, zero-work chain.** A case that makes zero model invocations does not queue a replacement. This stops the chain without a count cap or a price.

**M6, receipt v2.** The design now says V2 is every V1 field plus the new ones. It names `round_limit`, `binding`, `report`, `release_rereviews` and `release_review_attempts` as kept. `binding_sha256` supplements `binding`. For an active extension, the saved limit is the one authorized round number. The check against `run.py:921–929` is sound: `n=9` with `saved_limit=9` resumes, and `n=10` or an unbound `n=9` is rejected.

**Contract compatibility (interfaces §§2–6).** I re-walked the points below. All remain correct.
- D calls `await_lease` for writer and every stress review. It writes the reservation only after the Lease, and passes `lease=lease`. It never calls bare `admit()`.
- `settle` runs once on resume, before any call, in the case ledger. The `settled` flag is in the same checkpoint.
- `settle` is idempotent on `wait_id` and event IDs. It books only the missing usage. The $10 example is arithmetically right.
- A repeated wait works. The pending receipt is reset to `lease_id:null` plus `resumed_from_wait`, and the settled record is archived before re-admission. The L1, null-denial and L2 chain matches interfaces §3.
- All six §5 counters are exempt. B's section 4 backstops are kept, and `money_wait` is marked as B's proposed contract.
- Merge order and the flag state are correct. No owned contract shape changes.

**Cost evidence.**
- 873d7f `builder-1` is $15.0531879, `builder-8` is $0.744762, and e15450 `builder-10` is $4.3304802.
- `ca2f9bdf…` is $32.6137984 over 168 calls, with no invocation label.
- The VM card inventory is 54 cards. The Heilmeier cost answer is honest: it deletes the unsupported $15 and invents no replacement.

**Single-path doc.** The retry, exhaustion, unknown-outcome, batch-record, G10-serialization and approval lines agree with stream D.

## Blocker

### B1. The per-case model lock deadlocks G10 exam exposure (nested owner call)
- **Severity:** Blocker.
- **Scope:** "Serialize model dispatch per case with a case-local lock acquired before `await_lease` and held through wrapper finish… D's caller and wrapper nest it in the same thread… All new-schema factory jobs use this scheduling policy." Also "only one pending admitted invocation can match [the record]" and "A owns account concurrency across cases".
- **Finding:** The lock is a `threading.RLock`. It is reentrant only inside one thread. Code search shows a model call that runs in a different thread while the tester's call holds the lock.
  - G10 exam-exposure attempts call `owner_channel` (`run.py:2007–2014`) and then `model_call(call_context, c.models[role], …)` for the pilot. That tester call runs on a G10 calibrator thread.
  - `owner_channel` starts `owner_server`. It runs `HTTPServer.serve_forever` on its own daemon thread (`exam_responder.py:115–119`).
  - Each question the pilot asks makes `answer()` call `r.model_call(owner, c.models["reviewers"][0], …, "reviewer-owner-…")` (`exam_responder.py:94`). That is a real, paid model call.
  - It runs on the server thread while the tester's call is still in flight. The tester's call holds the case lock "through wrapper finish".
  - So the owner call blocks on the lock until the tester call ends. The tester is the one waiting for the owner's answer.
- **Consequences:**
  - Every owner question stalls until the tester's own timeout, which is `calibrator_minutes` (30). The tester never gets answers. The answerer then reports "owner unavailable", sets `cancel` and `role_cancel`, and `owner_server` re-raises the failure at exit.
  - G10 exam-exposure attempts would therefore fail, or score the pilot with no owner help. That is a gate liveness and correctness failure, not just a slowdown. The design says this policy applies to all new-schema factory jobs.
  - The "single pending admitted invocation" claim is also false here. The tester call and the owner call are two admitted invocations alive at once. A's one `provider_wait.json` and D's `settle` join (one pending reservation matched by lease) have no rule for this.
  - The design says it will use "the lock, not a change to the concurrent_roles flag". `exam_responder.py:78` and `run.py:2012` set `concurrent_roles=True` on exactly these nested contexts. The design never mentions the owner calls.
- **Fix (a design decision, one short paragraph):** Choose one and write it down.
  - **(a)** The owner call is part of the tester's admitted invocation. Hand the held lock to the owner server thread (the lock is owned by the call chain, not the thread). The owner call uses a sub-reservation under the tester's lease, and a provider denial on it cancels the tester through the existing `role_cancel` path. Never exit the process as `provider_wait` from the owner thread.
  - **(b)** Exclude `reviewer-owner-*` calls from the lock. State that exam-exposure G10 can have two live admitted calls. State which `provider_wait` record they use (for example, "owner-call waits cancel the tester and are unmatched"). State how `settle` matches two pending reservations.
  - Either way, add one exam on a saved exam-exposure G10 attempt. It should show that the pilot's owner question is answered with the lock held, and that the reservations settle once.
- **Why this is blocking, not optional:** It does not demand speculative architecture. It is a deadlock that the design's own rule creates in an existing mandatory gate. The zero-decision rule is also not met, because the implementer has to choose between (a) and (b).

## Optional refinements (not blocking)

- **O1. Writer-completion receipt before the automatic checkpoint.**
  - The design says to persist writer completion "before opencode's automatic checkpoint at ~199–208".
  - That checkpoint runs inside `opencode()` after `runtime.call` returns (`run.py:199–208`). A caller cannot write the receipt in between.
  - Name the mechanism, for example an `on_complete` callback parameter beside `lease=`.
  - Without it the system is still safe. A checkpoint with a pending receipt and a finished draft follows "continue unfinished authoring from saved draft". It only risks re-paying one writer call.
- **O2. Resume path for the `final_repair` receipt.**
  - A case that exhausted rounds has a `final_repair: true` receipt (`run.py:1167`).
  - At `run.py:962–970`, a resume without `raised` or `ruled_pending_writer` goes straight to `attack_unresolved("rounds_exhausted")`.
  - Say which branch the "diagnosis plus code eligibility" mapping changes, so the extension's first round can start.
  - The text "bypass ordinary round exhaustion for its active ID" already points at this. It only needs the line named.
- **O3. Existing test list.**
  - About 25 test files and 4 fixtures mention `max_cost` (for example `test_case_budget.py`, `test_model_runtime.py`, `test_resume.py`, `test_recovery_routes.py`, `test_paused_recovery.py`).
  - The design lists 7 files plus `test_run_exam.py`. The search exam covers the rest. It is fine, but say that unlisted `max_cost` fixtures are updated by that search.
- **O4. `run_budgeted` authority parameter.**
  - "Pass `max_cost=None` plus validated job authority" does not name how the authority reaches `run_budgeted`.
  - Name the parameter, or say that the effective `case_budget` plus the job object is enough.
- **O5. Dead cohort-attempt path.**
  - `key_holder.py`'s `additional_attempt` authorization (about 14 uses across `factory/`) becomes dead for new-schema jobs once `counted >= 3` goes.
  - Under "delete before adding", list it as deleted or kept for historical imports.
- **O6. Exponential restart delay.**
  - With `retries < 3` gone, `restart.py:83` still computes `delay = base * 2**retries`.
  - It stays safe because `remaining <= delay + 60` raises first. A one-line cap would make the intent obvious.
- **O7. Heilmeier "Impact".**
  - Impact, cost, risk, timeline (5–8 days) and exams are all present and honest.
  - Impact is two sentences. That is enough.

## Accepted prior choices (not re-opened)

- Removing replacement count limits, with the shared cumulative bound as the only stop.
- Deleting $15 without inventing a replacement.
- The B-owned money channel as an external prerequisite.
- Rows 10, 35 and 39 staying open until the public crash and capped-call bundles exist.
- The `max_total_calls` and `max_role_calls` caps staying in place. The design says "not G10's time/call limits". The default is 5000 (`run.py:2402`), and the observed cards show 390–799 events, so this is not a row-8 failure.
- ENGINEERING §3 staying active until implementation adopts the amendment.

## What passed

- **Zoom-out.** The design reuses `budget.py`, `restore_ledger.py`, `gate_state.py`, `late_recovery.py`, `coordinator.py`, `key_holder.py`, `sealed_audit.py` and `g11_review.py`. It adds only `diagnosis.py`, its prompt, and the extension history. Replacing the old trigger by deletion is consistent with "delete before adding".
- **Extension mechanism.** Stage order, the first-entry predicate, same-version comparison, lazy rebasing, zero repairs inside an extension, and snapshots surviving `invalidate` and `stop_defect` are all sound.
- **Diagnosis routing.** The strict schema, the reviewer-family rule, the checkpoint-hash binding, the `factory_bug` waste record and the operation-ID reclassification are specified.
- **Rows.** All rows stay open until real-artifact tests exist.

**Verdict: NOT PASS.** Fix B1 with one short design paragraph plus one exam. Every other blocker and major from rounds 1–3 is closed. After B1, a round 5 only needs to confirm that paragraph. O1–O7 can be accepted or declined without a further round.


## Elephant resolution

B1 accepted and fixed with reviewer option (b): nested reviewer-owner calls
bypass the tester’s RLock, get their own family-correct lease/reservation and
link to the tester operation in the case ledger. Owner waits cancel/join the
tester through existing owner_server failure handling; the root writes the
single record. New evidence: stream A ef01df3 already aggregates interrupted
per-lease receipts into call_id.receipts after joining. settle expands that
aggregate and linked cancelled reservations, deduplicating each lease/event and
wait ID. No borrowed cross-family lease, owner-thread checkpoint or new A shape.
The saved G10 owner-question exam covers normal answers under lock and denial/
interruption with both leases settling once. No finding rejected.

Incorporated the user’s new binding interfaces §7: await_lease(role,c,deadline=None)
uses the existing monotonic deadline; UTC batch metadata stays on c/environment;
pass lease to opencode/model_call; before_attempt reads c.model_lease for internal
fallback reservations; unknown interrupted usage defers internal retry until
checkpoint/resume settlement; finish and usage receipts book nothing; interrupted
unknown remains conservative until settle. Read the implemented API/code at
ef01df3 and the current interface doc, without changing either.

O1–O6 accepted: on_complete callback before automatic checkpoint; active-extension
final_repair branch at 962–970; search updates remaining fixtures/tests; named
job_authority keyword; additional_attempt historical-only; capped restart backoff.
O7 requires no change. Round 5 verifies the owner exception and §7 integration;
all previous blockers/majors were confirmed closed in this review.
