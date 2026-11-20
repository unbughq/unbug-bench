# Design review 1: queue-polling (goldfish, Mode: REVIEW, zoom_out + design_critic + implementation_readiness)

FAIL

All the factual claims I checked hold against the code and DBOS 3.4.0. Two gaps remain against the founder's hard requirements, and each needs only a small fix.

**Blocking**

1. **Work already queued on a missing row still waits forever with no error; change 2 only covers new enqueues.**
   - Evidence: when a queue's row is gone, its worker thread exits (`_queue.py:716-723`) and `queue_thread` never starts another until a row reappears (`_queue.py:907-930`). Recovery puts a PENDING slot or attempt back onto its own `queue_name` (`_sys_db.py:5457`). So an ENQUEUED workflow on a missing row sits there until some other workflow happens to enqueue onto the same queue.
   - Under the design's keep rules this cannot happen, so the founder's requirement holds only because the rules are right, not because anything checks it.
   - The planned test builds exactly this state. Case 2 of `b-u` is killed mid-run, so recovery re-enqueues its `slot_workflow` onto `steps-b-u`. The test then deletes `steps-b-u` before the reply. Case 2 is rescued only because case 1's `continue` enqueues and re-registers the row. Without case 1 the test would hang, so it checks the fix by accident.
   - Change: in `retire_finished_queues`, after the deletes, register every batch queue that a live workflow names (`queue_name`) and that has no row. Use the same `batch_queue` settings: admit 1, decision 1, steps `spec.max_concurrency` from that batch's spec, which retire already reads. That is about 3 lines and makes the requirement hold for recovered work too.
   - Restructure the test into two:
     - Delete `steps-b-u` while case 2 is ENQUEUED on it and no other case will enqueue. Assert that launch re-registers the row and case 2 seals.
     - Separately, delete the row while only an escalated case remains, so the reply's enqueue is the only path. That one tests change 2.

2. **No test checks that per-batch concurrency is unchanged after a re-register.**
   - The founder requires per-batch concurrency limits to stay the same. The change-2 test only checks that the attempt "registers it again and runs".
   - Change: after the re-register, assert the row's `global_concurrency` equals `spec.max_concurrency` for steps and 1 for admit, and that `polling_interval_sec == queue_poll_s`.
   - Also check that ADMITs stay serial after an `admit-*` re-register. The pattern is `Restart.test_queues_are_registered_before_recovered_admits_run` (`tests/factory/test_durable_engine.py:1206`).

**Verified (no change needed)**

- **Who enqueues onto a batch queue.** There are exactly three enqueue sites: `engine.py:1051-1053` (slot onto admit), `:1406-1408` (case onto steps) and `:2283` (V2 batch onto decision). No other module enqueues, resumes or forks. `board.py`, `observation.py`, `board_cleanup.py`, `admission_reasons.py` and `check-drained.py` only use `DBOSClient` reads.
- **Resumes reach live workflows only.**
  - `Engine.send`, `reply` and `resume_held` (`engine.py:2549-2595`) are all messages to running workflows.
  - `founder_stop_workflow` enqueues nothing.
  - `Runtime.start` refuses to attach to a finished batch before it calls `start_batch` (`runtime.py:452-454`).
  - `--resume-case` replays the old lineage's attempt IDs (`contract.py:272`, no batch id in the key). DBOS returns the existing workflows, whose `queue_name` is kept if they are still live.
