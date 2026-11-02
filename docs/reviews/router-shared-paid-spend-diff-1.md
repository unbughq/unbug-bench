# Goldfish diff review: router-shared-paid-spend (6afceac..bfc292e)

**Mode:** REVIEW. **Personas:** zoom_out and implementation_readiness. **Standards:** zoom-out and implementation-readiness.
**Reviewer:** claude-opus-5-5, read-only. I made no provider, secret or worker calls.

## Verdict: **PASS**. No blockers, 3 majors, 6 nits.

## What I checked in the code

**Money safety**
- **One forwarding path.** In `factory/model_call_gate.py` `Handler.do_POST`, the gate only connects to OpenRouter after the router returns exactly `{'granted': True}`. Every other reply, and any transport error, sets the `paid_failure` latch and returns 503 before an `HTTPSConnection` is made.
- **No other OpenRouter caller in factory code.** `enforce` replaces the CLI environment, so diagnosis's `diagnosis_environment` key is dropped for gated routes. `account_handoff.py` and `launch.sh` only give the key to `run.py`, which is the gate's upstream token. Exam and harbor code is the only direct user, and the design excludes it.
- **Reservations are serialized.** Credit is read before `BEGIN IMMEDIATE` (`model_router.py:270-281`). Both money checks and the insert happen inside one immediate transaction. The commit runs when the `with db` block exits, before the reply is sent, so a failed commit returns no permit.
- **Ceiling never rises.** The ceiling is taken from the stored `paid_account` row, or from `min(PAID_CEILING, credit)` when there is none, and the same value is written back. No code path raises it.
- **Counting and rounding.** `_paid_counts` counts pending and unknown rows at the full hold, and counts settled rows in the second check only when settled at or after `fetched_at - 900`. `fetched_at` is captured before the credit read, so settlements that land during the read are counted. Holds round up and credit rounds down.
- **Unknown and cancelled calls keep their hold once.** A sweep runs at the start and end of every RPC and marks pending rows of closed leases as unknown. `_paid_settle` only changes rows that are still pending, and rows that are already settled or unknown never change. A late settlement after finish, cancel or expiry cannot refund.
- **Settlement uses the stored tariff, not the live table.** The charge is always at most the hold.
- **Settlement happens before the CLI sees end of stream.** The settle RPC runs in the handler's `finally`. `content-length` is in `HOP_HEADERS`, so the response ends only when the connection closes, after settlement.
- **Runtime behaviour on refusal.** For `shared_paid` failures, `model_runtime.py` skips `observe` and raises `ProviderWait` after the receipt is written and the lease is finished. `run.py` and `batch_holder` already handle that resume path.
- **Subscriptions are untouched.** A subscription lease gets `binding` and no paid row.

**Rollout compatibility**
- Old clients cannot get a paid lease. Paid routes are left out of acquire without the new protocol flag, and start or renew of an old paid lease is refused.
- A new client against an old server fails cleanly. This is tested over real HTTP.
- The B3 manifest, `practice-policy.json` and `release-pins.json` are not touched.

**Tests I re-ran myself at bfc292e**
- `test_router_paid_spend`: 11 tests OK
- `test_model_router`: 42 tests OK
- `test_router_cheap_maxima`: 7 tests OK
- `test_router_item8_profiles`: 7 tests OK

## Majors

**M1. The suite record does not prove which code was tested.**
- **Where:** `docs/reports/router-shared-paid-spend-suite-20261101T150101Z-9bce2a01.json` and `docs/reports/router-shared-paid-spend.md:68`.
- **Problem:** The record names only `base_commit: 6afceac`. It has no HEAD or tree hash, so nothing shows the 167-script run used the code that is now `bfc292e`. The log's SHA-256 does match.
- **Fix:** Record the tested tree, for example the `git stash create` hash or a working-tree diff hash, and show it equals `bfc292e`'s tree. If that can't be shown, re-run. My re-run of the four directly affected scripts passes, but that is not the full suite.

**M2. Two tests the design requires are missing.**
- **Where:** `tests/factory/test_router_paid_spend.py`. The design's "Gate integration and ordering" section requires that "tests must exercise workers/diagnosis-shaped callers against the same real Store and assert no batch/job identity is a partition or regrant key".
- **Gap 1:** The six-process test uses bare `Store.rpc` leases. No diagnosis-shaped call (user `pilot`, name `diagnosis-*`, through `ModelRuntime._invoke` and `enforce`) and worker call draw down the same Store.
- **Gap 2:** The design lists "success => one" upstream connection. `PaidWireTests.test_settlement_precedes_downstream_eof_and_transport_loss_retains` asserts the money total but never asserts `len(self.seen) == 1`.
- **Risk:** The code structure has no batch or job key, so the money risk is low. These are still listed exams.

**M3. The `/credits` key-type assumption is unverified and not listed as a deployment prerequisite.**
- **Where:** `factory/model_router.py:182` `available_credit` and the report's "Deployment prerequisites" section.
- **Problem:** Every paid reservation calls `GET /api/v1/credits` with the inference `openrouter-key`. If OpenRouter needs a different key type for that endpoint, or answers with 401, 403 or 429, every factory paid request refuses forever. That fails safe, but it blocks item-8 and diagnosis on OpenRouter, which is a pit stop.
- **Fix:** I could not check this offline. Add "confirm `/credits` accepts the deployed key type" to the deployment prerequisites, next to the founder acknowledgement.

## Nits

- **N1.** `model_router.py:234` `_paid_charge` repeats the formula and cost check in `token_prices.openrouter_gate_cost`. Letting that function take the stored tariff profile would remove the copy.
- **N2.** A bulk edit added `paid_protocol=1` to the synthetic OpenRouter response payloads at `tests/factory/test_model_call_maxima.py:756` and `tests/factory/test_router_cheap_maxima.py:43`. It is harmless, but it misrepresents the provider response format.
- **N3.** `test_router_paid_spend.py:202,207` mock `build_opener` entirely, so `_NoCreditRedirect` (redirect refusal) is never exercised. The design asked for an in-process fake HTTP opener.
- **N4.** `model_router.py:455`: the 4-second handling-time refusal reports reason `binding`, which the gate treats as `router_unavailable`. That behaviour is safe, but the label is misleading in audits.
- **N5.** `model_router.py:346`: the acquire replay check uses `== 1` (so `True` passes) while other checks use `type(...) is int`. It is harmless because the stored request is compared exactly, but it is inconsistent.
- **N6.** `model_router.py:276`: the credit read happens before the duplicate and binding checks, so refusals that are certain anyway still spend a `/credits` request. This matters for the endpoint rate limits already noted as a risk.

## Murphy rows

No rows are claimed closed, which matches the design. There was nothing to verify.


## Elephant disposition

PASS, no blockers. All three majors accepted. M1: the original suite record
lacked a source snapshot, so a replacement full suite will run from a clean
committed source tree and record both commit and tree plus an end-of-run unchanged
source check. No retrospective provenance is claimed for the original log.
M2: added real ModelRuntime.call/_invoke/enforce worker and pilot diagnosis calls
against one Store with distinct batch/job authorities, followed by a third-batch
refusal; OS isolation and the CLI are explicit doubles. Added exactly-one-upstream
assertion to the successful wire test. M3: deployed-key /credits acceptance and
schema are now explicit practice prerequisites. N2: removed accidental protocol
fields from synthetic provider responses. Other optional nits deferred: existing
fail-closed behavior is unchanged, and no production code changes follow review.
A fresh diff review of these follow-up changes follows the new full suite.
