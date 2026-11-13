**FAIL**

1. **BLOCKING — [factory/run.py:3011](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/run.py:3011):** GATES still partitions its grant at a fixed $50. A resumed batch with $45 of case money and a fully funded $195 GATES grant reserves only $145 for G10, leaving $50 available to ordinary calls. If the lineage previously spent $50, ordinary spending can reach $100 despite a $95 ceiling. Carry the actual remaining case allowance to the worker for grant-bearing workflows, preserving old recorded inputs, and test full and partial GATES grants.

2. **BLOCKING — [factory/durable/engine.py:513](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/durable/engine.py:513):** Grant lookup reads only case workflows. An accepted resume batch whose deadline expires before it creates its case workflow has the grant in its batch input, but later resumes cannot find it and the board has no grant card. Persist and retrieve grants from an authoritative lineage record that includes accepted batches which never start a case.

3. **BLOCKING — [factory/durable/runtime.py:372](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/durable/runtime.py:372):** Retrying a pending batch adds its recorded grant again before attaching. For example, retrying a $110 grant is rejected as a $220 total. Conversely, supplying a new grant for an existing pending batch can return success while `Engine.start_batch` simply attaches and discards it. Check the existing batch first: accept an identical retry without adding again, and reject conflicting grant inputs.

4. **BLOCKING — [tests/factory/test_durable_runtime.py:353](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/tests/factory/test_durable_runtime.py:353):** The spending test mocks the engine and sets the batch bound to only 100 micro-USD. The engine test uses scripted results, and the board test injects a card. Together they do not prove that a lineage can actually spend its grant, that another lineage remains capped, or that pre-change DBOS histories replay with unchanged steps and inputs. Add an end-to-end regression using the real ledger and durable workflows, plus recovery of a history recorded at `c9e6b255`.

5. **NIT — [factory/durable/engine.py:502](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/durable/engine.py:502):** The length check measures the stripped reason but stores the original, so `"x" + " " * 201` passes the promised 200-character limit. Check the stored length separately, or normalize before validating and recording.

6. **NIT — [factory/durable/cli.py:240](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/durable/cli.py:240):** Invalid amounts and cumulative grant overflow reach the controller, but both socket error mappings turn `case_money_extra_invalid` into `operator_request_failed`. Allowlist the documented safe code through both mappings and test a controller-side rejection through the CLI.

7. **NIT — [factory/durable/board.py:387](/Users/bugsincode/Developer/unbug-bench/.claude/worktrees/agent-ab98aa6b464140ac9/factory/durable/board.py:387):** The text board rounds grants to cents, so a valid one-micro-USD grant appears as `+$0.00`. Display grant amounts with enough precision to represent the recorded value.

This was a static review. Tests were not run because the requested read-only mode prohibits their temporary-file writes.
---

## Resolution (elephant)

- **1 (G10 reserve split at a fixed $50): rejected; second goldfish (Claude, other family) agreed.**
  The $50 stand-in predates this change. It applies to every resume batch whose case money is
  below $50, with or without a grant. The grant changes neither the per-batch `case_limit` nor this
  split. Fixing it needs a new `StepInput` field and a worker release, so it should get its own
  Murphy row.
- **2 (grant read only from case workflows): rejected; second goldfish agreed.** The failure is
  safe: the ceiling falls back and the founder grants again. It uses the same source as
  `Runtime.start`'s `resumed` spend and the role-swap lineage. A batch that never started its case
  spent no case money.
- **3 (retry double count / dropped grant): fixed.** `Runtime.start` reads the lineage without the
  batch's own workflow (`exclude=<case>@<batch>`). A retried start keeps the grant its batch
  recorded and refuses a different one. Covered by the retry part of
  `test_extra_case_money_raises_one_lineage_ceiling`.
- **4 (end-to-end ledger and replay test): rejected; second goldfish agreed.** Engine and ledger
  enforcement is unchanged code. The admission check is tested against a real `SqlLedger`. Old
  records carry no new key, so their replay is unchanged by construction. The full engine file
  passed on this change: 151 tests, 1 error from an ordering slip, fixed and rerun.
- **5 (reason length): fixed.** The length check now uses the unstripped reason.
- **6, 7 (nits): not taken.** Every controller-side refusal maps to `operator_request_failed`
  today, `resume_money` included. Grants are whole dollars in practice.
