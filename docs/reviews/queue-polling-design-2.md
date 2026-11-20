# Design review 2: queue-polling (goldfish, Mode: REVIEW, zoom_out + design_critic + implementation_readiness)

FAIL

Review 1 checked: B2 is resolved, because the restart test now reads back each row's concurrency and polling interval. B1 is resolved in the design text but not in the test that is supposed to prove it (finding 1). I checked all the factual claims below against the code and DBOS 3.4.0, and they hold:
- `retrieve_queue` reads the database row (`_dbos.py:1325-1334`), so "row missing" is detected correctly.
- A worker thread exits when its row is gone (`_queue.py:711-723`).
- `delete_queue` warns that pending work on a deleted queue cannot be recovered (`_dbos.py:1342-1346`).
- DBOS's active set is PENDING, ENQUEUED and DELAYED (`_sys_db.py:144-149`).
- The job shapes, the three enqueue sites, the order in which `serve` launches before opening the socket (`cli.py:149-155`, `runtime.py:296`), and the absence of any cancel, resume or fork call in the factory.

**Blocking**

1. **The restart test passes without the new B1 code.**
   - Evidence: `Engine.launch` already loops over every PENDING/ENQUEUED `batch_workflow` and re-registers its rows with `always_update` (`engine.py:2481-2487`). That loop runs before `retire_finished_queues`.
   - In the planned test, batch `b-u` is still live (case 1 is escalated). So the old loop puts `steps-b-u` back, and the test's "rows back with their settings" check passes with or without the new "register every row a live workflow names" pass.
   - The new pass only matters for two cases the old loop skips: an orphan queue name whose batch workflow has ended, and a batch whose input cannot be read (the loop's `except ... continue`). Only the pure-function test covers those. This is the same "checks the fix by accident" problem review 1 raised.
   - Change: delete the old loop and let `retire_finished_queues` be the only place launch registers rows:
     - every live batch's rows at its spec settings (admit 1, steps `max_concurrency`, decision 1, poll `queue_poll_s`);
     - orphan names at 1;
     - then the deletes.
   - With one code path, the restart test exercises the new code. The loop also stops leaving out DELAYED. This removes a path instead of adding one beside it.
   - If you keep the old loop, add a test on real DBOS where a workflow is ENQUEUED on a deleted row and no batch workflow is live, then check that launch registers the row and the workflow runs.

2. **A failed delete can skip the safety-net registration.**
   - The design says "a failure of the delete pass is logged and launch carries on". But missing rows are registered after the deletes. So a delete that raises (for example a Postgres statement timeout under the very load this change targets) skips the registration, and recovered work on a missing row waits forever with no error. The founder's requirement rules that out.
   - Change: register first, then delete. Make only the deletes best-effort. A failure to list workflows or to register a row should fail launch, as the current loop does.

**Nits**

1. **Thread-count check timing.** `DBOS.launch()` starts a worker thread for every row before `retire` deletes any. Those threads live until their next reload, at least one poll interval (`_queue.py:711`, `:731`). So `queues.json` must be written at least one poll interval after launch. Writing it at exit is fine; writing it at launch would make "no worker thread for `b-t`" flaky.
2. **Two batches in one database.** `EngineRun` runs one scenario per workdir (`test_durable_engine_fakes.py:819-826`), and the default batch is `b-t` (`:547`). The test needs `b-t` and then `b-u` in the same SQLite database: two `EngineRun`s sharing one workdir, with `spec.batch_id` overridden. Add this to the list of harness hooks.
3. **What test 2 actually shows.** When `steps-b-u` is deleted and an enqueue re-inserts it straight away, the old worker thread is usually still asleep in its poll wait. It reloads, finds the row and keeps going, so `queue_thread` never starts a new one (`_queue.py:913`). The test shows the row comes back and the work runs, not that DBOS starts a thread for a new row. Either word it that way or don't rely on the "within 1 s" claim there.
4. **Name the source of `max_concurrency`.** For the enqueue-site registration, state that the steps concurrency comes from `self.spec.max_concurrency` on `_Case`, which is the batch spec (`engine.py:1153-1154`, `:1927-1928`), and that `slot_workflow` only ever needs the admit value, 1.
5. **Prefix match.** The `-b-` prefix match never touches rows of batch ids that don't start with `b-`. That is safe, but say so.

## Elephant's response

- B1 fixed as proposed: the old launch loop is deleted. `Engine.settle_queues` (pure decision in `queue_plan`) is the only launch path: it registers every live batch's rows (from a live batch or case workflow's spec, `always_update`), then every batch row a live workflow sits on if missing, then deletes. The restart test therefore runs the new code; mutation checks: with the deletes off the test fails on the `b-t` rows, and with the enqueue site back on `retrieve_queue` it fails with case 1 `engine_error`.
- B2 fixed: registration first and unguarded (a failure fails launch); only the deletes are best-effort.
- Nits 1 (queues.json is written at exit), 2 (two `EngineRun`s on one workdir; `spec.batch_id` override already exists), 3, 4, 5 taken into the design text.
- The design was revised to revision 3 and implemented; the diff review checks it against the code.
