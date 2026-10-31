# Goldfish diff review: isolation-minimax-merge-diff-1

**Verdict: PASS. No blocking findings, no major findings, and no nits that need action.**

**Mode:** REVIEW, using the `zoom_out` and `implementation_readiness` personas against `implementation-readiness-standard.md`. Step 2 (design) was skipped as a small mechanical merge. I reviewed against the beb5aa7 merge message and `docs/reports/isolation-minimax-merge.md`.

**Scope:** only the manual resolution shown by `git show --remerge-diff beb5aa7` (parents 893d268 and 6ffec7c). That touches two files: `docs/murphy-register.md` and `tests/factory/test_model_call_maxima.py`. The remerge-diff shows no hand-resolved hunks in production code, under `factory/` or anywhere else.

## Findings

None.

## Checks performed

1. **`setUp`:** The merge keeps `self.responses=None` from the incoming side and `self.https_connection=http.client.HTTPSConnection` from the other side. The real class is saved before the gate's `HTTPSConnection` patch starts, so the TLS test gets a genuine `HTTPSConnection` with the trusted localhost context. The upstream still honours `content_length`, and the deadline is still chosen per mode (60s real-CLI, 30s simulated).
2. **Helper signature:** It still takes `model`, `real_cli` and `content_length`.
   - These values come from the incoming side and remain authoritative: the MiniMax/Claude `paid` split, the maximum (`0.690001`, or `CLAUDE_PROFILES[model]`), the hold (`0.23`, or `2.409600` for 4.5 profiles, or `8.655360`), and the provider mapping through `claude_profile`.
   - The account is chosen by route (`openrouter-key` or `claude-factory-token-2`) and passed through `router_accounts=(account,)`.
   - The ledger `maximum_usd`, `estimated_gap_usd` and `held_usd` assertions all use these dynamic values.
3. **Pre-set cancellation event:** `c.role_cancel=threading.Event()` is attached before `runtime.call` in both modes.
4. **TLS client model:** `body()` already sets `model` to GATED_CLAUDE (`body()` is at line 66), so `dict(body(),model=provider)` overrides it correctly. The real CLI now sends the model of the selected profile, which matters for the 4.5 $3/$5 profiles. The in-process client was already doing the same thing via `request['model']=provider`.
5. **Linux platform patch:** It now applies only to MiniMax (`... if paid else nullcontext()`, and `nullcontext` is imported at line 29). `factory/model_call_gate.py:662` only checks `sys.platform` when the call is paid. So leaving the patch off Claude simulated-HTTP runs changes nothing that incoming 6ffec7c tested, and real Claude TLS processes run on the actual host platform.
6. **Startup path:** In the real-CLI path, `execute` hands off to the genuine `budget.run_budgeted`, which reports startup itself. Only the simulated branch calls `kw['on_started']()` directly.
7. **Real-CLI checks:** They are all still there:
   - the process-group check (`getpgid`);
   - the direct child already reaped (`ChildProcessError`);
   - the grandchild dead or a zombie, and its heartbeat frozen;
   - the gate not yet closed and the reservation still `pending` (death happens before settlement).
8. **Late-release checks:** These are unchanged after the release:
   - ledger bytes, gate snapshot and receipt bytes are immutable;
   - `reserve` returns None;
   - double `reconcile_reservations` leaves the ledger byte-identical;
   - no leases are left;
   - `router_interrupted_calls` ties the lease to the call.
9. **Coverage matrix:**
   - **HTTP:** every `CLAUDE_PROFILES` entry plus MiniMax, across 3 framing variants.
   - **TLS with a real process:** every `CLAUDE_PROFILES` entry across 4 variants, including HTTP/1.0 without Content-Length. That is 5 profiles, including `GATED_CLAUDE45:compact` ($3) and `:small` ($5).
   - **MiniMax:** remains simulated-CLI plain HTTP only. The TLS `connect` asserts the host is `api.anthropic.com`.
   - Account and provider assertions are kept: `--model`/`-m`, the OAuth token, `OPENROUTER_API_KEY` absent, and the lease route.
10. **Murphy register:**
    - `new-router-item8-prereqs-1` takes 893d268's wording, which scopes the TLS real-process evidence.
    - `new-isolation-settlement-1`, the escaped-descendant row (setsid descendant), stays open.
    - The incoming `new-batch-auth-inputs-1` stays open.
    - No row was dropped or newly closed. `new-isolation-outer-wall-2` was already closed on both parents and isn't part of the conflict.
11. **Evidence integrity:**
    - The test module blob at HEAD matches beb5aa7 (`10fdff08…`).
    - Its SHA-256 is `abdc96bd…`, which matches the suite JSON's `test_module_sha256` with `test_module_unchanged: true`.
    - The log's SHA-256 matches the JSON (`0d48cbe4…`).
    - The JSON records `tested_commit` beb5aa7 and exit 0.
    - Commits after beb5aa7 add only report and evidence files.
12. **Focused offline rerun:** `ProtocolTests.test_runtime_close_mid_response_retains_hold_once` and `test_real_process_tls_cancellation_settles_unknown_once` both passed: 2 tests, 14.3s, OK. The working tree was clean afterwards.
13. **Zoom-out:** The resolution only combines the two sides. It adds no new helper, abstraction or code path, which is appropriate for a mechanical merge.

## Limitations

- I did not rerun the full suite or the other 23 tests in the module. I relied on the recorded suite evidence and checked its hashes.
- I did not review incoming 6ffec7c changes outside the conflict hunks, including the `factory/` and `token_prices.py` diffs between the parents.
- No provider, cloud or paid calls were made, and I spawned no agents. All transport is synthetic localhost, so this review does not prove live-provider TLS behaviour or isolated-UID behaviour.

## Implementer response

PASS accepted. No findings required changes, and none were rejected. The fresh Claude reviewer independently reran both affected cancellation tests and verified the committed source/log hashes. Only this final report and response are added after review; executable source remains identical to tested merge beb5aa7. The focused 25-test result and full 165-script suite both passed. No new Murphy rows close, no live-provider qualification is claimed, and no paid OpenRouter reviewer was used.
