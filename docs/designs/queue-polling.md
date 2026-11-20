# Stop polling the queues of finished batches

Founder, 2026-11-20: approved fixing the controller's queue polling ("take your recommendations"),
from the control-plane investigation of 11-19/20.

## Problem

- The campaign controller (`unbug-durable-case-campaign`, one `Engine` in `factory/durable/runtime.py`)
  uses about 0.9 of the control VM's 2 cores and runs 390 to 410 threads. Postgres sees about 670
  transactions a second. This starves the model router and kills paid model calls.
- Cause, in DBOS 3.4.0 (`dbos/_queue.py`):
  - `queue_thread()` lists every row of the `queues` table once a second and keeps one
    `queue_worker_thread` per row.
  - Each worker thread reloads its row (`get_queue`) and polls for work every
    `polling_interval_sec` (ours: `Timing.queue_poll_s = 1.0`), forever.
  - A worker thread stops only when its row is gone: "Queue ... no longer exists in database,
    stopping worker".
- `Engine.register_queues` writes 2 rows per batch (`admit-<batch>`, `steps-<batch>`; plus
  `decision-<batch>` for a V2 batch). Nothing ever deletes them. The VM's database holds 370 rows;
  8 have work.
- `Engine.launch` already registers only the queues of unfinished batches, but that does not help:
  the old rows are still in the table, and DBOS polls every row.

## Who enqueues onto a batch queue

Only the batch's own workflows, and only while they run:

| Queue | Enqueued by | Code |
|---|---|---|
| `steps-<batch>` | the case workflow, each attempt (`slot_workflow`) | `_Case.run_seq`, `queue.enqueue(slot_workflow, job)` |
| `admit-<batch>` | `slot_workflow` of an ADMIT attempt (`attempt_workflow`) | `slot_workflow` |
| `decision-<batch>` | the V2 batch workflow (`admission_probe_workflow`); V2 is off in production | `_BatchV2` |

- Case workflows are started by their batch workflow (`DBOS.start_workflow`), not on a queue.
- On a restart DBOS recovery re-enqueues a PENDING queued workflow onto **its own queue**
  (`reenqueue_for_recovery`: `queue_name = coalesce(queue_name, internal)`). So a row must stay while
  any PENDING or ENQUEUED workflow names it, or that workflow waits forever, silently.
- Resumes (`founder_reply continue`, `resume_held`, `plumbing_release`, `bench_release`,
  `bound_raised`) are messages to a **running** batch or case workflow. A held, escalated or waiting
  case is a PENDING workflow, and so is its batch (`_Batch.run` loops until every case reported done).
- A `--resume-case` resume starts a **new** batch id; `Engine.start_batch` registers its queues before
  starting it. Attaching to an existing batch id also re-registers first.

## Change

