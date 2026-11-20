# Diff review 2: router retry on 83c659f8 (goldfish)

**PASS**

**How I checked:** I copied the worktree into a scratch folder, which is now deleted. The three changed test files pass: paid_spend 58 tests, model_router 51, router_capacity 10. I then ran four mutations. Changing `in (1, 2)` to `== 1` fails 3 capacity tests, so that change is protected. Three of the review-1 fixes have no test that catches their removal (finding 4). I found nothing unsafe for money, nothing that breaks sqlite, and no blocking version mix.

**What is sound since review 1**
- **Live recheck inside the open `with` block** (`factory/model_router.py:514-518`):
  - Under sqlite: after the explicit `BEGIN IMMEDIATE`, `db.rollback()` releases the write lock. The recursive `rpc` then opens its own connection and its own `BEGIN IMMEDIATE`. The outer connection stays open but holds no lock. When the outer `with db:` exits, its commit does nothing.
  - What the rollback undoes: the outer expiry sweep, the `paid_account.credit` write and the `health` dict. The early return skips `save_health`, and the inner call redoes all of it with the live balance.
  - Health and short bookkeeping: only a live short blocks the pool. The `paid_account.credit` write gets the live value.
  - The 4 s rule: `started` is passed through, so the inner call still cannot grant after 4 s. A late inner call says `binding`, and the gate retries. That is no worse than base.
  - Recursion depth is 1, because `live=True` sets `cached = None`.
- **Money:** `credit, fetched_at = cached` counts every hold granted since the read began, whether pending, unknown after it, or settled after it. Reconcile only rewrites rows older than `observed_at - 900`. Spend stays within credit plus one hold, and that does not depend on how old the cache is.
- **capacity_protocol 2, every mix:**

  | Router | Worker | Result |
  |---|---|---|
  | New | Old (protocol 1) | Gets `capacity`/`outage` as before, and benefits from the cache |
  | New | New | `capacity` and `no_route`, correct end to end |
  | Old | New | Paid retries work (the old router already dedups and answers `duplicate`); `no_route` stays `outage`; but a full seat comes back as `rate` (finding 5) |

- **Gate loop:** `duplicate` always means an earlier try was granted, because a row is only inserted on a grant and the duplicate check runs before the 4 s check. Any try still waiting for the lock started earlier, so it can only end as `binding`. That makes `definite` on the last `binding` sound.
- **`RouterRejected` for binding changed:** it subclasses `RouterUnavailable`, so every caller that catches the parent still works. `classify.py:134` maps it to the same label.
- **Refresh at the top of `reconcile_forever`** (`:1189`): it is off the serving thread. A hung read stalls only that thread, the same as `account_usage` did before.

**Findings**

1. **NIT: under load the cache can go stale, and paid requests go back to a live read every time.**
   - The background refresh period is 60 s plus reconcile's own run time. Reconcile makes up to 25 `generation_cost` calls in a row, each with a 5 s timeout (`:799`). The docstring says rows whose report never fits stay in that set for good.
   - On a pegged VM a pass can take more than 60 s. The cache then passes `CREDIT_FRESH_SECONDS` (`:408`), and every paid request goes back to the 11-19 hot-path read. The gate's 30 s retry now covers most of those failures.
   - A live read made in `rpc` (or in `lift_credit`) is never stored back. So after a top-up, every request pays cached-short, then a live read, then a second transaction, until the next refresh.
   - Fix (one line, money-neutral because `fetched_at` is when that read began): in the live branch of `rpc`, after a successful read, set `self.balance = (credit, fetched_at)`. That limits hot-path reads to one per 120 s whatever reconcile does.

2. **NIT: I don't accept review 1's reason for keeping finding 4 ("unreadable balance stays `credit`"). It is not blocking, though.**
   - When the cache is stale and the live read fails, `:721` returns `credit` with no pool block. The call ends as `router:credit`, `credit_ready` sees no block, and the case wakes at once and relaunches.
   - That is an infra relaunch wearing a credit label, from one provider round trip. It is the pattern the task removes, and the root-cause report suspected it in some 11-19 credit stops.
   - It needs finding 1's stale cache first, so it is rare now.
   - Fix: answer `binding` when `credit is None`. The gate retries for 30 s, and a balance that stays unreadable ends as `router_unavailable`. No grant is made, so it is money-safe.

