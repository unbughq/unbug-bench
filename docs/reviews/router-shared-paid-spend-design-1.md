**FAIL.** Two blockers, seven majors and six nits are open. The parent must get a fresh goldfish review of the blocker fixes.

I read the three persona files, `docs/ENGINEERING.md`, both standards, and the design `docs/designs/router-shared-paid-spend.md` (194 lines). I checked the design against `factory/model_router.py`, `factory/model_call_gate.py`, `factory/model_runtime.py`, `factory/token_prices.py`, `factory/diagnosis_dispatch.py`, `factory/launch.sh`, `control/unbug-model-router.service`, `docs/designs/router.md`, `interfaces.md`, `batch-service.md`, the B3 policy and pins, the funding reports and the test fixtures. I made no edits, external calls or test runs.

---

## Blockers

**B1. The budget rule counts factory spending twice, so only about $5.81 of the $11.63 can be used.**
- **Where:** design lines 66–74 (the "admission invariant").
- **Problem:** the rule is: counted settled charges + holds + next hold ≤ min(11.63, fresh available credit). Fresh available credit already has the factory's settled spending taken off, so each settled dollar is subtracted twice.
  - The funding report (`docs/reports/router-item8-funding-20261031.md:17-19`) shows remaining credit of $11.626127395, and no key limit.
  - After factory spend S: available ≈ 11.626 − S, and the rule becomes 2S + next ≤ 11.626. Paid lanes stop at about S = $5.81.
  - There is no command to release holds (line 162), so this is a permanent stop that needs a human. That is a pit stop the user explicitly wants to avoid.
  - The design calls this "can refuse early". It is really half the envelope.
- **Simplest fix:** two separate checks in the same transaction:
  - (a) everything counted (settled + pending + unknown) + next hold ≤ 11,630,000,000 nanodollars. This is the lifetime cap.
  - (b) outstanding holds + next hold ≤ available credit right now. Outstanding means pending, unknown, and settled rows settled within a fixed window before the credit fetch started (pick a value, say 15 minutes, and state it). The window covers provider usage lag.
  - This matches min(11.63, available) as written. Unknown rows are still counted conservatively. If the database is lost, total spending is still capped by the account credit, as long as nobody tops up.
  - If the founder prefers the halved reading, the design must say ~$5.81 effective and get that ruling. It cannot be called "conservative" by itself.

**B2. Fetching the credit balance while holding the router's global write lock can cancel unrelated running work.**
- **Where:** design lines 60–64, against `model_router.py`:
  - `Store.rpc` opens `BEGIN IMMEDIATE` with `timeout=10` (lines 175–177);
  - the client `_rpc` gives up after 5 seconds (line 326);
  - `running()` cancels the CLI after one failed renewal (lines 533–537).
- **Problem:** every RPC goes through the same lock: renew, acquire, finish and start, for every batch, Claude included. Each paid reservation would hold the lock for up to 2 seconds of network time. Three reservations queued in front of a Claude worker's renewal push it past 5 seconds, and that worker gets cancelled.
  - Paid reservations that time out on the client after the server commits leave holds that are counted forever (lines 64 and 100), about $0.23–$0.59 each.
  - "Acceptable at current throughput" (line 62) has no numbers behind it, and the throughput goal is 24 parallel cases.
- **Simplest fix:** fetch the balance before `BEGIN IMMEDIATE`, then check the rule inside the transaction against all holds committed by then.
  - This is safe because the rule subtracts every committed local hold at commit time. Two reservations that read the same balance still see each other's holds. A stale balance only misses outside usage, which is out of scope anyway (lines 72–74), plus settlement lag, which B1's window covers.
  - Also have the server refuse to commit, without writing anything, when its own handling time is already more than about 4 seconds. Then a client that has given up never leaves an orphan hold.
  - Delete the claim on line 61 that "no later reservation can race".

---

## Majors

**M1. Refusals have no response format; the current wire turns them into transport errors.**
- **Where:** lines 90–100 and 121–126, against `Handler.do_POST` (lines 566–583) and `_rpc` (lines 330–334).
- **Problem:** any server-side `ValueError` becomes HTTP 400, and the client turns that into `RouterUnavailable`. So the planned split ("credit for refusal, router_unavailable for transport uncertainty") cannot happen. Duplicate request IDs and changed bindings would look like outages.
- **Fix:** specify the exact HTTP 200 bodies:
  - `{"granted": true}`;
  - `{"granted": false, "reason": "credit" | "duplicate" | "binding"}`.

  Then specify, as the gate's actions:
  - the HTTP status and error type it returns to opencode;
  - whether a refusal sets the exhaustion state;
  - whether it calls `observe(reason='credit')`. That reason never clears on a timer (`model_router.py:189`, `batch-service.md:411-413`), so it blocks the `openrouter-key` pool until a top-up is observed;
  - whether a definite refusal releases the local hold.

**M2. Settling after the downstream socket closes would keep the last request of most invocations at its full hold.**
- **Where:** lines 128–139.
- **Problem:** in `model_call_gate.Handler.do_POST`, the CLI sees EOF only after `do_POST` returns, because the gate sends `Connection: close` and no content length. If the settle RPC happens after the socket closes, the CLI exits first. Then `gate.close` and the lease finish can beat the settle. Every invocation's final request, about $0.23–$0.59, is held for good. Twenty to fifty invocations would use up the envelope.
- **Fix:** say that the settle RPC runs inside `do_POST`'s `finally`, after the local `finish` succeeds and before returning. That orders the CLI's EOF after settlement. Bound it with the RPC timeout.

