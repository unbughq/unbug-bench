# Goldfish design review: `docs/designs/isolation-settlement-cloud.md`

The design does not pass yet. It has one blocking finding. Of the two requested prerequisites, it can complete only the local part of the first one. It cannot complete the second, cloud exposure, and it says so honestly. The full review is below, ready for you to save as `docs/reviews/isolation-settlement-cloud-design-1.md`.

---

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`
**Personas:** zoom_out, design_critic, implementation_readiness
**Standards:** heilmeier-standard.md, implementation-readiness-standard.md
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-c3a8faa6` at HEAD a4da071 (design file untracked)
**Files read:**
- `docs/ENGINEERING.md`, the three persona files and both standards
- the design
- `tests/factory/test_model_call_maxima.py` (ProtocolTests)
- `factory/budget.py` (`run_budgeted`, `stop_process`)
- `factory/model_runtime.py` (`_invoke`, cleanup)
- `factory/model_call_gate.py` (`Allowance`, `Handler`, `enforce`)
- `factory/job_authority.py:for_case`
- `factory/launch.sh:85-160`
- `docs/murphy-register.md` (rows 9, 43, 44, new-isolation-outer-wall-2, new-router-item8-prereqs-1)
- `docs/reports/isolation-item8-prereqs.md`
- `docs/designs/stream-d.md` (item 8)
- `tests/factory/fixtures/isolation-timeouts/*`
- the saved restore-14 spend and deletion JSONs, read-only

No files were edited, no agents spawned, nothing launched, and no paid calls made.

## Verdict

**Not passing.** One blocker (B1), four majors, several nits.

## Blocker

### B1. The separate-session heartbeat will survive local cancellation, so "stopped heartbeat" cannot pass

