# Router maxima diff review 1

**Reviewer:** fresh goldfish, a different model family from the author, read-only. Personas: `zoom_out` and `implementation_readiness`, `Mode: REVIEW`.
**Scope:** `a3bb9dc..fcc0030` (frozen implementation), plus the follow-up `fcc0030..de33c1b`. The follow-up touches only tests, docs and evidence: `git diff fcc0030 de33c1b -- factory bin` is empty.
**Design basis:** `docs/designs/router.md`, the follow-up section, plus interfaces §§2/3/4/7. Design reviews 2, 3 and 4 and their author responses were read.

## Verdict: FAIL — 0 Blockers, 1 Major, 8 Nits

The money bound holds. I found no path that sends a request after the joint dollar or token test fails, and no path that gives back an allowance for an uncertain response. The arithmetic matches the design: W = $19.041792, token ceilings 113,636,363 in and 1,136,363 out, and the gate prices settled usage at the same 2×1.1 rate as the unchanged estimator.

It fails on one problem the design shares: the gate treats a request that only overlaps in time with others as a terminal cap stop (M1). That turns ordinary concurrent CLI requests into an unscored `model_call_cap` stop that D must then diagnose. That is the pit-stop class this factory is trying to remove.

**Test evidence:**
- Full suite on `fcc0030`: 135 scripts ran, 1 failed (`tests/factory/test_invalid_runs.py:613`). Recorded in `/tmp/router-maxima-full-fcc0030.json`, exit code 1.
- Full-suite rerun on `de33c1b`: **still running** when this review was written. The log is `/tmp/router-maxima-full-de33c1b.log`, and the metadata file does not exist yet. Neither run counts as a pass yet; the author should append the final result here.

---

## Major

### M1. Requests that only overlap in time trigger a terminal `model_call_cap`

**Scope:** `factory/model_call_gate.py:149-163` (`Allowance.reserve`), and `tests/factory/test_model_call_maxima.py`, `test_concurrent_reservations_and_close_never_refund_unknown`, which asserts the behaviour: of 16 concurrent reservations, 2 succeed and `is_set()` is true. The design wording is at router.md: "Exhausted means a monetary/token pre-admission test failed".

**Evidence:**
- `reserve` compares settled + held + new W against the maximum, where held includes **active** in-flight allowances. On failure it sets `exhaustion`. That flag is sticky, kills the CLI through `run_budgeted(cancel=gate)`, and `enforce` turns it into `BudgetError('model_call_cap')`.
- Every request reserves at least $17.60 just for the 1M-token input bound. So three concurrent requests are always fatal, even with $0 settled, and two are fatal once settled usage passes about $11.9.
- The CLI really does send concurrent requests:
  - writer and stress_tester run with `WebFetch` (`model_runtime.py`, the `--tools` line);
  - `ANTHROPIC_SMALL_FAST_MODEL` routes WebFetch summarisation through this same gate;
  - Claude Code runs read-only tools such as WebFetch in parallel.
- All eight Linux scenarios are serial, and `--network none` stops WebFetch before its side request, so no concurrent case has been exercised.

**Why it matters:** an in-flight allowance is not spent money. It can still be released when the response completes and validates. Treating it as exhaustion produces unscored factory-limit stops on normal research turns. It also changes the "exhaustion is terminal" rule from "the money is gone" to "requests happened to overlap".

**Action (small):**
1. Under the existing lock, keep the terminal test but evaluate it on settled + **retained** (unknown) + W + headroom. If that fails, set exhaustion exactly as now.
2. If it fails only because of active allowances, wait on a `threading.Condition` that `finish()` and `close()` notify. Bound the wait by the gate deadline, `closed` and `cancel`, and re-check under the lock before forwarding.
3. Nothing is forwarded until the request fits, so the money guarantee is unchanged.
4. Amend the router.md exhaustion sentence to match.
5. Add two tests:
   - two requests in flight plus a third: the third waits, then forwards after one validated finish;
   - the retained (unknown) part alone overflows: the stop is still terminal and sticky.

