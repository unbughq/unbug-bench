## Diff review round 2 (final): stream-d public-match terminal outcome

**Final verdict: the implementation passes, with no blocking implementation finding open. It is not ready to merge.** `ENGINEERING.md` step 4 requires a clean full suite, and the post-fix full suite at `fb731a2` failed. That failure is still an open delivery blocker. This review does not waive it.

I reviewed `e1087df..79b7286` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` (`t3/stream-d-implementation`, HEAD `79b7286`), using `zoom_out`, `implementation_readiness` and the implementation-readiness standard. `e1087df` is the current `factory-simplify` tip and an ancestor of HEAD. The only production changes in `66f0351..fb731a2` are `extension_public_match.py`, `freshness_retrieval.py` and `late_recovery.py`. `fb731a2..79b7286` changes docs and records only. I edited, committed and ran nothing.

### B1: independently resolved
- **No-clock check only on public-match proof:** `late_recovery.py:59` adds `retained=False`. Only `extension_public_match.py:132` (`_confirmed`) passes `retained=True`. `cleared_stress` (`late_recovery.py:113`) uses the default, so it keeps the 24-hour window in `freshness_retrieval.py:111`.
- **Checks kept in no-clock mode** (`freshness_retrieval.py:100-116`):
  - receipts must be a list that matches the rows;
  - `at` must parse and carry a timezone;
  - URLs must match;
  - responses must be present, with plain names, no symlinks, and matching body hashes;
  - the retrieval digest must equal `confirmation.retrieval_sha256` (`late_recovery.py:89`);
  - completion, verdict hits and the search binding must match, and the case hash must match (`:93-98`).
  - Retained mode also adds a whole-tree check that rejects any symlink or special file (`:86-87`).
- **No other clock in the path:** I traced `search_binding`, `attack_report`, `checked_freshness_verdict`, `_receipt` and `_intent`. None of them reads the clock.
- **Tests:** `test_retained_public_match_replays_and_retires_after_retrieval_expiry` moves the clock 49 hours ahead by patching the global `datetime.datetime`, which also covers admission. Under that clock it checks:
  - `verified` and `completed_route` succeed;
  - `run` stops with `extension_incomplete`;
  - after `diagnosis()`, `subsequent_entry` refuses with `retired_no_progress`;
  - no fetch, review, writer or Evaluator runs, and the money ledger does not change.

  It then runs `verified` again with a clock whose `now()` raises an error, and that passes. `test_confirmation_cache_completes_after_retrieval_expiry` covers a crash after the cache was published followed by completion 49 hours later. All 20 public-match tests pass in the post-fix full run (log line 1242).

### M1: independently resolved
- The whole-tree check now runs only in retained mode. For ordinary clearance, a symlinked body is caught inside `load`, giving `InvalidInfra`, which becomes `ValueError`.
- `read` (`late_recovery.py:67-74`) turns missing files, files that aren't objects, and bad JSON into `Refused`, which is a `ValueError`.
- `test_clearance_corruption_and_expiry_keep_execution_pending_policy` covers a symlinked body, a missing `review-completed.json`, a `verdict.json` that isn't an object, and expiry 49 hours later. For each case it checks `extension_execution_pending` at the package boundary and `ValueError` from `mark_gates`.

### N1–N3: resolved
- **N1:** the `capture.record` body is wrapped and every failure becomes `extension_snapshot_changed`. Tests cover `{}`, invalid JSON, and a receipt with no binding.
- **N2:** tests now cover a stale binding (returns False), a different entry identity (refuses), a same-family reviewer (refuses), and a symlinked live proof file before completion (refuses).
- **N3:** the `gate_results` projection is documented in the design under "Diff-round-1 corrections".

### New findings (none blocking)
1. **Nit: the N1 wrapper renames a money wait.**
   - **Where:** `factory/extension_public_match.py:103`, under the catch-all at `:108`.
   - **Problem:** `job_authority.for_case(c)` sits inside the `try`. It can raise `BudgetError('money_wait')`, `'retired_batch_bound'`, or `MoneyWait`, which is a `ValueError`. Any of these would be renamed `extension_snapshot_changed`, which is one of the evidence stops (`EVIDENCE_STOPS`), not a money wait.
   - **Risk:** low. The same authority check has already passed at run entry, and nothing changes it mid-attack.
   - **Fix:** do what `complete()` does at `:184`. Call `for_case(c)` once before the `try` and use its `source_generation`.
2. **Nit: one failure type still differs on ordinary clearance.**
   - **Where:** `factory/late_recovery.py:93`.
   - **Problem:** the report is now read with `_input_bytes`. If it is missing, that raises `OSError`, where the old `sha()` raised `Refused`. It also rejects symlinked parent directories, which the old code allowed.
   - **Risk:** a missing report is unreachable in practice, because `gate_marker` returns early when `attack_report` is None, and `:291` catches `OSError`.
   - **Fix:** optionally wrap the read in the same `require` mapping.

### Delivery blocker (separate from the implementation)
- **Full suite at `fb731a2`:** 175 scripts, 1 failed, exit 1. Only `tests/factory/test_control_resume.py` failed: 9 failures and 4 errors, all `TimeoutExpired` or "controller did not reach…" at 10–20 second deadlines.
- **The "isolated" recheck was not isolated:** it ran 07:54–08:07, inside the full run's 07:26–08:32 window. Load was about 38 at the start and 254 at the end. Neither record is a quiet-host result.
- **Evidence it is load, not this change:** the failing controller tests don't import or call any module this diff touches. One test that failed is a bare `sh` guard script with a stubbed `collect_vm`, and it timed out after 10 seconds. The same script passed at `66f0351`, and the only changes since then are the three modules above. This is strong evidence of load, but it is not proof. The blocker stays open until the full suite passes cleanly on this source.
- **Required fix:** rerun the full command at `fb731a2` or later, with nothing else running, and commit the record. Do not weaken timeouts in this slice.

### Scope and invariants
- Only the confirmed public-match terminal is in scope. There is no lane 1 slice 2/3 work and no lane 2 work.
- Unchanged-writer handling still runs first in `completed_route`, `run` and `subsequent_entry`.
- Diagnosis is still disabled, and the Murphy register is unchanged, so no row closes.
- The `test_launch_manifest.py` change only adds the new module to the expected worker files.

### Skipped checks and remaining risk
- **Not rerun:** the full suite and the focused tests, as instructed. Test results come from the committed log.
- **Not traced:** every downstream handler of `extension_snapshot_changed` for the authority mislabel in nit 1.
- **Residual risk from round 1:** if `c.case` changes after an intent is excluded but before stress is saved, a resumed run would refuse. Nothing tests that path.
- **Layout risk:** ordinary clearance now uses no-follow reads relative to `c.work`. If any real VM layout puts a symlink between `c.work` and the attack or verdict files, clearance would now refuse. I found no such layout.

**Remaining blocker (3 lines):**
1. The implementation passes. B1 and M1 are independently resolved, and only two optional nits remain.
2. Delivery is blocked: the full suite at `fb731a2` failed `test_control_resume.py` on deadline timeouts, while host load was 38–482.
3. To clear it, rerun the full suite on a quiet host at `fb731a2` or later, get 175/0, and commit the record. Merge only after that.

## Elephant disposition

B1 and M1 are independently resolved by this fresh final review; no blocking finding was rejected or self-approved. The two new nits are optional and deferred, with no source changes after the reviewed fb731a2 source. The required full-suite delivery blocker remains open. The file-only controller recheck ran concurrently with the full command and is not a quiet-host isolation result; the report now says this explicitly. Per the user's two-round limit, stop and return the remaining blocker in three lines. Do not claim merge readiness, a clean post-fix suite, any Murphy closure, or completion of later slices.
