## Goldfish follow-up review: router-shared-paid-spend (bfc292e..cfa7d5d)

**Mode:** REVIEW. **Personas:** zoom_out and implementation_readiness. **Reviewer:** claude-opus-5-5, read-only. I made no edits, provider calls, secret reads, worker or child-agent runs, or network calls. Every shell command was rtk-prefixed.

### Verdict: **PASS**. No blockers, no majors, 3 nits.

### Provenance checks (M1)
- **Tree matches.** `git rev-parse 302677f^{tree}` gives `72513d6c2260f10078503ee8f550b5f9218239e5`, which is the `tested_tree` in the suite JSON. The `tested_commit` is `302677faa677b6e0750b1a7034ce23a1ad091050`.
- **Current source is the tested source.** `git diff --stat 302677f cfa7d5d` touches only three files:
  - the new suite `.json`
  - the new suite `.log`
  - `docs/reports/router-shared-paid-spend.md`

  No code or test file changed after the tested commit.
- **No production code changed.** `git diff bfc292e..302677f -- factory/ tools/` is empty. The follow-up changes only tests and docs.
- **Log hash matches.** The SHA-256 of the log is `dad1dc3fbe1fb10a61fe3df7ba345b5c5692ed75fb10bf5695d0b21e99ef760d`, the same as `log_sha256` in the JSON.
- **Log content is consistent.**
  - It has 167 `== script ==` sections and ends with "167 test scripts run; 0 failed."
  - The `test_router_paid_spend.py` section reports "Ran 12 tests … OK". That is 11 earlier tests plus the new one, so the new test was in the run.
  - Lines matching "failed" are PASS-line descriptions only.
- **Flags are recorded.** The JSON has `clean_source_before_run: true` and `tracked_source_unchanged_after_run: true`. The worktree is clean now.
- **Old record is marked historical.** The report says the original source-unbound record is historical evidence only, and claims no provenance for it after the fact.

### Integration test checks (M2)
- **Real code paths run.** `test_worker_and_diagnosis_runtime_share_one_ledger_across_batches` drives the real `ModelRuntime.call`, which goes through `_invoke` and then `model_call_gate.enforce`. The Store is real SQLite, and `router._rpc` is patched to call `store.rpc` directly.
- **Only OS isolation and the CLI are doubles.** The doubles are `_wall_access`, `getpwnam`, `_quiet`, `run_budgeted` and `_opencode_flags`. The CLI double sends real local HTTP through the gate's listener (`self.post(kwargs['cancel'])`). Upstream is the existing `ProtocolTests` fake HTTPS, with `self.seen` counting connections.
- **The diagnosis call takes the real diagnosis path.** It uses `user='pilot'` and the name `diagnosis-synthetic`, so `_invoke` line 562 goes through `diagnosis_environment`.
- **The key assertions are real checks, not empty ones.**
  - The key comes from the patched `SECRETS` into `model_env`. `enforce` raises `credential_expiring` when there is no token, so a pass proves the key reached the gate.
  - The CLI env must also lack `OPENROUTER_API_KEY`, which proves the gate removed it.
  - The pilot-only checks are also asserted: the webfetch deny and the absence of EXA.
- **Batches and jobs are distinct.** Each call has its own batch, job, case and reservation_id.
  - Totals after each call: $0.23, then $0.46.
  - A third batch raises `ProviderWait`.
  - There are exactly 2 upstream connections and 2 distinct `lease_id`s in `paid_requests`.
  - This proves the allowance cannot be refilled per batch or per job.
- **Exactly one upstream connection.** `len(self.seen)-before == 1` was added to the successful wire test, in both the lost and normal branches.
- **I re-ran the test file myself.** `uv run --offline python -B tests/factory/test_router_paid_spend.py` gave "Ran 12 tests … OK", and the worktree stayed clean afterwards.

### Prerequisite check (M3)
- **Fixed.** The `/credits` check is now under the report's `## Deployment prerequisites` heading. It says the practice run must confirm the deployed key type and response schema, that authorization failures and rate limits fail closed, and that past funding observations do not count as that confirmation.

### N2 check
- **Fixed.** The stray `paid_protocol=1` field is gone from both synthetic provider responses (`test_model_call_maxima.py:756` and `test_router_cheap_maxima.py:43`).

### Nits
- **F1.** `tests/factory/test_router_paid_spend.py`, third-batch `assertRaises(router.ProviderWait)`: the test does not check the wait reason. A refusal for another reason, such as `binding` or `router_unavailable`, would also pass. Asserting the shared-paid reason would pin down that the allowance is what blocks the call. The money totals and `seen == 2` already cover the money safety, so this is only about what the test proves.
- **F2.** `docs/reports/router-shared-paid-spend.md:68-73`: the old "Full suite: 167 scripts, 0 failures" line and its link still come before the note that marks them historical. Readers who skim may treat the old record as the evidence. Putting the historical label on that line itself would fix it.
- **F3.** `docs/reports/router-shared-paid-spend.md:63`: one added line is much longer than the lines around it ("…newly deployed credential/endpoint contract. No credential was delivered"). It reads fine, but the wrapping doesn't match.

### Murphy rows
- This follow-up claims no rows closed, so there was nothing to verify.

## Elephant disposition

PASS, no blockers or majors. M1–M3 are independently verified closed by this fresh review. Optional F1–F3 are recorded for later: money safety and the shared runtime path are asserted, the report explicitly labels the old run historical, and wrapping has no behavioral effect. No code, tests or report changes follow this review; this commit only saves the review and disposition. No Murphy rows close.