---

## Nits

**N1. A complete upstream error response holds a full W, and the cap label overrides the provider's label.**
- Scope: `model_call_gate.py:352` (only status 200 can settle) and `:400-401` (`finally` replaces any in-flight `BudgetError` with `model_call_cap`).
- A complete 429/503/529 response costs nothing at the provider but keeps $19.04 held. With production `CLAUDE_CODE_MAX_RETRIES=0` the pinned CLI did not retry (the exam needed a test override of 3), so this is usually one W per lease. Still, whenever exhaustion is set, a `provider_limit` carrying `provider_failure`/`reset_at` is replaced. The router then loses the account-limit observation that §"Failure classification" says is preserved.
- Action: keep W retention, which is conservative and accepted in the design. But when exhaustion is set and the inner error carries `provider_failure`, record that observation before re-raising, or say explicitly in the design that it is dropped.

**N2. `cancellation_failed` (E's cleanup label) is overwritten.**
- Scope: `model_call_gate.py:401`.
- That label means a sudo child may have survived. Re-raise `cancellation_failed` unchanged and keep `cap_used.exhausted=true` as the record. The design's override list names "CLI/process/cancel labels", not cleanup failures.

**N3. A parent cancel is answered as `model_call_cap`.**
- Scope: `model_call_gate.py:155` together with `:323`.
- When the shared role cancel is set, `reserve` returns None and the CLI receives the `model_call_cap` message even though `exhausted` is false. The receipt is correct; only the message is wrong. Use a different fixed message, or none.

**N4. The release path has only seen synthetic SSE.**
- Scope: `Usage.merge`/`event`/`final`.
- Every validated response so far came from author-written SSE (`sse()` in tests, and the probe's fake upstream). No real provider bytes exist in the fixtures. If real streams send `null` for optional fields in `message_delta` usage or for `server_tool_use`, every response falls to unknown, and the route dies after two requests. That fails closed, so no money is at risk, but it makes the route practically unusable.
- Action:
  - in B's practice exam, require `validated_requests > 0` and `unknown_requests == 0` on a normal completion;
  - consider treating an explicit `null` as "absent". `message_start` must still supply all four integers, so this is safe.

**N5. The rollout note understates what this deploy invalidates.**
- Scope: router.md, the paragraph added in `de33c1b`.
- `gate_state.MODEL` contains `model_runtime.py`, `token_prices.py` and `calibration.py`, and both `judge_dependencies(calibration=True)` and G8/G9/G16 inputs hash them. This diff changes all three. So on deploy, every saved calibration attempt and every G8/G9/G16 reuse record stops matching, which means paid re-runs on resume. That happens even without the `calibration.py` edit.
- The coupling existed before this change. It is contained here, because the old leases are drained first and no current rotation qualifies. But the note should say this accurately, not attribute it to "the propagation-only calibration change" alone.

**N6. `model_call_gate.py` is not in `gate_state.MODEL`.**
- `token_prices.py` is in that list, yet the gate changes what reaches the model: thinking normalisation, context_management removal and request rejection. Decide explicitly whether a later gate edit should invalidate G8/G9/G16 evidence, and record the decision in one line of the design.

**N7. The `calibration.py` edit is optional.**
- `interruption_label` only feeds the diagnostic counter `calibration_interruptions` before `calibrate` re-raises (`run.py:2178-2183`). `model_call_cap` propagates whether or not that edit exists.
- Reverting the hunk avoids touching a file C pins. The trade-off is that the counter then shows `unknown`. Either choice is acceptable; deleting the hunk is the smaller diff.

**N8. The follow-up test's negative checks are conditional.**
- Scope: `tests/factory/test_invalid_runs.py`, in the `de33c1b` follow-up.
- Make the two negative checks unconditional at this HEAD, with `assertNotEqual(actual, current)` and `assertNotEqual(actual_panel, panel)`, so the "newer identity is refused" proof cannot skip silently.

---

## Assessment of the test-only follow-up (`fcc0030..de33c1b`)

Accepted, subject to N8. The original test built `current` from the live code and overrode only the files pinned by the C policy. So it never proved that real production migration works across non-policy changes: any A-side `model_runtime.py` change already breaks that. It was a test of the policy function that also happened to require `calibration.py` to be byte-identical to C's target.

The new form keeps the positive case on C's registered target. It adds checks that the live, newer identity and panel are refused, and keeps the seed and `bin/bench.py` mutation checks. Runtime policy, `compatible_identity`/`compatible_panel` and scoring are unchanged. Native fixture source hashes are unaffected because `factory/` and `bin/` are byte-identical.

The validation doc now records the failed first run honestly. The final full-suite result is still pending.

## Prior findings, checked against the code

| Prior item | Status at `fcc0030` |
|---|---|
| R2 B1–B3: replace the fixed 8 requests with dollar/token admission before any network call; hosted/web requests not fatal | Done: `reserve` runs before connect; a rejected hosted tool gets a local 400 and `unsupported` is counted (Linux tools scenario) |
| R2 M1: authenticate before reading the body; no token substitution | Done (`do_POST:306-308`); an auth failure changes no state |
| R2 M2: overclaims | Scope is stated in the module docstring and router.md |
| R2 M3/M4: protocol, headers, env allowlist | Done: one `ENV_KEYS` list feeds both env and the sudo preserve list; fixed headers and betas; hop-by-hop headers stripped |
| R2 M5/M6: actual native Linux retry/compaction/tools/output/sudo exam | Done on x64 and arm64; test-only overrides are disclosed; **no concurrency scenario** (see M1) |
| R2 M7: `model_call_cap` propagation for every role | Done: `run.py` preflight, early probe, provider probe loop, `interruption_label` |
| R2 M8: drained deployment | Done: old leases are refused at renew, start and replay |
| R3: exact `cap_used` v1 schema | Done: keys, decimal strings and disjoint counters match; snapshot is immutable after close |
| R3: native Linux retry exam | Done: 2 forwarded, 2 unknown, `model_call_cap`, a single Lease |
| R4: `final_usage_known`, headroom, 2.2 estimator for both W and settled, lost CLI final | Done (`model_runtime.py` receipt predicate; real-replay test) |
| Parent bug fixes: sticky exhaustion, no auto-reconnect after close, initial-only/empty terminal usage keeps W | Done, with regression tests |

The supplied-lease and RPC tamper checks, the one-use start (a slash marker in `observations`) and the per-call launch permit hold. Unknown and other routes return `Wait('unbounded_route')`, and capacity for them is 0. No Murphy row is claimed closed, which is correct: rows 2, 3, 4, 20, 47 and 48 remain open.

**To pass:** fix M1 with its regression tests, address N8, and get a green full-suite run on the final SHA. All the Nits are optional.

## Author response

Fixed M1: temporary active allowances now wait on a deadline/cancel/close-bounded Condition under the existing admission lock. Only settled plus retained unknown allowances can make exhaustion terminal. finish/close/exhaustion notify all waiters. Both reviewed regressions pass, as do cancellation/deadline/close wakeups and sticky retained-unknown exhaustion. All original eight Linux native probes were rerun at the changed source hashes, plus two architecture-specific native concurrency exams; all ten pass. No finding is rejected.

Fixed N8 with unconditional actual-newer identity/panel inequalities and rejection assertions. Fixed N2/N3 with cancellation_failed preservation and a distinct nonmonetary local denial label. Documented N1's deliberate provider-observation loss, N4's real-stream practice predicate and N5's full evidence-invalidation scope. Fixed N6 by adding the gate to gate_state.MODEL; this changes evidence identity, not scoring. N7's diagnostic label is retained to accurately count cap interruptions; reverting it is optional, not a blocking finding.

The running second full suite is superseded by the accepted implementation finding. A final full run will follow stabilized fixes and fresh re-review; no superseded run is claimed as passing final evidence.
