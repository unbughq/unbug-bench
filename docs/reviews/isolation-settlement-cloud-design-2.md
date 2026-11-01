# Design review 2: `docs/designs/isolation-settlement-cloud.md`

**Verdict: pass. No blockers remain.** B1 and M1–M3 are fixed, and I checked each fix against the code. M4 is fixed too: the cloud section is now an archive plus a written handoff. One non-blocking major and several nits remain.

The design gets the evidence right. It says what this increment can prove (local cancellation of the current Claude call, a real process, real TLS, settlement) and says plainly that cloud qualification stays incomplete. The incomplete cloud work depends on things outside this change. It doesn't block the change.

**Review setup:**
- **Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`.
- **Personas:** zoom_out, design_critic, implementation_readiness.
- **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
- **Worktree:** `t3-c3a8faa6` at HEAD a4da071. The design and review-1 files are untracked.
- **Code read:**
  - `factory/budget.py` (`run_budgeted`, `shared_stop`, `stop_process`, the error and cleanup path)
  - `factory/model_runtime.py` (`_call`, `_invoke`, cleanup)
  - `factory/model_call_gate.py` (`Allowance.finish`, `Allowance.close`, `Handler.do_POST`, `enforce`)
  - `factory/model_router.py` (`running`)
  - `tests/factory/test_model_call_maxima.py` (ProtocolTests `setUp` and the mid-response helper)
  - `tests/factory/test_model_router.py:526-537`
  - the Murphy register rows
  - the saved provider billing and pricing reports
  - the archive source files
- **Side effects:** no repo files edited, nothing delegated, nothing launched, no paid calls. I ran one TLS check in a temp directory, outside the repo.

## Fixes checked

**B1, heartbeat in the same group: fixed.**
- `run_budgeted` starts the CLI with `start_new_session=True` (`budget.py:1111-1113`), so the CLI's PID is also its group ID.
- `stop_process` calls `os.killpg(process.pid, SIGKILL)` and then `process.wait(5)` (`budget.py:1082-1107`).
- A heartbeat child that never calls `setsid` inherits the CLI's group, so the kill reaches it. The CLI is reaped by `wait`. The orphaned heartbeat is either gone or a short-lived zombie under init/launchd. The design's check ("absent or zombie, and the heartbeat file has stopped changing") is correct.
- The design now claims nothing about descendants that escape the group, or about surviving SIGTERM. It registers the static finding (an escaped child of a non-isolated CLI survives cancellation) as `new-isolation-settlement-1`, open, with no fix claimed.
- It changes no production policy.

**M1, readiness channel and where the check happens: fixed and actionable.**
- `enforce` passes only `ENV_KEYS` through (`model_call_gate.py:28`, `:656`). So the design bakes absolute temp paths and an absolute `sys.executable` shebang into a per-test script. That is the right channel.
- Writing nothing to stdout keeps the stream-json parser out of the test.
- **The check point is real.** Cancellation goes `role_cancel` → `Allowance.is_set` (`gate.py:153`) → `shared_stop` raises `BudgetError('cancelled')` → the `finally` block runs `stop_process` → the exception reaches the wrapper. The wrapper sees it after the CLI is killed and reaped. At that point the gate is still open, and the runtime receipt and reservation have not been written yet.
- **The wrapper can reach the gate.** `_invoke` passes `cancel=gate` (`model_runtime.py:652`), so the wrapper reads it from `kw['cancel']`, as the existing test already does.
- **Real startup is exercised.** `on_started` is called by the real `run_budgeted` after `Popen`.

**M2, how TLS is injected: fixed.**
- The gate builds `http.client.HTTPSConnection(host, timeout=gate.remaining())` with no `context` (`gate.py:532`). Stacking a `side_effect` that returns the real `HTTPSConnection('localhost', port, context=trust, **kwargs)` keeps the real class and still passes `timeout`.
- The gate stores `connection.sock`, which is the `SSLSocket`, and calls `shutdown(SHUT_RDWR)` on it (`gate.py:229-230`, `:544`).
- **Checked on this machine** (OpenSSL 3.6.3, Python 3.14.6):
  - `-addext subjectAltName=DNS:localhost` produces a SAN certificate.
  - `create_default_context(cafile=…)` verifies it.
  - A `read1` blocked on a close-delimited TLS response wakes about 0.5 s after `shutdown`, with an `OSError`. The gate's `except (OSError, …)` path catches that.
- The test needs no committed certificate and makes no claim about the provider's identity. That is correctly scoped.

**M3, close-delimited TLS case: fixed.**
- Settlement stays safe because `Allowance.close()` moves active allowances into `retained` before it shuts the sockets, and the later `finish()` call then returns early (`gate.py:195-199`, `219-231`). That holds whether the interrupted read raises or returns `b''`.
- The design requires `validated_requests=0`, `settled_usd=0`, and an unchanged cap, receipt and ledger after release, for every variant. That pins the invariant that matters.

**M4, cloud reduced to archive and handoff: fixed, and honest.**
- All five source files exist at the absolute paths given (restore-14 `results/spend/…`).
- The saved spend JSON has `balance_before_usd 4.26532`, `balance_after_usd 4.17171` and `actual_spend_usd 0.09361`. That really is the difference between two account balances. It does not show what this worker cost.
- The readiness JSON contains `observed` and `provider_error`, so the allowlist step is justified.
- The saved provider report documents per-sandbox usage (`billing.md:173-224`, `pricing.md:198`). The design is right that a documented API is not a receipt.
- `HOLDER_ENABLED = False` (`batch_holder.py:26`) and `DIAGNOSIS_ENABLED = False` (`batch_service.py:21`) stay unchanged.
- The design names what is missing:
  - a reviewed control-VM launch path, or the founder's identity at launch;
  - a bounded workload that fits within USD 1;
  - a per-sandbox usage receipt;
  - a completed deletion plus a full inventory showing the sandbox is gone;
  - a documented bound on when billing stops.

## Incomplete outside this increment (not blockers)

- **Cloud exposure (prerequisite 2) stays open.** The normal launch needs credentials on stdin and a reviewed release and job configuration. It also needs eligible bootstrap and an independent cleanup step. None of that exists or is ready.
- **No live receipt can be attributed to this worker.** The design correctly refuses to accept the account-balance difference instead.
- **Not covered by this test:**
  - shutdown of live provider generation;
  - cleanup of the isolated sudo UID;
  - other routes and future profiles;
  - Murphy row 9;
  - broader item-8 acceptance.

  The design hands these back explicitly.

## Major (not blocking)

**MA1. The plan never says where the archive and blocker report go.**
- **Scope:** lines 42-45, 133-146.
- **Finding:** "Preserve public copies" and "the report lists missing evidence" name no destination. The fixture README is only implied (line 143), and no report filename is given. Only the suite log and its metadata get a name pattern (line 155).
- **Guidance:** name both, for example:
  - `tests/factory/fixtures/isolation-settlement-cloud/` with a README of hashes and the bounds each file establishes;
  - `docs/reports/isolation-settlement-cloud.md` for the blocker list.

  This is a placement choice only. It doesn't affect whether the evidence is correct.

## Nits

- **N1. `c.role_cancel` has to exist before the call starts.** `_call` copies `c` and binds `context.role_cancel = getattr(c, 'role_cancel', None) or Event()` (`model_runtime.py:346-350`). Assigning `c.role_cancel` after `runtime.call` starts would never reach the gate. Say "attach `c.role_cancel = threading.Event()` before submitting `runtime.call`; later `.set()` it".
- **N2. The fake client must outlive socket errors.** If its relayed read fails and the script exits before `run_budgeted` polls (about 0.1 s), the outcome is no longer a deterministic `cancelled`. The wrapper's "require cancelled" check would catch this as a test failure, but say it directly: the client keeps waiting after any socket error.
- **N3. The upstream wait conflicts with the old bounds.** The shared `Upstream` handler has `stall.release.wait(30)` (`test_model_call_maxima.py:554`). Line 106 says 60 seconds, and line 108 says the old case keeps its 30/5 bounds. Pick one: parameterise the wait on `self.stalled`, or raise it to 60 for all variants. Either is harmless.
- **N4. Ordering against the budget ledger.** `run_budgeted` writes `terminal_stop` and removes the invocation from `active` before `stop_process` runs (`budget.py`, the error handler runs before the `finally` block). Limit "reaped before settlement" to the gate, receipt and reservation, as lines 87-88 already do. Don't assert ordering against the budget ledger's `terminal_stop`.
- **N5. The credit rate has no source.** "0.00001 USD/second historical rate" is cited nowhere. Either cite the historical converter, or say only that the record's own `balance_after_usd` equals 417171 × 0.00001.
- **N6. Heilmeier: risks are implicit.** Add one line, such as: the real-process timing could be flaky, so cleanup is bounded in `finally`. Objectives, current state, approach, impact (line 152), cost (zero model spend), timeline (one session) and exams (lines 148-151) are all present.

## Zoom-out

- No over-building: there is no new abstraction, flag or harness. The design reuses the existing helper, its parameters and the openssl pattern.
- Deleting nothing is justified, because this increment is evidence only.
- The Murphy handling is proportionate:
  - add `new-isolation-settlement-1`, open;
  - add the TLS test to the `Closed by` cell of `new-router-item8-prereqs-1` (currently "TLS socket wake unproved") without broadening its claim;
  - close no other row.

## Result

- **Prerequisite 1 (local seam):** ready to implement. B1 and M1–M3 are fixed. It can complete at $0.
- **Prerequisite 2 (cloud exposure):** correctly reported as incomplete because of the outside dependencies listed above. That is not a blocker for this increment.
- **Blocking findings: none. Pass.** MA1 and N1–N6 are recommended before implementation and can be checked in diff review.

## Implementer response

Pass accepted. MA1 and N1–N6 accepted and incorporated during implementation: named archive/report, pre-bound cancellation event, persistent client, parameterized release wait, precise receipt/reservation ordering, historical converter citation, and bounded cleanup.
