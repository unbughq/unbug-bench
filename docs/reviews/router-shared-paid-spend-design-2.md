**PASS: no blockers remain. Two majors and seven nits are open.** Both majors are design gaps that cost little to fix. Neither lets money leak. Fix them in the design before implementation starts.

I read the three persona files, `docs/ENGINEERING.md`, both standards, the design (280 lines) and review 1. I checked the design's claims against `factory/model_router.py`, `factory/model_call_gate.py`, `factory/model_runtime.py`, `factory/token_prices.py`, `factory/diagnosis_dispatch.py:415`, `factory/launch_manifest.py`, `control/unbug-model-router.service`, `control/unbug-key-holder.service`, `docs/designs/router.md`, `docs/designs/batch-service.md`, `docs/designs/interfaces.md` and the B3 practice JSON files. The worktree is at HEAD 6afceac, and only the design and review-1 files are untracked. I made no edits, external calls, model calls or test runs.

---

## Prior blockers (checked against the code myself, not taken from the disposition)

**B1 (double debit): resolved.**
- **Check (a)** (lines 94–97) compares lifetime counted spend against a fixed ceiling. The ceiling is min($11.63, the credit observed at the first accepted reservation), stored once and never raised. It does not depend on the live balance, so settled spending is only subtracted once. The full envelope is usable.
- **Check (b)** (lines 98–103) only subtracts pending, unknown, and settlements from the last 900 seconds from the newly observed credit. Settlements older than that are left to the provider's own balance.
- **Boundary case:** rows that settle while the credit fetch is running have timestamps after the fetch started. They fall inside the window, which line 100 states.
- **Lag:** the design claims no provider-lag guarantee (lines 101–102). Factory spending alone cannot overdraw the account, because (a) caps it at or below the credit at the first reservation, unless someone tops up. Only spending outside the factory (exam/harbor) during a lag window could overdraw. The design names that risk (lines 110–115).

**B2 (network call under the global lock): resolved.**
- Every RPC runs inside one `BEGIN IMMEDIATE` in `Store.rpc` (`model_router.py:173-175`). The server is a `ThreadingHTTPServer` (line 549).
- The design (lines 85–91) fetches credit before opening the transaction, with a 2-second timeout. It then checks all committed holds inside the transaction, so two reservations that read the same balance still see each other's holds.
- Renewals and finishes on other threads no longer wait behind network reads. That removes the path where `running()` cancels a worker after one failed renewal (`model_router.py:533-537`).
- Refusing at 4 seconds against the client's 5-second timeout (`model_router.py:326`) shrinks the orphan-hold window but cannot close it. Line 88 says this honestly, and the false "no later reservation can race" claim is gone.

## Prior majors (re-checked)

- **M1 refusal wire:** resolved. Lines 143–147 specify HTTP 200 `granted` true/false with a reason. Today every server `ValueError` becomes a 400, which the client turns into `RouterUnavailable` (`model_router.py:330-334`, `578-583`). The design keeps 400 only for malformed envelopes. See N1 for one gap.
- **M2 settle before the CLI sees end of stream:** resolved. The gate sends `Connection: close` and strips Content-Length (`model_call_gate.py:46`, `527`). Its writer is unbuffered, and the socket closes only after `do_POST` returns. Settling in the `finally` after `state.finish` therefore happens before the CLI sees end of stream. `Allowance.finish` needs to report whether it removed the active entry (lines 195–197); that is a small, clear change.
- **M3 rollout order:** resolved (lines 128–132). The old server's exact-field check at `model_router.py:208` makes "new client against old server fails everything" true, and the design says so.
- **M4 global config:** resolved in the design (lines 56–64). Applying it in `batch-service.md:95-107` is a listed task (line 224).
- **M5 artifacts:** resolved. Settlement and credit-parser inputs are labelled synthetic (lines 238–242). B3's `launch_ready:false` is confirmed in `release-pins.json:24` and `practice-bounds.json:21`. `factory/model_router.py` and `factory/model_call_gate.py` are in `launch_manifest` (lines 44–58, plus `WORKER_GLOBS` at line 98), so new code changes the release digests and old pins fail closed, as line 228 says.
- **M6 exam/harbor:** resolved (lines 110–113).
- **M7 Heilmeier:** mostly resolved. Objective, impact, cost, timeline, exams and risks are now present (lines 18–37). Still dense, but acceptable.

**Requirements the parent listed:** all reflected in the design.
- one global paid cap across batches, processes and restarts, in the existing router ledger;
- no subscription debits (GATED_OPENROUTER only, lines 133–134 and 230);
- unknown credit is refused (lines 80, 104);
- legacy clients fail closed (lines 124–127);
- settlement happens before the CLI sees end of stream;
- a deferred wait with no persistent credit-health block (lines 184–189);
- B3 pins stay compatible.

---

## Majors

