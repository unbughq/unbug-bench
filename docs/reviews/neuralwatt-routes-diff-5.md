# Diff review 5: neuralwatt-routes rollback confirm on c10a109a (goldfish)

**Verdict: FAIL.** (a) closed, (b) not closed.

- **(a) Closed.** Rollback step 1 changes only what new acquires get (`workers.py:557`, `:572`; `executor.py:94` acquires once per step). The lane stays enabled until step 3, so a step still holding the key can lease what it offers. A new step re-acquires, wipes and re-delivers `/dev/shm/secrets`, and builds a fresh `Ctx`, so "wait until every live case has started a new step" is enough.
- **(b) Blocking: deleting the state file does nothing.** `ordinary-retries` is in `SNAPSHOT_RETAINED` (`run.py:3207`), and every step starts with `worker_step.restore(snapshot, work)` (`worker_step.py:729-739`), which brings the file back. The first new step after key removal fails `ordinary_retry_state_invalid` (`ordinary_retry.py:128-130`), booked as infra (`classify.py:112`), on every retry. Fix in code: check `spent_routes` against `model_router.routes(models[0], model_router.ACCOUNTS)`; spending stays bounded by `approved`. Test: a state with an NW route in `spent_routes`, under a context without the key, must not raise.
- **Nit:** SIGTERM must target the forked attempt child, not the `supervise` parent (`worker_step.py:470-471`).
- **Nit:** a helper sent during the wait copies the parent's `router_accounts` (`helper_link.py:213`), key included, onto a box without it. Say so in the doc, or keep helpers off during the wait.
- The step 6 gate wording now reads correctly.

## Elephant response (2026-11-19)

- **(b):** fixed in code as specified (`factory/ordinary_retry.py`), with `test_a_spent_neuralwatt_route_survives_the_key_being_withdrawn` in `tests/factory/test_stream_d_retries.py`. The test fails with `ordinary_retry_state_invalid` without the fix and passes with it. Rollback step 4 now says there is nothing to clean up.
- **Nits:** both taken in rollback step 2.
