**Pass. Nothing blocks the merge.** I found one Major issue, which is a one-line fix in the Murphy register, and four nits.

## What I checked independently
- **Scope:** the four commits since `a4da071` touch only tests, docs and fixtures. No `factory/` file changed. Commit `a4e4a21` changes one line in the test cleanup and nothing in production.
- **The test does the real work.** `test_real_process_tls_cancellation_settles_unknown_once` calls the real `budget.run_budgeted` (`tests/factory/test_model_call_maxima.py:761`). That function starts the client in its own session and kills the process group (`factory/budget.py:1082-1113`).
  - Cancellation comes only from `c.role_cancel`. It is attached before the call starts and set only once both the readiness file and the heartbeat file exist.
  - When `BudgetError('cancelled')` arrives, the wrapper checks that the client was already reaped (`waitpid` raises `ChildProcessError`, and `ps` returns nothing). It checks that the heartbeat process is gone or a zombie and that its file stops changing. It also checks that the gate is not yet closed and the reservation is still `pending`.
  - That ordering covers the gate and the reservation, as review-2 N4 asked, and not the budget ledger's `terminal_stop`.
  - Any assertion failure there surfaces as an `AssertionError` rather than `cancelled`, so `assertRaisesRegex` catches it. The check has teeth.
- **TLS really verifies.** The client uses a default context trusting a per-test localhost certificate with a SAN. The connection is the real `HTTPSConnection` and verification is never turned off. Only the gate's `http` namespace is redirected.
  - All four variants run: HTTP/1.1 keep-alive, HTTP/1.1 `Connection: close`, HTTP/1.0 with Content-Length, and HTTP/1.0 without it (close-delimited).
- **Settlement:** USD 8.655360 of unknown usage is held once. The USD 50 reservation becomes an `estimated` gap. `settled_usd` and `validated_requests` stay at 0 and the router lease list is empty.
  - The test captures ledger bytes before the upstream is released. After release, the ledger, receipt and gate snapshot are byte-identical, and two reconcile replays leave the ledger unchanged.
  - The plain-HTTP test keeps its old 30 s / 5 s bounds, and its timestamp race is now ordered by an event.
- **Cleanup:** the finally block sets the cancel event, releases the upstream and shuts the pool down. It kills the process group only when the process check did not complete.
- **Focused re-runs** (allowed by the brief):
  - The whole module ran 23 tests, OK, in 7.8 s.
  - `ProtocolTests` ran 7 tests, OK.
  - The negative control failed again exactly as recorded: one failure at `handler_done.wait`, 16.0 s.
  - After both runs, `pgrep` found no leftover client or heartbeat processes.
- **Suite evidence:** the log's SHA-256 matches the JSON (`6e22df47…`). The log ends "159 test scripts run; 0 failed", and the module segment shows 23 tests OK. The JSON's test-module hash (`3c912578…`) matches both `a4e4a21` and HEAD.
- **Archive:** all five source hashes match the files in the restore-14 directory. Four copies are byte-for-byte. The readiness copy drops `holdsCreatorLogins`, `provider_error`, `deadline_monotonic` and `hydration_phase`.
  - The request and completion share operation `bdop_fdc5…` and target `bx_d6dzvjbc`.
  - Readiness finished around 09:53Z, before the 11:18:20Z completion.
  - The balance figures check out (4.26532 − 4.17171 = 0.09361) and are correctly called an account-balance change, not worker cost.
- **Unfinished-task limits are stated honestly.** The report says cloud exposure is UNQUALIFIED, spend was USD 0 and the USD 1 approval is unused. It says `HOLDER_ENABLED` and `DIAGNOSIS_ENABLED` stay false, and it lists the missing receipts and the control-VM launch dependency. It makes no claim about live providers, isolated users, escaped sessions or other routes.
- **Murphy scope:** no row was newly closed. The `Closed by` cell of `new-router-item8-prereqs-1` (already closed) was extended, and it still names its limits: synthetic protocol and job authority, no live provider, no isolated user. `new-isolation-settlement-1` is added as open with no claim of a fix. Row 9 is untouched.

## Blockers
None.

## Major (not blocking; fix in the merge commit)
**M1. The new Murphy row sits outside the table** (`docs/murphy-register.md`, the empty line between `new-router-item8-prereqs-1` and `new-isolation-settlement-1`). In Markdown, an empty line ends a table. The open escaped-session row therefore renders as a stray paragraph, not a register entry. Nothing in the code reads the register, but the register is the record of truth and this row is the main open-risk claim of the increment. Delete the empty line.

## Nits
- **N1. The suite JSON contradicts itself.** It says `"uncommitted_implementation": false`, but `source_timing` says the run started with uncommitted test changes. The module hash is stated, not captured when the runner loaded the file. Changing the field to `true` or `"test-only, see source_timing"` would fix it. The risk is low: my re-run at HEAD passes 23/23 and no production file changed.
- **N2. The negative control turns only the HTTP/1.1 `Connection: close` variant red.** The other three variants are not shown to depend on the socket-shutdown call. That is acceptable, but the report could say so in one line.
- **N3. The readiness edit isn't fully specified.** `provenance.json` says only "public field allowlist" and doesn't list the keys kept. The README's "omits arbitrary observed … fields" also reads as if all of `observed` was dropped, when a subset was kept. Listing the kept keys would fix both.
- **N4. One line in the report reads as if it has been done.** "The fresh diff review is saved under the same topic" is still pending until this review is saved as `docs/reviews/isolation-settlement-cloud-diff-1.md`.

## Zoom-out
- There is no new abstraction, flag or harness. The existing helper is parameterised, `run_budgeted` and the openssl pattern are reused, and no production path changed.
- The cleanup guard runs only on failure paths, which is appropriate.
- The design-2 points MA1 and N1–N6 all show up in the code or the docs.

## Implementer response

Pass accepted; no blockers were raised or rejected. M1 fixed by removing the blank line before the new Murphy row. N1 fixed by marking the suite as starting with uncommitted test implementation, retaining source timing and the final module hash. N2 clarified that only the HTTP/1.1 Connection: close variant is selected by the negative control. N3 fixed by listing the exact retained readiness fields in provenance and README. N4 resolved by saving this review verbatim here. These final changes are documentation/metadata only; no executable source changed after the passing full suite and independent focused reruns.
