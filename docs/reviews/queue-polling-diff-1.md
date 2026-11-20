# Diff review 1: queue-polling (goldfish, Mode: REVIEW, zoom_out + implementation_readiness; also the re-check of design revision 3)

PASS

I found no blocking issues. Revision 3 of the design is sound, the code does what it says, and the blocking findings from both earlier reviews are resolved in the code as well as the design text:

- **Review 1, B1:** `settle_queues` registers every batch row that a live workflow sits on (`engine.py:2546`, `waiting`).
- **Review 1, B2:** the restart test reads back each row's concurrency and polling interval (`test_durable_engine.py:1285`).
- **Review 2, B1:** the old launch loop is deleted. `settle_queues` is now the only place launch registers rows, so the restart test runs the new code.
- **Review 2, B2:** rows are registered first, and a failure there fails launch (`engine.py:2539-2546`). Only the deletes are best effort (`:2547-2551`).

`QueuePolling` passes locally: 2 tests, 31.9 s.

What I checked against the code and DBOS 3.4.0:

- **Every workflow type and input shape in `queue_plan`** (`engine.py:161-189`):
  - Batch and case workflows have `job["spec"]["batch_id"]`.
  - Slot, attempt, prepared attempt and admission probe have `job["input"]["batch_id"]`, which is `StepInput.batch_id`.
  - `raise_bound_workflow` (`{"batch_id":…}`), `founder_stop_workflow` (`{"case":…}`) and DBOS's own temporary send workflows raise `KeyError` or `AttributeError`. That is caught, and none of them enqueue.
  - Every malformed shape raises one of the four caught exceptions: a string input, `None` input, empty args, `spec: None` or a non-dict spec.
- **Same scope for workflows and rows.** `list_workflows` and `list_queues` both filter to this app's name plus unclaimed rows (`_sys_db.py:1267-1273`, `:2996-3003`, `:6608-6627`). Neither filters by version, so the scopes match.
- **Launch ordering.** `DBOS.launch()` starts the recovery and `queue_thread` threads before `settle_queues` runs. That is harmless:
  - The listing is one query. Recovery only moves workflows between PENDING and ENQUEUED, and both are kept.
  - The only new workflows during launch are children of live workflows, which share their batch, so that batch's rows are kept.
  - A recovered case that enqueues before `settle_queues` reaches it gets its row from `batch_queue`.
  - Nothing else launches an `Engine`: `maintain_successor.py` and `campaign_controller.py` start nothing in the background, and `serve` opens the socket only after launch (`cli.py:149-151`).
- **Deleted and re-registered rows.** A worker thread exits on its next reload when its row is gone (`_queue.py:711-723`). If the row comes back first, the old thread carries on with it, and `queue_thread` never starts a second thread for a live one (`_queue.py:913`).
- **Replay.** `retrieve_queue` and `register_queue` are not recorded steps (`_dbos.py:1177-1334`), and the concurrency argument is deterministic: `self.spec.max_concurrency`, or 1. Settings match `register_queues` (`engine.py:2552-2559`).
- **Rollback.** Only rows of batches with no live workflow are deleted. The old code's `retrieve_queue` sites only run for live batches.
- **Other readers.** Nothing outside `engine.py` and the tests reads the `queues` table.
- **Harness hooks.** The `reply` change only adds an override; it falls back to `when["case"]` as before. Writing `queues.json` after `result.json` is the only other change.

**Blocking**

None.

**Nits**

1. **Removing the `waiting` registration (`engine.py:2545-2546`) leaves every test green.**
   - In the restart test, `b-u`'s batch workflow is live, so `register_queues` brings `steps-b-u` back through the specs path.
   - The orphan path ("recovered work sits on a missing row and no batch or case of it is live") is only checked in the pure `queue_plan` test.
   - It is unreachable in practice, because a case blocks on `get_result`. Still, either add one real-DBOS case (an orphan ENQUEUED attempt on a deleted `admit-` row, then relaunch), or stop saying in the design that this is "checked" end to end.
2. **`keep.add(w.queue_name)` (`engine.py:170`) is not proved by the pure test.**
   - Every workflow there that sits on a queue has a readable batch, so `keep.update(...)` keeps the row anyway.
   - Without that line, an attempt with an unreadable input would have its row registered by `waiting` and then deleted by `retire`.
   - Add `wf("attempt_workflow", "undecodable", "admit-b-x")` with `"admit-b-x"` in `names`, and assert the row is kept and in `waiting`.
3. **V2 paths are not exercised.**
   - The `queue_v2` OR at `engine.py:182` is untested: every pure-test spec has `queue_v2: False`.
   - The admit enqueue site (`:1098`) and the decision enqueue site (`:2330`) are never hit on a missing row.
   - V2 is off in production, so this is acceptable. Say so in the design's Tests section.
4. **A non-string `batch_id` crashes launch.** Something like a list in a spec record makes `specs[batch]` (`engine.py:182`) raise an unhashable `TypeError` outside the `try`. The old loop caught that through `ContractError`. Our own `to_record` never writes this, but an `isinstance(batch, str)` check inside the `try` would keep launch from crashing on a corrupt record.
5. **Unclosed SQLite connection in the test.** `with sqlite3.connect(...) as db` at `test_durable_engine.py:1261` commits but never closes, which causes the `ResourceWarning` in the test output. Use `contextlib.closing`.
6. **One case is not mentioned in the docstring or design.** The deletes run in a single `try` (`engine.py:2547-2551`), so one failed delete skips the rest until the next restart. That is acceptable as waste; one clause in the docstring would cover it.
7. **Docs referenced in `CLAUDE.md` are not on the branch.** `docs/ENGINEERING.md` and `docs/murphy-register.md` are missing. The design already says the Murphy row `new-queue-polling-1` will be added at merge; make sure it is added then and closed by `QueuePolling`.
8. **`origin/main` has moved on** (`d883a958`) and does not touch the queue code in `engine.py`. Merge it into the branch rather than force-pushing.

## Elephant's response

- Nit 1: design reworded: the orphan pass is proved by the `queue_plan` test, not end to end, and is unreachable today.
- Nit 2: added an unreadable attempt sitting on `admit-b-x`; the test asserts it is in `waiting` and not deleted.
- Nit 3: design Tests section says the V2 decision and admit enqueue sites on a missing row are not exercised.
- Nit 4: a non-string batch id raises inside the `try` (treated as unreadable); test case added.
- Nit 5: `contextlib.closing` in the new test.
- Nit 6: one clause in `settle_queues` (a failed delete leaves the rest to the next launch).
- Nit 7: noted for the merge; `docs/murphy-register.md` is not on main either.
- Nit 8: origin/main merged into the branch (no force-push).
- `QueuePolling` rerun after the nits: 2 tests OK. Full suite run on the final head.
