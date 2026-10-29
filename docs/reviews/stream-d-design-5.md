# Goldfish review, round 5: Stream D design (`docs/designs/stream-d.md`)

**Mode:** REVIEW, read-only. I made no writes, launches, decryption, credential reads or paid calls.
**Personas:** zoom_out, design_critic, implementation_readiness.
**Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.
**Focus:** the round-4 blocker B1 (nested G10 owner call), the new interfaces §7 integration, and nearby text for contradictions. Accepted earlier choices and O1–O6 are not reopened.

**Scope read:**
- `docs/reviews/stream-d-design-4.md` verbatim, including the elephant resolution.
- `stream-d.md` lines 1–232 and the tail from the test list onward.
- `/Users/bugsincode/Developer/unbug-bench/docs/designs/interfaces.md`, §§1–7 in full.
- Code via `git show`, with no checkout:
  - `ef01df3:factory/{model_router,model_runtime,exam_responder}.py`.
  - `ef01df3:factory/run.py`, around the `opencode`, `write_provider_wait`, `model_call`, `calibrate`, G10 pool and stop-handler sections (about 196–285, 2022–2110, 2178–2215 and 2625–2650).
  - `budget.py`: `invocation_role`, `run_budgeted` cancel handling.
- In the current tree: `gate_pipeline.py` (G10 overlap) and `fairness.py`.
- The later A commit `447795b`, only to see where it differs from the pinned `ef01df3`.

## Verdict: PASS

B1 is closed, and I found no blocking gap in the §7 integration. The deadlock is gone, and I walked the cancel and settle path against the code without finding a hole. Several of the notes below (M1–M5) are real gaps that a careful implementer would otherwise have to guess at. They are one-to-three-sentence design clarifications. None needs another review round, and the elephant can accept or decline them.

## B1 verification (nested owner call)

**The deadlock is removed.** In `ef01df3`, the owner call is `r.model_call(owner, c.models["reviewers"][0], …, "reviewer-owner-…")`. It runs on the `owner_server` HTTP thread. The tester call holds the `RLock` on the G10 calibrator thread. With the bypass, the owner call never waits on that lock, so the tester's wait for the owner's answer can complete.

**Facts the exception rests on, confirmed in code:**

- **Family and requested model are right.**
  - `invocation_role("reviewer-owner-…")` returns `reviewer`.
  - The requested model is `c.models["reviewers"][0]`.
  - `runtime.call` pins family against `card.roles.reviewer`.
  - So the owner gets a reviewer-family lease of its own.
- **Owner failure cancels the tester through the existing path.**
  - `answer()` catches `BaseException`, appends to `failure`, sets `cancel`, and sets `c.role_cancel`.
  - `c` there is the tester's `call_context`.
  - The tester's `run_budgeted` then raises `BudgetError('cancelled')`, at `budget.py:272` or on mid-run kill.
  - That label is not in `runtime.call`'s provider-failure mapping.
  - So the tester is not misclassified as an outage, and the router pool is not falsely marked bad.
  - `finish(…, 'interrupted', receipt)` and the per-lease receipt are written in the `finally` block.
- **Ordering is right.**
  - The G10 executor joins its workers (`run.py` ~2202, `except BaseException: role_cancel.set(); raise`) before the stop handler runs.
  - The stop handler's condition is `str(error)=='cancelled' and c.card.get('router_waits')` (`run.py` ~2639).
  - `write_provider_wait` therefore runs after the tester's receipt exists. The design's "after joining" is correct.
- **At most one live owner call per tester.**
  - `owner_server` uses plain `HTTPServer`, not a threading server, so questions are serial.
  - This is stronger evidence than the design's "restricted tool context" (see N2).
  - The easy tester is blocked on the lock while the strong tester runs, so at most one tester plus one owner is live.
- **No checkpoint from the HTTP thread.**
  - `owner.calibrator_slot_offset = 0` makes `opencode()` skip `checkpoint_progress`.
  - "Never seal or exit from the HTTP thread" is already true. Keep the guard.
- **Single record.** `write_provider_wait` writes once, under `PROVIDER_WAIT_LOCK`, from the root. The design claims no A change, and that holds.