- **A batch stays live while any case is unfinished.** `_Batch.run` loops on `has_pending_work`, which is `done < cases` (`engine.py:2131`, `:2158`).
- **Recovery.** Non-queued PENDING workflows go to the internal queue (`_recovery.py:26-28`), and queued ones keep their own queue. Both PENDING and ENQUEUED are kept by the design.
- **Launch cannot race `start_batch`.** `serve` calls `runtime.launch()` before it opens a plain, single-threaded `UnixStreamServer` (`cli.py:149-155`). `maintain_successor.py` and `backup.py` never launch an engine. The unit restarts with `KillMode=control-group`, so two controllers never overlap.
- **What DBOS does with deleted and re-registered rows.** The worker thread exits on its next reload (`_queue.py:716`). A re-registered row is picked up by `queue_thread` within 1 s because the old thread is dead (`_queue.py:921-930`). `register_queue` and `retrieve_queue` are not recorded steps (`_dbos.py:1245-1290`, `:1325`), so change 2 adds no replay steps on the normal path.
- **Listing failures fail safe.** Undecodable inputs come back as strings (`_serialization.py:462-472`), which is the design's "unreadable" case. A statement timeout on the listing raises (`_sys_db.py:1254`) and deletes nothing.
- **Rollback is safe.** The old `launch` re-registers live batches with `always_update`. Rows that are gone belong to batches with no live workflow.
- **Batch-id extraction.** `spec.batch_id` (batch and case) and `input.batch_id` (slot, attempt, prepared attempt, admission probe) cover all the enqueuers. `raise_bound_workflow` (`job["batch_id"]`, `engine.py:1136`) and `founder_stop_workflow` (no batch id) are not covered, but neither enqueues, and the V2 batch stays live while a raise is outstanding (`engine.py:2207`).

**Nits**

1. Use DBOS's whole active set (`PENDING`, `ENQUEUED`, `DELAYED`; `_sys_db.py:144-149`), not just PENDING and ENQUEUED. The factory never delays a workflow today, but this keeps the rule correct if that changes.
2. Pass `load_output=False` to the live listing.
3. Say that `raise_bound_workflow` and `founder_stop_workflow` carry no extractable batch id and why that is safe, so the "every workflow type" claim is accurate.
4. Name the source of the row list (`DBOS.list_queues()`, which is limited to this app) and the match rule (`admit-b-`, `steps-b-`, `decision-b-`).
5. The `QueuePolling` test runs the engine in an `EngineRun` subprocess. The design should name the harness hooks it needs: a scenario action that deletes a row, and a way to report `queue-worker-*` thread names from the child (for example, write `threading.enumerate()` to a file).
6. "Exits within about 2 s" does not hold under contention backoff, where the interval can grow to 120 s (`_queue.py:727`). Say "within one poll interval".
7. `Engine.start_batch` re-registers a finished batch's rows when called directly (`engine.py:2522`). It is harmless because `Runtime.start` refuses that first, but registering after the status check would be tidier.
8. `test_durable_prepared_attempt.py:67` and `test_durable_admission_queue.py:101` call `retrieve_queue(...).enqueue` directly. They call `DBOS.launch` rather than `Engine.launch`, so retire does not affect them; state that in the design.
9. Batches that finish mid-day are polled until the next restart (up to 24 h). That is acceptable, but give the expected rows per day at full parallelism (24 cases plus resumes) so the ceiling is concrete.

## Elephant's response

- B1 fixed: after the deletes, launch registers every `admit-`/`steps-`/`decision-` row a live workflow names and that has no row (`batch_queue`, steps at its live batch's `max_concurrency`, else 1). Test split: (a) restart test deletes `steps-b-u` in the database while case 2 is mid-attempt and checks the restart brings the row back and case 2 seals; (b) a separate action deletes `steps-b-u` while only the escalated case is left, then replies, so the enqueue site is the only path.
- B2 fixed: the test reads the re-registered rows' concurrency and polling interval and checks them against `register_queues` (steps = `max_concurrency`, admit 1, poll = `queue_poll_s`). ADMIT serial: covered by the concurrency 1 check on `admit-b-u`; the existing `Restart.test_queues_are_registered_before_recovered_admits_run` still runs through the new launch.
- Nits 1-6, 8, 9 taken into the design. Nit 7 not taken (unchanged behaviour, `Runtime.start` refuses first).