**M-A. A credit refusal causes repeated CLI restarts, because provider wait is off by default.**
- **Where:** lines 184–190 (deferral path), against `model_router.py:434-472` and `model_runtime.py:509-521`.
- **Problem:**
  - The design says to set `router_deferred` and "return to the existing provider-wait resume path… no repeated CLI start inside the same call".
  - But `await_lease` only honours `deferred` when `UNBUG_PROVIDER_WAIT=1` (`result = … wait if enabled and deferred else _admit(...)`, line 455).
  - That flag is off in production: nothing in `factory/`, `bin/` or `control/` sets it, and `batch-service.md:38` says it "remains off until A and D merge and qualification passes".
  - With the flag off, the loop goes `_admit` → a new paid lease → a new CLI start → a fresh `/credits` GET → refusal → repeat, until the call's timeout (default 2400 s). The design also skips `observe(reason=credit)` (line 184), so no health block stops the loop.
  - The CLI's own SDK retries on the 503 add more reservations and credits GETs per start.
  - No money leaks. But this churns CPU, may hit the credits endpoint's rate limits, and is exactly the "repeated CLI start" the design says cannot happen.
- **Fix:** state the behaviour when the flag is off. For example: for `shared_paid` failures, raise `ProviderWait` (or a fixed `BudgetError('shared_paid_spend_wait')`) straight out of the ModelRuntime loop regardless of the flag. Add a test with `UNBUG_PROVIDER_WAIT=0` that asserts exactly one CLI start after a credit refusal.

**M-B. The router service gains an OpenRouter inference credential. That is a new security property, not reuse of an existing one.**
- **Where:** lines 74–77 ("existing factory inference credential supplied in RAM via OPENROUTER_API_KEY in router.env").
- **Problem:**
  - Today `router.env` holds only the router token, certificate and key (`router.md:48-53`). The module docstring says "No model or credential transport lives here" (`model_router.py:1-4`).
  - The router listens on `0.0.0.0:8765` (`model_router.py:593`). Putting a credential that can spend money into that process is a new placement. The credential already exists on the control VM, in `secrets.age`, decrypted by the key holder.
  - `ENGINEERING.md` §1 says the founder approves designs that change a security property.
  - The design also leaves open who writes the key into `router.env` and how a key rotation reaches it ("deliver router env outside this offline task", line 229).
- **Fix:** name the change honestly: "the router process newly holds the openrouter-key in RAM, for the read-only `/credits` call only". Record that founder acknowledgement is needed, or obtain it. Name B3 as the owner who writes it, with rotation meaning drain plus restart, like the token. The offline increment still fails closed with no reader (line 82), so implementation does not have to wait.

---

## Nits

- **N1 (lines 136–147):** Say which reason, or which HTTP status, covers these cases: lease not active, lease not started, lease closed, route not in GATED_OPENROUTER, or protocol mismatch on `paid_reserve`. "binding" (200) and 400 lead the gate to different local-hold behaviour, and the zero-decision rule requires the choice to be made in the design.
- **N2 (lines 98, 108):** In check (b), an unknown row whose real cost the provider has already billed counts twice for as long as it exists: once as a full hold and once in the lower balance. That was the user's choice and it is conservative. State the effective envelope: about $11.63 minus the real billed cost of unknown rows, in the worst case.
- **N3 (lines 47–53):** The path comes from `UNBUG_CONTROL_HOME`, which `router.env` (an EnvironmentFile) can set. Changing it silently opens a fresh database: the lifetime counter resets to min($11.63, current credit), and unknown holds are lost. That contradicts "no … configuration can delete/regrant paid authority". Either refuse `UNBUG_CONTROL_HOME` in the router's environment, or soften the claim to "bounded by current account credit absent top-ups".
- **N4 (line 87):** Define where "handling elapsed time" starts. The start of `do_POST` is the natural choice. The TLS handshake (`model_router.py:572-574`) is outside it, while the client's 5 seconds includes it.
- **N5 (lines 74, 85):** One `/credits` GET per paid HTTP request, across 24 parallel cases plus SDK retries, has no stated rate-limit assumption. A 429 counts as unknown credit, which refuses and defers safely. Say that throughput, not safety, is the risk.
- **N6 (line 5):** "Parent task, 2026-11-01. Base 6afceac is merged… Read docs/ENGINEERING.md." is process noise, not problem statement.
- **N7 (lines 96–97):** "persisted once and never increased" plus a hard-coded ceiling means raising the cap later needs a code change plus a data migration. Add one line saying the founder governs this and there is deliberately no runtime path.

---

## What checked out

- **Credential reach:** paid mode replaces the CLI's environment with `openrouter_environment` (`model_call_gate.py:637-651`), so the CLI never gets the OpenRouter key.
- **Diagnosis:** `diagnosis_dispatch.py:415` goes through `r.opencode` → ModelRuntime → the gate.
- **Expiry hook:** lazy lease expiry at the start of every `rpc` (`model_router.py:176`), plus `cancel` and `finish`, gives a single place to mark pending paid rows unknown in the same transaction.
- **Skipping `observe`:** `observe()` already skips `router_unavailable` (`model_runtime.py:484`). Adding a `shared_paid` skip is a one-condition change.
- **Holds on close:** `Allowance.close` already keeps active holds and refuses late refunds (`model_call_gate.py:220-233`). This matches "late finish has no settlement authority".

## Elephant disposition

PASS; no blockers. Both majors accepted before implementation. Shared paid failures raise ProviderWait directly after receipt/lease cleanup regardless of UNBUG_PROVIDER_WAIT; a latch prevents SDK retries from repeating reserve. New router credential placement is explicitly a deployment security change requiring founder acknowledgement; B3 owns RAM delivery and drain/restart rotation. Offline implementation remains unconfigured and refuses paid dispatch. Nits addressed in the design clarification below; no live action or row closure.