**Keep and settle, as designed.** Owner denial with a null lease books $0. The cancelled tester's reservation survives and settles conservatively. This is the right asymmetry.

## §7 integration verification

| §7 item | Design text | Status |
|---|---|---|
| `await_lease(role, case, deadline=None)`, monotonic deadline | D passes the existing monotonic operation deadline and never a UTC epoch. | Matches `await_lease`: `stop_at = min(batch_deadline, now + (deadline − monotonic()))`. |
| Batch deadline, batch ID and job ID from `case` or `FACTORY_*` | Same. | Matches `metadata()`. Owner and tester contexts are copies of `c`, so the attributes are inherited. |
| Requested route is `card['roles'][role]['model']` | Same. | Matches. `runtime.call` sets `router_model`. |
| D passes `lease=` to `opencode` and `model_call`; `case.model_lease` exposes the lease | Same. | Matches. `runtime.call` sets `c.model_lease = context.model_lease = lease` before `before_attempt()`. |
| `finish` and usage receipts book nothing | Same. | Matches. Only `settle` books. |
| Interrupted usage stays conservative until `settle` | Same. | Matches (see M5 on a cost caveat). |
| Internal fallback leases reserved in `before_attempt` | Reserve and map each newly returned lease from `c.model_lease`, with no extra logical round. | Compatible. The wrapper reuses a caller-written reservation, so reserving twice is a no-op. |
| Defer internal attempts after unknown final usage | Reuse `router_deferred` and preserve the Wait and receipt. | Direction is right. See M4 for the flag-off hang. |

## Non-blocking design gaps (M1–M5)

### M1. The bypass trigger and `parent_operation_id` are not defined (Major, non-blocking)
- **Scope:** "G10 nested owner exception".
- **Finding:** Two details are left to the implementer.
  - **Bypass.** "Trusted `reviewer-owner-*` calls … bypass the lock" does not say how the wrapper knows. Matching on a name prefix is spoofable and fragile.
  - **`parent_operation_id`.**
    - `owner_channel` creates the owner context before the tester's wrapper admits anything. The tester's invocation ID and lease do not exist yet.
    - A later `c.model_lease` assignment on the tester's `call_context` is not visible to the already-copied owner context.
    - The G10 tester has no logical `operation_id`. That concept belongs to writer and stress units.
    - So the link has no defined value.
- **Guidance:**
  - `owner_server` sets two attributes on its copied context: a lock-bypass marker and a parent key. The wrapper bypasses the lock only if the marker is present.
  - The simplest parent key is the tester's deterministic call name (`f"{role}-{name}-{i}"`). The tester's reservation already stores its call name, so `calibrate` can pass that name to `owner_channel`.
  - Say that `settle` can also find unsettled interrupted reservations by lease receipt without the link. The link then only narrows the search.

### M2. Owner route data does not reach the root card (Major, non-blocking)
- **Scope:** "Child contexts share the root `router_waits` collector"; the settle line "resolve interrupted effective route from its per-lease receipt/card.route_receipts".
- **Finding:**
  - `owner.card = {**c.card, …}` is a shallow copy. `c.card.setdefault(...)` on the copy creates a private list whenever the root has not yet created that key.
  - The design shares only `router_waits`. `route_receipts` is appended in the same way and is not mentioned.
  - The `ef01df3` per-lease usage receipt has no route or account field. Its keys are `lease_id`, `invocation`, `booked_event_ids`, `usage_delta`, `events`, `unidentified_events`, `final_usage_known` and `outcome`.
  - So an owner lease's route cannot be recovered at settle time. The design says D never prices from the record's route.
- **Guidance:** The simplest fix removes the dependency. D's reservation helper already receives the `Lease`, so store `route`, `account`, `billing` and `pool` in the reservation at creation. Say "settle prices from the reservation, with `route_receipts` as evidence only". If the elephant prefers sharing, name `route_receipts` and `cleanup_errors` alongside `router_waits`.

