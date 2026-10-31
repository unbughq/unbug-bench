**Verdict: PASS.** No blocker. Three Major findings should be fixed in the design before implementation starts.

Reviewed: `docs/designs/stream-b-controller-waits.md` (untracked in worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`), against `heilmeier-standard.md`, `implementation-readiness-standard.md` and `zoom-out-standard.md`. I also read `factory/batch_holder.py`, `factory/key_holder.py:427-455`, `factory/batch_money.py`, `factory/batch_service.py:163-204`, `factory/run.py:223-269`, `factory/model_router.py`, `factory/account_handoff.py` and `docs/murphy-register.md`.

Zoom-out: the design fits the problem. It reuses `reserve`, the deterministic `operation_id`, the crash repair in `reserve` and `advance_locked`, and the next-tick dispatch done by `reconcile`. It adds no schema, queue or timer, and it keeps the gates off. I checked the replay claim at lines 39–42. `authorize_locked` (`batch_money.py:271-279`) is idempotent once `row.authority.source_generation` equals the source, so a replay does not advance money a second time. That claim holds.

---

**1. Major: the scheduler can loop on `unbounded_route` waits (risk)**
- **Where:** design lines 29–31 ("reason in model_router.REASONS").
- **Problem:** `REASONS` includes `unbounded_route`. The router itself treats that reason as a setup fault, not a provider condition (`model_router.py:304` rejects it as an observation reason). It also re-arms it automatically: `retry_at('unbounded_route')` at line 368, and `retry_after=now+900` at line 233. A successor started on the same route will hit the same wait again. Each new successor then spends a worker, its setup and infrastructure charges until the batch deadline. Lines 51–53 say the design does not bound infrastructure across successors.
- **Fix:** require `reason in model_router.REASONS - {'unbounded_route'}`. Add a test that an `unbounded_route` projection is refused. Also decide whether `credential_expiring` is retryable on the same account. If it is not, exclude it too, or state why it is safe.

**2. Major: every tick re-verifies the full collection while the wait is not yet due (efficiency, lock contention)**
- **Where:** lines 16–20 and 26–33, together with `key_holder.py:561` (the tick runs about once a second, because the socket timeout is 1s).
- **Problem:** `_source` calls `_entry`, then `service._snapshot`, then `_card`. That chain hashes every file in the generation, including the encrypted archives, and runs `collection.verify`, all while holding the batch lock. As written, the due-time check runs only after this proof, inside `reserve`. A quota wait can last hours. Each waiting candidate would then be re-hashed every second under the lock that `collect`, `reconcile` and operator `reserve` also need.
- **Fix:** add a cheap pre-filter in `schedule_waits`. Read only the stored card's `provider_wait.retry_after` and `terminal_stop`, with no full verification, and skip the candidate if it is not due or not a provider wait. Then call `reserve`, which repeats the full proof and the due check under the lock. The pre-filter only skips and never admits, so this keeps the "no process-local wait map" property. State the order explicitly and add a test: a not-yet-due candidate never calls `_snapshot`.

**3. Major: the reserve predicate's interface is not specified (fails the zero-decision rule)**
- **Where:** line 20 ("internal provider-wait-only predicate") and lines 26–35.
- **Problem:** the implementer has to choose:
  - the `reserve` signature, for example a keyword argument or a separate wrapper;
  - where the check sits relative to the `if identity in ops` early return (`batch_holder.py:186-191`), which skips every source check;
  - where the card comes from;
  - which exceptions count as an individual refusal and which count as a scan failure.
- **Fix:** specify it, for example `reserve(policy, root, home, name, source_generation, *, provider_wait=False)`. With `provider_wait=True`:
  - run the extra checks on the `card` returned by `_source`, after `_source` and before `advance_locked`;
  - make the existing-identity branch refuse, with `request_refused`, so the scheduler never repairs or replays.

  In `schedule_waits`, catch `(money.MoneyWait, OSError, ValueError, KeyError, TypeError, AttributeError)` per candidate and skip it. This matches `reconcile`'s set at `batch_holder.py:380`. Let a scan-level failure raise to `batch_tick`'s existing `'batch scan refused'` handler instead of adding a new label. Also specify where the call goes. `batch_tick` currently runs `reconcile`, `orphaned` and `unpublished` in one loop (`key_holder.py:448-451`), so that loop has to be split, or `schedule_waits` added as its own try block between the scans.

**4. Nit: the field checks are looser than what the writer produces**
- **Where:** lines 30–31.
- **Problem:** `write_provider_wait` writes `wait_id` as a UUID4 and both times through `model_router.utc`, which produces a UTC `Z` value. "Canonical UUID" and "timezone-aware" are looser than that.
- **Fix:** require a version-4 canonical UUID, the same check as `run.py:provider_continuation`. Parse both times with `money.deadline`, which requires UTC offset 0, rather than accepting any time zone.

**5. Nit: `operation_id` is cited with the wrong signature**
- **Where:** line 37.
- **Problem:** the real signature is `operation_id(policy, job, source)`, and the release comes from `policy['batch']['sha256']`.
- **Fix:** correct the text.

**6. Nit: the objective is written in jargon (Heilmeier: Objectives, Impact)**
- **Where:** lines 5–12.
- **Problem:** the objective depends on terms like ACK, outbox, authority and current pointer. Impact is mentioned only at line 50.
- **Fix:** open with two plain sentences. For example: "When a case pauses because a model provider is rate-limited, nothing restarts it today; an operator must. This makes the controller restart it automatically once the provider's retry time passes, using the same reservation path an operator uses."

**7. Nit: related Murphy rows are not named**
- **Where:** lines 54 and 76.
- **Problem:** no rows closing is correct for offline-only tests. But the work moves rows 2, 11 and 47 forward (provider waits without human resubmission), and the design names none of them.
- **Fix:** name them as "advanced, not closed".

**8. Nit: the design file is uncommitted**
- **Where:** `docs/designs/stream-b-controller-waits.md`.
- **Fix:** commit it before saving the review record, so the reviews listed on the merge commit point to a committed design.

The phasing, the test list (lines 61–68) and the cost and timeline (lines 74–82) are adequate for this offline step. I am not asking for any activation work.

## Elephant response

Accepted all findings. Before implementation, committed the updated design at 34e008d: exclude unbounded_route, add the skip-only card filter, specify reserve keyword/check order and exceptions, use UUID4 and UTC parsing, explain credential_expiring reload/admission, correct the operation ID signature, and name rows advanced but not closed. No findings rejected. Existing successors are skipped; partial money-before-reservation recovery remains allowed because no operation exists yet. No activation work is included.

