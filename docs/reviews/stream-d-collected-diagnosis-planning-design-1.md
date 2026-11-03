**Verdict: NOT PASS.** This was design round 1 of 2, read-only, on worktree `t3-21bef30c` at HEAD `8baa7a0`. One blocker and three majors are open.

Before reviewing, I read the three persona files, `docs/ENGINEERING.md`, both standards, the opt-in design, B's `pilot-run.md` (via `git show`), and the code in `factory/batch_service.py`, `factory/batch_holder.py`, `factory/key_holder.py`, `factory/batch_money.py`, `tests/factory/test_batch_holder.py`, `tests/factory/test_batch_service.py` and `tests/run.py`.

## What holds
- **Smallest seam:** adding one more scan inside `key_holder.batch_tick` (`key_holder.py:463-467`) with action `None` and a `[]` return matches the existing `schedule_waits` pattern. The existing per-scan `try` already catches a top-level failure.
- **No other callers:** `batch_service.plan` has no other production caller (grep found none). The keyword-only `published_operation=None` keeps the old local contract.
- **Lock reuse is sound:** checking inside plan's own `batch_money.locked` avoids nesting the lock (`flock` on a second open of the same file in one process would block forever) and avoids a check-then-unlock-then-write race. `_source`, `_config`, `_operations` and `money.load_locked` take no lock, so the helper can call them while holding it.
- **Replay:** the facts and queue rows are written together in one atomic `journal.json` write, so a lost reply or a restart replays safely. Using `operation_id(policy, job, output_generation)` as the "source already consumed" check is correct and matches `schedule_waits:486`.
- **Default-off holds:** `HOLDER_ENABLED=False`, `practice.active` needs its environment variable, and no `factory/batches/*` manifest contains `diagnosis_policy`. There is no launch, reserve, dispatch, pilot admission or Boat settlement work, and B's plan rules out replacements.
- **No Murphy row closes:** saying row 9 stays open is correct.

## Findings

**1. Blocker: refused candidates re-verify full archives every tick while holding the shared money lock.**
- **Where:** design lines 32–37 and 72–77, `batch_service.py:328-345`, `key_holder.py:580-583`.
- **Evidence:**
  - `batch_tick` runs about once a second, because `server.settimeout(1)` sets the loop's pace.
  - The cheap scan selects any entry whose facts are still `None`, and the design says to retry refusals while facts stay `None`.
  - Some outcomes never set facts:
    - `retire_legacy` returns `retired` with `facts=None` (`batch_service.py:334-335`).
    - A projection refusal never sets facts.
    - A damaged snapshot never sets facts.
  - Each of those tick runs hashes every archive in `_snapshot` while holding the money lock. That blocks collect, reserve and reconcile.
  - The successful path hashes twice: once in plan's existing `_snapshot`, then again in the helper's `_source` → `_entry` → `_snapshot`.
  - `schedule_waits` was built specifically to avoid this ("never hash a future wait's archives each tick", `batch_holder.py:490`).
- **Exact fix:**
  - (a) The cheap pre-lock scan also skips when the successor `operation_id(policy, job, output_generation)` already exists in the operations (copy `batch_holder.py:486`).
  - (b) It also skips when `retirements/<case>/<generation>.json` exists.
  - (c) When `published_operation` is given, run the helper before plan's `_snapshot` and reuse the card that `_source` returns. Do not call `_snapshot` a second time.
  - (d) For snapshot or projection failures that never clear, either add an in-memory per-`case/generation` backoff in the holder process (not durable, so it adds no latch), or state that the cost is accepted and bound it with a test. Add a test that counts `_snapshot` calls across repeated ticks for a legacy-retired candidate and for a refused one.

**2. Major: the new tick scan breaks an existing test, and the design doesn't say how to resolve it.**
- **Where:** `tests/factory/test_batch_holder.py:886-900`, `test_tick_future_due_restart_and_single_successor`.
- **Evidence:** the test asserts `service._snapshot.assert_not_called()` across two real `batch_tick` calls. Its fixture record has `diagnosis_policy` enabled (`test_batch_service.py:44`), and the waiting operation is launched, ACKed and retired with no successor. With planning in the tick, the first tick calls `_snapshot`, so the test fails. The design requires the full suite to pass but leaves this choice to the implementer.
- **Exact fix:** state the decision. Recommended: in `WaitSchedulingTests`, either set `diagnosis_policy` to false for no-hash wait assertions, or change the assertion to "exactly one planning verification per generation, zero on later ticks". Also name `test_batch_tick_never_stops_and_records_only_dispatch_exits` and `test_batch_tick_survives_real_corrupt_money` as tests to re-check.