### M3. The "aggregate" wording and the exam do not match what A writes (Major, non-blocking)
- **Scope:** "uses A's existing multiple-receipt aggregation"; the exam line "write one A aggregate".
- **Finding:**
  - `write_provider_wait` writes `receipts:[…]` only when `router_waits` holds two or more distinct `call_id` values.
  - A cancelled tester raises `BudgetError('cancelled')`, not `ProviderWait`, so it never enters `router_waits`.
  - In the owner-denial and owner-interrupted cases, `router_waits` therefore holds only the owner's wait. The record's `call_id` is that single leaf (or null), with no aggregate.
  - An aggregate appears only if the owner itself had two or more interrupted leases, such as sequential owner fallbacks.
  - The exam as written would assert something that does not occur.
- **Guidance:**
  - The settle logic is still right, because the tester is joined through the case-ledger links.
  - Reword the exam to "A writes one record (leaf or aggregate). Settle books the tester through its linked reservation."
  - Add that the expected terminal stop is `provider_wait`. The root sees `cancelled`, because `owner_server` re-raises `failure[0]` only on clean exit. `write_provider_wait` therefore fires only because `router_waits` is non-empty at the root, so collector sharing is load-bearing. If sharing fails, the stop silently becomes an ordinary `cancelled` stop with paid work lost.

### M4. Unknown-usage deferral with the flag off (Major, non-blocking)
- **Scope:** "ModelRuntime.call defers further internal attempts (existing router_deferred path)".
- **Finding:**
  - With `UNBUG_PROVIDER_WAIT=0`, `await_lease` never raises `ProviderWait`. Its loop sleeps on cancellation forever.
  - `final_usage_known` is false for every interrupted outcome. If deferral is set on that, a worker that hits a provider failure with the flag off would wait forever, because nothing resumes or settles.
  - With the flag on, the deferral also polls for the 60-second `WAIT_SECONDS` before the ProviderWait. That is harmless.
  - D merges before B turns the flag on, and D's own tests run in that window.
- **Guidance:** Say that unknown-usage deferral applies only when the flag is on. With the flag off, keep A's current behavior and leave the conservative reservation in place for ordinary crash reconciliation.

### M5. Hold-and-wait on pool capacity (Major, non-blocking)
- **Scope:** "get independent reviewer-family leases … neither borrows the other's route/account".
- **Finding:**
  - Pool capacity defaults to 1 (`self.capacities.get(route['pool'], 1)`). Free routes share the pool `opencode-free`. A busy pool returns `Wait('rate', retry_after=now+15)`. A newer request also queues behind older overlapping requests.
  - Here the tester holds its lease while the owner waits for a reviewer-family slot. After 60 seconds `await_lease` raises ProviderWait (`rate`), which cancels the tester.
  - It is fail-closed: nothing is mis-scored, and the tester's spend settles. It is also wasteful, and B's relaunch cap of 10 per reason (`provider_wait_unrecoverable`, "means a bug") could trip during a busy batch even though no provider is faulty.
  - B's `capacity(route)` check covers only the record's route. That route is the owner's, not the tester's.
- **Guidance:**
  - State this as an accepted risk, and require the batch deadline qualification to record owner-admission waits.
  - Ask B to check both the tester route and the reviewer route before relaunching a G10 exam attempt.
  - Either option is acceptable. The design has no better local fix, because A's wait threshold cannot change.

### M6. Cost caveat on interrupted calls (Optional)
- A's receipt marks every interrupted call `final_usage_known:false`. Under the settle rule, even a CLI that fails in seconds with zero billed events gets the full reserved maximum gap booked.
- This is the binding contract (interfaces §3), conservative, and not an error. It does mean several short waits can burn real batch headroom.
- If it matters in practice, a tighter gap bound is a later refinement. It should not change this design.

## Nearby nits (optional)

- **N1. Pin.**
  - The design pins §7 at `ef01df3` but says "A checks installed credentials/Codex expiry **before returning a Lease**".
  - In `ef01df3` that check runs after the lease, inside `runtime.call`, and the denied path leaves `lease_id` null.
  - Credential-before-lease and the rewritten `previous_waits` are in `447795b` and `ff5ed1a`. The interfaces text I read has no credential statement.
  - Name the A commit the design relies on. The merge order rebases onto A before implementation, so this is cosmetic.