**M3. A new client breaks every admission on an old server, not just paid ones.**
- **Where:** lines 82–86.
- **Problem:** `acquire` rejects any field outside its exact set (`model_router.py:208`). A new client sending `paid_protocol` therefore fails all acquires on an old server, Claude subscriptions included. Line 85's "existing subscription admissions remain compatible" is only true in one direction.
- **Fix:** state the rollout order (upgrade and restart the router service first, then the clients). Say the new server accepts `paid_protocol` as optional, and add a test for new-client-to-old-server failure.

**M4. The batch-scoped router contract is left contradicting the design.**
- **Where:** lines 25–35 and 154–155.
- **Problem:** the design says all batches share one service and one database. But `batch-service.md:95-107` pins a per-batch router config (database path, capacities, accounts, TLS) by hash. `interfaces.md:65` says the router token is batch-scoped. `Store` holds one set of capacities and accounts. The design doesn't say:
  - whether concurrent batches share one capacities/accounts config and token;
  - who writes `/run/unbug-bench/router.json`;
  - what a manifest's router pin must contain now.
- **Fix:** make the config and token control-VM-wide. Add `batch-service.md` to the documents updated. Replace the `database` field with the derived canonical path (see N1).

**M5. The tests claim real artifacts that don't exist.**
- **Where:** lines 166–177.
- **Problem:** no OpenRouter usage-counter capture is retained. `completion_tokens` appears in no fixture, `router-paid-deepseek.json.gz` is a case card, and the reports confirm no paid call was ever made. No raw `/credits` response is retained either; the reports kept only dollar amounts.
- **Fix:** name the real artifacts that do exist:
  - `router-item8-minimax-endpoints` and `router-cheap-price-records`, for tariffs;
  - the dollar figures in the funding reports.

  Label the settlement and credit-parsing tests synthetic, built on the documented OpenRouter schema. Do not let them close or imply any Murphy row.

**M6. Exam traffic uses the same OpenRouter key and isn't named.**
- **Where:** lines 72–74 and 141–145.
- **Problem:** `bin/exam-launch:110,115`, `bin/exam-round:224`, `bin/run-exam:224` and `harbor/run-audited.py:167` push and use `openrouter-key`. All of that spending lowers the same account credit outside the ledger.
- **Fix:** list exam/harbor explicitly as outside spenders on the shared key. Their spending reduces available credit through check (b) and is not counted in the $11.63 lifetime. A reader shouldn't infer that "every OpenRouter call" is covered.

**M7. The design doesn't meet the Heilmeier standard and is hard to read.**
- **Where:** the whole document.
- **Problem:** it has no plain-language objective, impact, risks/payoffs, cost, timeline or mid-term/final exams. It is dense shorthand ("E's receipt freeze", "B3 must drain").
- **What's missing:** a one-paragraph plain summary, plus the numbers:
  - a single paid request holds $0.23, $0.57 or $0.59 depending on route (`token_prices.py`), or $0.69–$1.71 per invocation;
  - so about 20–50 cancelled requests use up the envelope;
  - and, under B1 as written, the effective budget.

---

## Nits

- **N1 (lines 25–28).** Deleting is better than guarding. Drop the `database` key from `router.json`, refuse to start if it is present, and derive the path the same way as `key_holder.CONTROL_HOME` (`key_holder.py:30`, with `.resolve()`). That removes the rule about linked paths.
- **N2 (lines 90–92).** Key the paid-reservation requirement on `route in GATED_OPENROUTER`, the same check the gate uses (`model_call_gate.py:519`), rather than on billing/account. Then the gate cannot forward an OpenRouter request that has no reservation.
- **N3 (lines 102–105).** When the reported cost is above the frozen estimate, the result isn't specified. Suggest: mark the row unknown and charge max(hold, reported cost), so a provider price rise can't push spending past the lifetime cap unseen.
- **N4 (line 32).** `PRAGMA synchronous=FULL` applies per connection. Say it is set on every `rpc` connection.
- **N5 (lines 181–182).** "E's TLS tests" should name the file.
- **N6 (lines 49–50).** "Freshly available" overstates it, because provider balances lag. With B1 and B2 fixed, the design no longer depends on freshness, so word it that way.

---

## What checked out

- **Credential reach.** Every lease that is granted today goes through `enforce`, and `enforce` replaces the CLI's environment. The Claude key set and the OpenRouter environment both leave out `OPENROUTER_API_KEY`.
- **Diagnosis.** It reaches the gate through `r.opencode` (`diagnosis_dispatch.py:415`). No other in-factory caller talks to OpenRouter directly.
- **Subscription and free routes.** `opencode-go` and `:free` routes never get a maximum, so they never get a paid record.
- **Cancelled holds.** `Allowance.close` keeps active holds and refuses late refunds, which fits "count unknown and cancelled once" through central close-time marking.
- **Credit endpoint.** Reading `/api/v1/credits` with the inference key is backed by the funding reports.
- **B3 pins.** They are already `launch_ready: false`. Leaving them untouched and requiring fresh pins fails closed, which is acceptable.


## Elephant disposition

Both blockers and all majors accepted. Revised design separates lifetime and observed-credit checks, moves provider I/O outside transactions and specifies wire, ordering, rollout, artifacts and ownership. Nits addressed or qualified in the design disposition. No code changed. Fresh review required.