**3. Major: the midterm exam's expected queue result isn't defined for the current fixtures.**
- **Where:** design lines 28–29 and 108–111, `batch_service.py:264-292`, `test_batch_service.py:63-71` and `79`.
- **Evidence:**
  - `HolderTests.output()` writes a card with a known total, and `self.answers()` defaults to `pending=None`. With those inputs `_enqueue` writes facts but no resume row, so the "expected resume key" doesn't exist.
  - The fixture also has `replacement_policy` enabled, so an eligible projection also writes a derivation and a `replacement/<case>` row. The design never mentions those.
  - `input()` sets `diagnosis_state={}` with the comment "Authored provenance for contract-only API doubles". So "real projection where compatible" is undecided.
- **Exact fix:**
  - Name the projection inputs for the midterm. For example, use `self.answers(pending={'schema_version':1,'status':'pending','replacement_eligible':False})` via `patch.dict(sys.modules, diagnosis=...)`, labelled as an API double, and expect exactly `resume/<case>/<generation>`.
  - State that replacement rows and derivations are existing plan behaviour, gated by `replacement_policy`. Assert them explicitly when that policy is enabled, or disable it for this file's fixture. The pilot proposes no replacements.
  - State that the queue drain in the next increment consumes only resume rows.

**4. Major: the deadlock check depends on a timeout that doesn't exist.**
- **Where:** design lines 123–124, `tests/run.py:31`.
- **Evidence:** `run.py` calls `subprocess.run` with no timeout. Re-acquiring the lock in the same process blocks forever, so a regression would hang the suite instead of failing it.
- **Exact fix:** add a direct test. Patch `batch_money.locked` with a depth-counting wrapper and assert the maximum depth is 1 during `plan(..., published_operation=...)` and `plan_collections`. Optionally also run the case in a child process with an explicit `timeout=`.

**5. Nit: the helper re-implements checks `_post` already has.**
- **Where:** design steps 1–4.
- **Evidence:** `_post` (`batch_holder.py:169-187`) already checks export, incidents, the aggregate bound, the deadline, overrun, `row.authority == op.authority`, `row.sources[-1] == op.source_generation` and `_config`. `locked()` already refuses `export.json` (`batch_money.py:160`).
- **Exact fix:** extract that common prefix of `_post` into one shared function used by both, so the two checks can't drift apart. Do not call `_post` itself: it also re-checks the input source, which costs another snapshot hash.

**6. Nit: the helper signature is missing `root`.**
- **Where:** design line 49.
- **Evidence:** step 1 needs the holder-enabled check, and `enabled(policy, root)` → `practice.active(policy, root)` takes `root`.
- **Exact fix:** add `root` to `_planning_source`.

**7. Nit: test fixture borrowing needs a named mechanism.**
- **Where:** design lines 100–102.
- **Exact fix:** say the new file uses the existing `WaitSchedulingTests` pattern: `locals().update({k: v for k, v in vars(HolderTests).items() if not k.startswith(('test_', '__'))})` (`test_batch_holder.py:855`).

## Skipped checks
- I ran no tests, as instructed.
- I did not measure real archive sizes, so the per-tick hashing cost in finding 1 is not quantified.
- I did not check whether the real `diagnosis` predicates give an exhaustion or pending result on the e15450 ledger card.
- I did not review the imported-only path (`batch_transfer.source`) beyond confirming the design leaves it out.
- I did not re-review the opt-in increment, and made no edits, record, delegation or network calls.

## Elephant disposition

All findings accepted. Revision 2 specifies consumed/retired skips, one snapshot,
60-second process-local refusal backoff, explicit fixture projections and policy,
a depth-counting lock test, shared _post prefix, root parameter and helper borrowing.
Fresh final design review required before implementation.