1. **One launch pass registers live rows, then deletes finished ones.** `Engine.settle_queues()`
   replaces the registration loop at the end of `Engine.launch()` (after `DBOS.launch()`), so launch has
   one queue path and every restart runs it. The decision is a pure function,
   `queue_plan(names, live)`, so it can be tested on its own.
   - Read every active workflow: `DBOS.list_workflows(status=["PENDING", "ENQUEUED", "DELAYED"],
     load_output=False)` (DBOS's own active set; the factory never delays a workflow today), and this
     application's rows (`DBOS.list_queues()`).
   - Keep the `queue_name` of every live workflow.
   - Keep all three queue names of every batch any of them belongs to. The batch id is in the job:
     `job["spec"]["batch_id"]` (batch and case workflows) or `job["input"]["batch_id"]` (slot,
     attempt, prepared attempt, admission probe). `raise_bound_workflow` and `founder_stop_workflow`
     carry no batch id this way; neither enqueues, so only their own `queue_name` (none) matters.
   - **Register first.** Every live batch's rows from its spec, through `register_queues`
     (`always_update`, as the old loop did), now from a live case workflow's spec too, not only a live
     batch workflow's. Then every `admit-b-`/`steps-b-`/`decision-b-` row a live workflow sits on, if
     missing (`batch_queue` below; steps at its live batch's `spec.max_concurrency`, otherwise 1, for an
     orphan whose batch and case have ended; 1 never exceeds a batch's limit). DBOS recovery re-enqueues
     a PENDING queued workflow onto its own queue, and a missing row would leave it waiting forever with
     no error, so launch checks it rather than relying on the keep rules alone. (For a live batch,
     `register_queues` already covers it; the extra pass matters only for an orphan, which cannot arise
     today because a case blocks on its attempt's result. It is proved by the `queue_plan` test, not end
     to end.) A failure here fails launch, as the old loop did.
   - **Then delete** (`DBOS.delete_queue`) every row named `admit-b-`, `steps-b-` or `decision-b-`
     that is not kept. Other rows (DBOS's own, batch ids that do not start `b-`, anything else) are
     never touched. If a live `batch_workflow`, `case_workflow` or `slot_workflow` (the enqueuers) has
     no readable batch id (DBOS hands back an undecodable input as a string), delete nothing. A failure
     of the deletes is logged and launch carries on: polling waste must never stop the controller.
   - Each deleted row's worker thread sees its row gone at its next poll and exits (one poll interval:
     1 s, more under DBOS's contention backoff). The threads DBOS started at launch for those rows live
     that long.
2. **Register a missing queue at the enqueue site.** The three enqueue sites get the queue through a
   new `batch_queue(name, concurrency)`: `DBOS.retrieve_queue(name)`, or, if the row is missing,
   `DBOS.register_queue(name, global_concurrency=concurrency, polling_interval_sec=queue_poll_s,
   on_conflict="never_update")` with the same concurrency `register_queues` uses (admit 1, steps
   `spec.max_concurrency` from `_Case.spec`, the batch spec; decision 1; `slot_workflow` only needs
   admit). If the deleted row's worker thread has not yet woken, it reloads the new row and carries on;
   otherwise DBOS's queue manager starts one within 1 s. `register_queue` and `retrieve_queue` are not recorded steps, so replay is unchanged.
   - Today an enqueue onto a missing row raises `AttributeError` (`None.enqueue`) inside the case
     workflow. With this, it works.
   - `tests/factory/test_durable_prepared_attempt.py` and `test_durable_admission_queue.py` call
     `DBOS.launch` and `retrieve_queue(...).enqueue` directly, not `Engine.launch`; they are unaffected.

Why at launch only: the operator socket is served by one thread, and `launch()` runs before the socket
opens, so no `start_batch` can register a new batch's rows between the read and the deletes. The
service restarts at least daily (`RuntimeMaxSec=86400`) and on every deploy.
`ponytail:` rows of batches that finish while the controller runs are polled until the next restart;
call `settle_queues` periodically if a day's batches ever matter. At full parallelism (24
cases, each started, resumed or imported as its own batch, a few times a day) that is at most about
100 to 150 rows by the end of a day, against 370 today and growing.

Rejected:
- `DBOS.listen_queues`: it must be called once, before launch, so a batch created later is never
  polled without touching DBOS internals.
- Shared fixed queues: concurrency is per batch (`steps` = `spec.max_concurrency`, `admit` = 1 per
  batch). Partitioned queues could keep that, but every enqueue would change and workflows recorded on
  the old queue names would replay onto new ones. A much bigger change.
- Raising `queue_poll_s`: keeps 370 threads, and finished batches keep their stored 1 s.

## Why nothing is lost or stranded

- A batch with any live workflow keeps all its rows. That covers an escalated, held, waiting or
  backing-off case, a case waiting for a release, and a case mid-attempt when the controller died.
- A row any live workflow names (as its queue) is kept, even for a batch that is otherwise finished, so
  a recovered PENDING workflow is always dequeued.
- After the deletes, a batch with no live workflow cannot enqueue: its batch workflow and every case
  have ended, and the factory never calls `DBOS.resume_workflow` or `fork_workflow`. If one ever
  enqueues anyway, change 2 registers the queue again.
- Messages to an ended case or batch already do nothing today.
- Concurrency limits and worker slots are unchanged: rows of live batches keep their settings, and a
  re-registered row gets the same settings `register_queues` writes.
- Restart with work in flight: launch runs the same rules on the recovered state. Recovery only moves
  live workflows between PENDING and ENQUEUED, and both are kept.
- Rollback to the old code: the old launch registers live batches' rows (they still exist), and the
  only rows that are gone belong to batches nothing can enqueue onto.

## What it deletes

About 360 of the 370 rows on the VM's first launch, and with them about 360 polling threads and about
650 Postgres transactions a second. No code paths are deleted.

## Tests

In `tests/factory/test_durable_engine.py`, class `QueuePolling` (real DBOS 3.4.0, the engine fakes):
- **Restart with work in flight.** A finished batch (`b-t`, sealed). Then batch `b-u`, killed (SIGKILL)
  with case 1 escalated and case 2 mid-attempt; the `steps-b-u` row is then deleted in the database.
  The restart has no `admit-b-t`/`steps-b-t` row and no worker thread for them, has `b-u`'s rows back
  with their settings (steps concurrency = `max_concurrency`, admit 1, poll = `queue_poll_s`), and
  case 2 finishes.
- **Enqueue site (change 2).** In the same restart, once case 2 has sealed and only the escalated case 1
  is left, an action deletes `steps-b-u` and then replies `continue` to case 1. Its next attempt
  registers the row again with the same settings and runs, and case 1 seals.
- `queue_plan` on rows shaped like `DBOS.list_workflows` output: an orphan ENQUEUED attempt keeps
  its queue and a missing row of it is registered at concurrency 1, a live case keeps its batch's rows
  when the batch workflow has ended, an unreadable enqueuer deletes nothing, and other rows are
  untouched.
- Not exercised: the V2 decision queue and the admit enqueue site on a missing row. V2 is off in
  production; `batch_queue` is the same call at all three sites.
- Every existing engine test now runs through `settle_queues` at each launch, including the
  kill-and-restart ones (`Restart.test_queues_are_registered_before_recovered_admits_run` checks ADMITs
  stay serial after a restart).
- Harness hooks in `tests/factory/test_durable_engine_fakes.py`: an action `delete_queue` (deletes a row
  through `DBOS.delete_queue`), a `case` field on `reply` (reply to another case than the trigger's),
  and `queues.json` written next to `result.json` with the live `queue-worker-*` thread names and each
  row's concurrency and polling interval.

Checked by mutation: with the enqueue site back on `retrieve_queue`, the restart test ends with case 1
`engine_error` (the `AttributeError` above, not a hang); with the deletes off, it fails on the `b-t`
rows.

Measurement (local Postgres 14, DBOS 3.4.0, `Timing()` defaults, the same database set up with 366
rows of 183 finished batches plus 4 live batches holding a PENDING workflow each, 8 rows; 20 s window
after a 6 s settle; script in the PR description):

| | queue rows | `queue-worker-*` threads | all threads | queue reloads/s | Postgres tx/s | controller CPU (cores) |
|---|---|---|---|---|---|---|
| before (old launch loop) | 374 | 375 | 386 | 258 | 1,046 | 1.09 |
| after (`settle_queues`) | 8 | 9 | 20 | 8 | 45 | 0.04 |

The 8 live rows are kept in both. Before, 374 threads managed only 258 reloads a second of the 374 due:
the GIL, not the database, was the limit.

## Murphy rows

`docs/murphy-register.md` is not on this branch (removed with the docs archive). New row to add at
merge, `new-queue-polling-1`: "Controller polls every queue ever registered; CPU and Postgres load
grow with every batch and starve the router." Closed by `QueuePolling` in
`tests/factory/test_durable_engine.py`.

## Deploy

New code reaches the controller only with a restart: drain the router (no model calls in flight),
`sudo systemctl restart unbug-durable-case-campaign`, then check the thread count and the `queues`
row count.