- **N2. Owner concurrency evidence.** Cite the non-threading `HTTPServer` for the "no third nested owner" claim, instead of "restricted tool context".
- **N3. Denied-after-admission reservation.** Say that a reservation whose lease finishes `denied` with no CLI started (family mismatch, validation error) is released at $0 at once. Otherwise it stays "unmatched admitted" and is conservatively overcharged. This is rare after `447795b`.
- **N4. "One admitted invocation".** "Thus ordinary calls have one admitted invocation" means one live at a time. Sequential fallbacks produce several leases over a call's life, as the same document says elsewhere.
- **N5. Exam wording.** "Neither attempt is scored invalidly" is ambiguous. Use "neither attempt is scored, and neither is writer feedback".
- **N6. Flag-off test gap.** The test list has no case for the flag-off deferral path in M4.

## Other checks

- **Lock and foreground gates.** G10 runs in a pool thread overlapping foreground gates (`gate_pipeline.py`). The foreground G16 reviewer call serializes behind the G10 tester under the lock. The G10 tester never waits on the foreground, so there is no cycle. The wall-time cost is already flagged in the design.
- **Concurrent cancel and the second tester.** After cancel, the easy tester acquires the lock and `await_lease` raises `cancelled` before admission. No reservation is left behind.
- **Resume of the G10 unit.** `series.remaining()` re-runs the uncommitted try. "Resume its unfinished unit normally" is correct, and the interrupted try is not recorded as a result.
- **Reservation timing.** The caller-written reservation plus the wrapper reuse rule makes `before_attempt` reservation idempotent per lease. State that explicitly if the elephant revises the text (see N3).
- **Nearby contradictions.** None beyond N4 and N5. No stale "single pending admitted invocation" claim remains in the document.

## What passed

- **Zoom-out.**
  - The exception reuses `role_cancel`, `owner_server`'s failure path, A's existing aggregation and the case ledger.
  - It adds no new abstraction.
  - Option (b) was the correct choice over handing the lock to the owner thread. It avoids sub-reservations under a tester lease.
- **Implementation readiness.** The exception names the files (`exam_responder.py` and the shared wrapper) and the required behavior. M1–M3 are the only places the implementer would have to decide something.
- **Contract compatibility.** The paragraph keeps A's record and receipt shapes unchanged and keeps B's backstops intact. All six §5 counters stay exempt. The merge order and flag state are unchanged.
- **Heilmeier.** Unchanged and honest. Cost deletes the unsupported $15 and invents no replacement.

**Verdict: PASS.** B1 and the §7 integration have no blocking gaps. M1–M5 are recommended clarifications, N1–N6 and M6 are optional, and none requires a further review round.


## Elephant resolution

PASS recorded. No blocking findings or rejected findings remain. All optional
M1–M5, N1–N6 and M6 accepted without another review round, as the reviewer allows.
M1: program-created owner bypass marker, deterministic tester call_name parent
link set before admission, and authenticated unsettled-receipt fallback search.
M2: store all returned Lease pricing/route/account/pool metadata in D reservation;
share root operational lists before owner context copy. M3: root provider_wait
record is null/leaf/aggregate as applicable, linked tester is settled separately;
exam expects provider_wait and no scoring/feedback. M4: defer unknown internal
retry only with flag on; flag-off exam added. M5/M6: record owner pool waits and
conservative charges as accepted risk; B should schedule both required pools.
Nits: pin ef01df3+447795b and ff5ed1a; cite HTTPServer; release denied/uninvoked
reservation at $0; one live ordinary invocation; unambiguous unscored exam wording;
flag-off coverage and idempotent before_attempt reservation.

The reviewer read the new credential-before-Lease wording and section 7. Latest
user clarifications are explicit: provider_wait lease_id/call_id identify the
interrupted attempt; route/account belong to B’s next candidate and never price
past work; merged call_id booked_event_ids may span sequential fallback leases.
The existing merged-receipt exam checks $3+$2 booked and $3+$2 gaps = $10 total,
second settle $0, independent of next-account fields. These clarify the accepted
settlement/aggregation design, without any owned interface shape change.
