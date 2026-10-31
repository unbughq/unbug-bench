**PASS** — no blocking finding. The addendum fixes M1 correctly and the
publication replay is safe. Two majors remain (one a real but narrow safety gap
in the lost-exit predicate, one an underspecified status data path), plus nits.
All are fixable before activation, none gates the increment's own merge.

## Majors

**M1. The "known ceiling" names the benign gap, not the real residual; the
predicate can mark `failed` while a worker still exists.** (addendum "Lost
dispatch exit", vs. `factory/batch_holder.py:296-307`,
`bin/boat-launch-guards.sh:70-97`). The design's claimed ceiling — a dispatch
child killed in the microseconds between `control_resume`'s `mkdir` and its
`launch.json` write stays pending — is fail-closed and harmless. The actual
window the design does not name is the one where a worker is created but its
`new.N` creation record is not yet written: if that signature (`launch.json`
present, `controller.lock` free, no `new.*`, empty `ids`) is reached, the
predicate marks `failed`, which frees the concurrency slot and lets a successor
launch — two workers on one case against one committed hold. The `controller.lock`
check fences the single-kill case, so this needs both the dispatch parent and
the controller dead in that window — narrow but nonzero, and it is the one
money-safety property this predicate exists to prove. Fix: either cross-check
the live Boat inventory for a worker owned by this launch before marking
`failed`, or require `new.*.pending` absent, and document the real residual
instead of the benign one.

**M2. The "flag failed operations" and "active ignores failed operations"
requirements are in tension and the data path is unspecified** (`batch_status.py:227-244`,
addendum "Terminal dispositions are visible"). `read_rows` selects its row from
`active = [o for o in operations if o['retirement'] is None]`. A failed
operation has `retirement is None` and `output_generation is None`. If failed
ops are removed from `active`, then for a job with a prior collected entry the
fallback lookup (output matches entry) cannot match a failed op, so `selected`
is `None` and the row renders as the stale `stopped` card — the `launch failed`
flag never appears, silently hiding the dead case and defeating stated goal #3.
The design must say how the terminal operation's `incident` reaches `render`
when it is excluded from `active`: keep a separate selection for the terminal
op, or scope "ignore failed ops" to the uniqueness check only, not to selection.

**M3. New schema fields and incident labels aren't wired into the hard
validator** (addendum "Bounded holder retries"/"Terminal dispositions", vs.
`batch_holder.py:28-31, 66`). The journal grammar enforces `set(op) != FIELDS`
and a closed `incident` whitelist. Adding `failures` and the
`resume_failed`/`publication_failed` labels makes every `validate_operations`
call raise `invalid batch operations` until `FIELDS` and the whitelist are
extended. State this as an explicit change; the shared validator that
`batch_service` imports is the single place to change, and the money-state
accounting-incident reasons are a separate set that must not gain these labels.

## Nits

- **N1.** "waits `60 * 2**(failures-1)` (60, 120, 240, 480 s)" lists four waits
  for `RETRY_LIMIT = 5`. The fifth failure only terminates; state that it sets
  the incident without a sixth wait.
- **N2.** `failures` is never reset on a later success. Harmless for one
  case/one worker, but a resume that flapped then succeeded then flapped again
  would be one flap from terminal. A one-line note or a reset is enough.
- **N3.** The `publish` child decrypts the full secrets file to read four `R2_*`
  lines. `dispatch` zeroes its key buffer on the way out; require the same for
  the publish child since it now holds live R2 credentials.
- **N4.** `record_child` must not double-count or clash with `record_exit` for
  dispatch: confirm dispatch children keep going through `record_exit` only.

## What holds

- **Bounded retries are correct.** `failures` is durable, the backoff is
  bounded exponential, `orphaned()` and the publication scan skip terminal
  labels, and a free operation lock for a resume leaves it pending, not counted.
- **Lost-dispatch-exit predicate is mostly safe.** `dispatch` holds the
  operation lock synchronously until `launch.sh` exits, so a free lock proves
  the dispatch child is gone; `control_resume`'s `mkdir` is a real fence; the
  benign gap fails pending, which is correct.
- **Publication replay is race-free.** `complete` is only written after all
  workers are deleted and collection has finished, so `unpublished`'s
  `complete` + scorecard conjunction cannot race `collect.sh`; replay reuses the
  idempotent `collect`, which re-verifies the frozen bytes.
- **Trusted closure is complete.** `budget.py` and `diagnosis.py` plus their
  already-pinned local imports cover the publication import path.
- **Deferred prerequisites are acceptable for a one-case practice run.**
  Per-reason retry identities, `new-batch-service-3` (unreachable with
  `DIAGNOSIS_ENABLED=False`) and retired-without-output disposition all defer
  without risking money loss or double-scoring.

Skipped: I did not run the suite or measure the kill-window timing; M1's
severity is an analytical argument. If you accept M1 as-is, comment the real
residual rather than shipping the benign ceiling text.

---

Reviewer: goldfish, OpenCode `openrouter/~deepseek/deepseek-pro-latest`, design review 1 (activation readiness addendum), 2026-10-30.