3. **NIT: when the gate loop stops on `is_set()` or `closed`, it overwrites a failure that is already recorded** (`model_call_gate.py:639-645`).
   - Request A gets a definite `credit`, or the call hits its cap (`model_call_cap`).
   - Request B, which is retrying, then breaks with `reason='router_unavailable'` and overwrites `paid_failure`. `enforce`'s `finally` checks `paid_failure` first, so the stop becomes `infra:router_unavailable`.
   - This existed before with the single try, but the new loop now exits on exactly these flags.
   - Fix: `if not (gate.state.is_set() or gate.state.closed): gate.state.paid_failure = reason`, while keeping the `finish` and the 503.

4. **NIT: three review-1 fixes have no test that catches their removal.**
   - I removed the `or gate.state.closed` check, changed `RouterRejected('lease binding changed')` back to `RouterUnavailable`, and removed the top-of-loop `refresh_credit()`. All of `test_router_paid_spend`, `test_model_router` and `test_router_delivery` still pass.
   - Add one small test each:
     - Close the gate while the reserve keeps losing its reply, and assert it stops in well under 30 s with no pending row.
     - Return a changed `route` from `renew`, and assert the call is cancelled after one renewal with no retries.
     - Have `reconcile` assert that `store.balance` is set on the first pass with a long `interval`.

5. **NIT: the router must deploy before the worker plumbing, and nothing says so.**
   - With an old router and a new worker (`capacity_protocol=2`), the old router answers `capacity_protocol == 1 → capacity else rate`. Every full-seat wait becomes a `router:rate` stop, which is the 8 November regression.
   - The old router validates the key set, so code cannot fix this. The deploy order is the guard.
   - Fix: write "router restart (drained) before the worker plumbing release" in the PR body and the release notes. Also restart the controller, so the old `stop_registry` stops reporting `router:no_route` as UNKNOWN. That second part is cosmetic.

The review-1 7b "not changed" reason holds: the hold is kept, which is money-safe, and reconcile's usage bound releases it later.

## Elephant response (2026-11-20)

PASS. Nits handled as follows.

Fixed:
3. A retry cut short because the call already stopped keeps the stop already recorded: `paid_failure` is set only when the call has not stopped (`is_set()`/`closed`), and a `credit` refusal is always recorded.
4. Added the three tests; each was checked to fail on a scratch copy with its fix removed:
   - `test_router_paid_spend.PaidWireTests.test_a_reserve_retry_stops_when_its_call_ends` (no `closed` check);
   - `test_model_router.RouterTests.test_a_renewal_answer_with_a_changed_binding_ends_the_call_at_once` (`RouterUnavailable` again);
   - `test_router_paid_spend.PaidTests.test_the_background_pass_reads_the_balance_as_it_starts` (no start refresh, `interval=60`).
5. The deploy order (drained router restart before the worker plumbing release) and the controller restart go in the PR body.

Not changed:
1. Storing a live read back into the cache would make every live read in `rpc` a cache write. The router's own tests (and any process without the background pass, such as `--reconcile-once`) rely on each paid request reading live when no refresh ran, and many change the balance between requests. The stale-cache case is the old behaviour plus the gate's 30 s retry, which the reviewer notes covers most of it. The post-top-up case costs one extra live read per short request until the next refresh (at most 60 s), and only while the cached balance is short.
2. Kept, with the reason corrected: a `credit` refusal with no pool block is not an immediate relaunch. `classify_wait` gives it the 900 s provider-limit backoff, and the engine keeps it on its worker for that sleep (the `credit_park` branch parks only when the pool is blocked; ARCHITECTURE: "a refusal with no block ... keeps the short sleep on its worker"). Answering `binding` would turn it into `infra:router_unavailable` after 30 s, an operational wait that rechecks at 2 minutes. That is a different labelling and parking choice, not a fix to this change; it was the base behaviour and needs a stale cache plus a failed live read to happen.