- **Severity:** Blocker
- **Scope:** design lines 17–23; `factory/budget.py:1082-1107`; `factory/model_runtime.py:668-676`
- **Finding:**
  - In the local test, `user=None`. The real cancellation path is then only `stop_process()`, which calls `os.killpg(process.pid, SIGKILL)` and then `process.wait(5)`. The CLI is started with `start_new_session=True`, so this kills only the CLI's own process group.
  - A heartbeat child that calls `setsid` (the design's "separate-session heartbeat child") is outside that group. Nothing in the `user=None` path kills it. The only escaped-descendant sweep is `sudo pkill -KILL -u user`, which runs only when `user` is set. The design explicitly excludes that path ("not … isolated sudo UID cleanup").
  - So the assertion "stopped heartbeat … before settlement is accepted" will fail on the current code. An implementer would have to quietly change the test's meaning or the production code. "Ignoring SIGTERM" also tests nothing here, because the path sends SIGKILL.
  - This is not only a test-design problem. Builder and attacker roles call `opencode(...)` without `user` (`factory/run.py:787`, `:1159`, `:1435`, `:1516`). In production, a descendant that escapes from a non-isolated CLI can outlive cancellation. Money stays safe because the closed gate refuses its later requests (comment at `budget.py:1262-1264`). Process survival and contamination are not handled.
- **Required decision (pick and write it down):**
  - (a) Put the heartbeat in the CLI's process group. Assert that killpg kills it and that the CLI is reaped. This is the honest claim for this seam.
  - and/or (b) Keep a separate-session child as well, and *expect it to survive*. Assert that a request it sends after cancellation gets `invocation_stopped`/502, that it causes no reserve, and that the snapshot is unchanged. Register `new-isolation-settlement-1`, the non-isolated escaped descendant that survives role cancellation, before any fix. Murphy rows 43/44 are the precedent.
  - Do not assert "stopped heartbeat" for a separate-session child unless the design adds and scopes a cleanup mechanism for `user=None`.

## Major

### M1. The readiness channel and the "before settlement" observation point are left to the implementer

- **Scope:** lines 17–25
- **Finding:**
  - `enforce` replaces the environment with `ENV_KEYS` only (`model_call_gate.py:28`, `:657-664`), so the fake CLI cannot receive a side-channel path through a custom environment variable.
  - Its stdout is parsed by `run_budgeted` as Claude stream-json. A JSON line could be consumed as a ledger event, and non-JSON goes to `diagnostic()`.
  - The design does not say:
    - how the fake CLI learns where to signal;
    - how the test reads the CLI and heartbeat PIDs;
    - where "reaped before settlement is accepted" is checked.
- **Guidance:** specify the following.
  - Generate the client script per test with absolute temp paths baked in, and an absolute `sys.executable` shebang.
  - Use readiness and PID files, and write nothing to stdout.
  - Have the wrapper catch the real `run_budgeted` exception and assert the process states before re-raising. The receipt and ledger are written only after `enforce` exits, so this checkpoint is ahead of settlement.
  - Name the existing `self.stalled.release`/`received` events the test reuses.

### M2. How TLS is injected is undecided

- **Scope:** lines 28–30; `model_call_gate.py:532`; ProtocolTests `setUp:563-566`
- **Finding:**
  - The gate constructs `HTTPSConnection('api.anthropic.com', timeout=…)` with no `context`.
  - "Patch only the connection destination to localhost, retaining the actual HTTPSConnection" fits two incompatible mechanisms:
    - (i) a `side_effect` that returns a real `HTTPSConnection('localhost', port, context=trusting_ctx, **kw)`. Hostname verification is then against `localhost`.
    - (ii) keep the host and redirect `socket.create_connection` or the default context, using a certificate with a SAN for `api.anthropic.com`.
  - `setUp` already patches `HTTPSConnection` to plain HTTP for every test, so the TLS variant must stack its own patch. The upstream `ThreadingHTTPServer` also needs a TLS-wrapped socket; the design never says this.
- **Guidance:** choose (i). What is under test is `SSLSocket.shutdown(SHUT_RDWR)` waking a blocked `read1`. CPython clears `_sslobj` on shutdown, which is the real TLS-specific difference from plain sockets. Hostname identity is not under test. Reuse the openssl certificate generation and `ssl.create_default_context(cafile=…)` pattern at `tests/factory/test_model_router.py:526-537`. Do not add a new certificate fixture.

### M3. The variant list skips the TLS case where a truncated stream looks complete

- **Scope:** line 31; ProtocolTests upstream (`Content-Length` always sent)
- **Finding:**
  - All three variants send `Content-Length`, so even "HTTP/1.0" is length-delimited. A truncated body then raises `IncompleteRead`.
  - With `suppress_ragged_eofs=True` (the default for `HTTPSConnection`), a close-delimited TLS body that is cut off returns `b''`. That looks like a clean EOF, and `parser.final()` runs.
  - Settlement is currently safe only because `Allowance.close()` moves active allowances into `retained` *before* it shuts the sockets, so the later `finish()` call returns early (`model_call_gate.py:197-199`, `219-231`). That ordering is the invariant to pin.
- **Guidance:** add one TLS variant with no `Content-Length` (HTTP/1.0, close-delimited). Assert that `validated_requests` stays 0 and `settled_usd` stays 0 after release.

### M4. The cloud prerequisite has no workload, no exit criteria and no definition of "attributable", and it depends on things outside the agent's control

- **Scope:** lines 39–54
- **Finding:**
  - **Honesty:** good. The design correctly says that `actual_spend_usd: 0.09361` in `20261029T095210Z-99393-factory.json` is `balance_before − balance_after`, which is an account delta and not worker billing. It also correctly says one deletion completion (`bdop_fdc58246…`, `completedAt 2026-10-29T11:18:20.705Z`) gives no upper bound on outage time.
  - **External dependency the agent cannot meet:**
    - The normal launch path refuses to run without the founder's age identity piped on stdin (`launch.sh:140-143`).
    - Batch launches also need holder job configuration and a batch release (`launch.sh:62-71`).
    - So "a live worker … only through the normal single launch path" cannot happen without the founder in the loop. The design does not say this.
  - **Undefined workload:**
    - The normal path launches a factory case. The saved precedent was `--restore … --qualified-release candidate-vm-canary --max-spend 0.75`, with model roles.
    - That conflicts with "zero model spend" on line 70.
    - The design does not say what the worker would run, or how model calls are excluded or bounded inside USD 1.
  - **Undefined acceptance:**
    - The design does not say what counts as "attributable billing".
    - The saved `billing.json` exposes only an account-level `creditBalanceSeconds`. If Boat has no per-sandbox usage, even a successful launch cannot meet the line 53–54 criterion unless a sole-tenancy bracket method is defined in advance:
      - a complete-inventory snapshot that is empty before and after;
      - no other workers;
      - a documented balance-settlement latency.
    - "Read current provider docs and compare" has no stated exit condition.
- **Guidance:**
  - State now that prerequisite 2 will not complete in this increment.
  - List the external dependencies:
    - the founder's identity or presence at launch;
    - a provider per-sandbox usage source, or founder acceptance of a bracket method;
    - the documented deletion and billing latency.
  - Reduce this section to the archive step (hashes and exact bounds) plus a written blocker list.

## Nits

- **N1. Source paths (lines 41–43).** The spend and deletion files are at `…-restore-14-20261029/results/spend/20261029T095210Z-99393-factory{.json,.deletions/bx_d6dzvjbc/…}`. That is not the `control-home/launches/6533…` directory that README cites. Give absolute paths, and also include `deletion-completion-query.json` and `-bx_d6dzvjbc.readiness.json`.
- **N2. "Identity" (line 44).** Limit this to sandbox and operation IDs. No account or founder identity. Also reconcile with the README's "no identity … copied" while `created.json` already contains `bx_d6dzvjbc`.
- **N3. Units.** `balance_after_usd 4.17171` matches `creditBalanceSeconds 417171`. Note the unit conversion explicitly; do not assume the field is in dollars.
- **N4. The "60-second network timeout" (line 33) has no source.** The upstream timeout is `gate.remaining()`, which is the call limit (30 s in this test). Cite the real bound.
- **N5. Implementation.** Parameterise the existing `_runtime_close_mid_response_retains_hold_once` by `(transport, cli)` rather than adding a sibling copy. That is the "reuse" the design promises at line 58.
- **N6. Murphy text.** Say that `new-router-item8-prereqs-1`'s `Closed by` cell, which currently reads "TLS socket wake unproved", will be amended in the same commit that adds the TLS evidence. Name the report filename pattern, as earlier designs did: `docs/reports/isolation-settlement-cloud-suite-<UTC>-<nonce>.log`.
- **N7. Heilmeier gaps.** No timeline beyond "one increment". No per-prerequisite exam for success or failure. Impact is implicit (item 8 / `DIAGNOSIS_ENABLED` gating), not stated.
- **N8. Factory admission is first exercised here.** The real `run_budgeted` will now run factory admission for the first time in this harness. The existing `c` looks sufficient (`job_money` and `authenticated_job_config` match `for_case`), but say that a `money_wait` failure means the harness is wrong, not that the product needs a fix.

## Zoom-out

- No over-building (YAGNI) problems. There is no new abstraction, flag or provider layer, and deleting nothing is justified.
- The scope is right for prerequisite 1.
- The cloud section is an investigation with no exit condition and should be narrowed (M4).

## Can this design complete both requested prerequisites?

**Prerequisite 1: invocation cancellation and settlement (A/D).**
- **Locally:** yes, at $0, once B1 and M1–M3 are fixed. Nothing external is needed.
- **Limit:** it qualifies only the local, non-isolated, current-Claude seam. Shutdown of live provider generation and the isolated-UID path stay unqualified, as the design says.
- **Implementation blockers:** B1 (and M1–M3).

**Prerequisite 2: cloud exposure (B/E).**
- **Cannot complete in this increment.**
- **External dependencies:**
  - the founder's age identity on stdin for `launch.sh`, plus batch job configuration if the batch path is used;
  - a provider source of per-sandbox attributable usage, or a sole-tenancy bracket method the founder accepts;
  - documented deletion and billing settlement latency to bound the cleanup tail.
- **Implementation gaps (fixable in the design):**
  - an undefined live workload that conflicts with "zero model spend";
  - no acceptance criteria for "attributable" and "complete inventory";
  - imprecise source paths.
- The design does not overclaim here (lines 52–54).

**Admission gates:** nothing in the design bypasses them. The USD 1 limit can only go through the normal path, which currently needs the founder.

## Implementer response

Accepted B1 option (a): same-process-group heartbeat, no escaped-child death claim. M1–M3 and N1–N8 incorporated in the revised design. M4 accepted as an archive-and-blocker handoff; no live launch is attempted in this increment. No findings rejected. Fresh design review requested.
