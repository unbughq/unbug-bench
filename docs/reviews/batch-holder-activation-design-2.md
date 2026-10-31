**PASS** — no blockers. All three design-1 majors are genuinely resolved, and
I verified each resolution against the source. The two reconciliation decisions
(publish child holds its operation lock; the ~15-minute R2 ceiling) are safe
and money-safe. Nothing here blocks the one-case live practice run;
`HOLDER_ENABLED` stays `False`, so this increment spends no money.

## Blockers

None.

## Majors

None. The one finding that was close to a major — a lock-order inversion
introduced by the new lost-exit probe — is deadlock-free by construction, so it
is a nit (N1).

## Nits

- **N1. The lost-exit probe inverts the lock order and is safe only because it
  is nonblocking.** `dispatch`, `resume`, `record_exit` and the new `publish`
  child all take `operations/<id>.lock` and then `money.locked`
  (`factory/batch_holder.py:534`→`:541`, `:244`). `reconcile` holds
  `money.locked` and then, inside `_reconcile_one`, probes
  `operations/<id>.lock` (the new design). That is the opposite order. It cannot
  deadlock only because the probe is `LOCK_NB` (`:236`): a busy lock means a
  live owner, so reconcile skips and the operation stays pending. Keep the probe
  nonblocking and never hold `money.locked` while blocking on an operation lock.
  A publish child running `reconcile` on its own launched op never reaches the
  probe (worker_id is set, so `_reconcile_one` returns at `:297`), so there is
  no self-conflict.
- **N2. Old reservations without `failures` are rejected.** Adding `failures`
  to `FIELDS` makes `validate_operations` reject any pre-increment
  `reservations.json` (`set(op) != FIELDS`, `:50`). That is acceptable because
  the gate was off before this increment and activation uses a fresh batch with
  a new policy; state it so nobody expects an in-place upgrade of an old batch.
- **N3. The publish-pending window shows a gone worker.** A chain head that is
  launched, output null, not yet retired, with `complete` present but the
  worker already deleted, maps to `running`; `observe`/`render` then flags
  `worker gone` (`factory/batch_status.py:114`) until `reconcile` records
  retirement. Cosmetic, brief, and not money-unsafe.
- **N4. Confirm the publish wiring and the TRUSTED_FILES closure.** The publish
  entry must call `collect()` directly with the identity buffer and the four
  `R2_*` values in its own environment, not the `main` `collect` subcommand,
  which reads `UNBUG_LAUNCH_STATE` and is meant for `collect.sh`
  (`factory/batch_holder.py:617-623`). And confirm `diagnosis.py` is actually on
  the publication import path before pinning it; adding a non-imported file to
  `TRUSTED_FILES` only changes the fingerprint, so this is harmless either way.

## What holds

- **Design-1 M1 is verified true and the window is closed.** `guard_new` runs
  the creator as `( ... boat new ... ) > "$state/new.$serial"`
  (`bin/boat-launch-guards.sh:75`); the subshell's `>` redirect creates and
  truncates `new.$serial` at fork, before the API call, and an unknown outcome
  also `touch`es `new.$serial.pending` (`:89`). So any worker the creator makes
  always leaves a `new.*` file, and the predicate's "no `new.*`" clause can hold
  only when the creator never ran. The holder always sets `UNBUG_LAUNCH_STATE`,
  so the state directory is never `rm -rf`'d, and the file persists. The only
  residual — a controller killed between `control_resume`'s `mkdir`
  (`factory/control_resume.py:50`) and its `launch.json` write — leaves the
  operation `pending`, which is fail-closed and money-safe. No Boat inventory
  call is needed, and adding one would violate the no-cloud-I/O-under-the-batch-
  lock rule.
- **Design-1 M2 is resolved correctly and the chain-head rule is complete.**
  Operation IDs are UUID5 over the source, so a given source maps to one
  operation and each output is unique to one operation; the chain is linear and
  has exactly one head. "Zero or several heads is unreadable" is a defensive
  clause that well-formed data never hits. The head is selected structurally
  (output null, or not another operation's source), so a failed head or a
  retired-with-no-output head is surfaced with its own row and flag even when an
  earlier collected entry and a pointer exist. The implementation must replace
  the whole `active`/fallback block (`factory/batch_status.py:227-244`),
  including the current "retired with no output -> unreadable" path, with the
  design's explicit mappings.
- **Design-1 M3 is fully specified.** `failures` joins `FIELDS` (`:28-31`) and
  `resume_failed`/`publication_failed` join the operation incident whitelist
  (`:66`) in the single shared `validate_operations` that `batch_service`
  imports. The money-state accounting-incident reasons (`:350-351` and
  `money.ACCOUNTING_ERRORS`) are a separate set and are correctly left unchanged.
- **Design-1 N3/N4 are addressed.** The publish child zeroes its identity
  buffer in the same `finally` as dispatch/resume (needs `main` to read the key
  for `publish` too). Dispatch children reach `record_exit` only
  (`factory/key_holder.py:437`); resume/publish reach `record_child`, so there
  is no double count.
- **The publish operation lock is safe.** `collect()` and `reconcile()` take
  only `money.locked`, not the operation lock, so a publish child holding its
  operation lock across them does not self-deadlock, and a second publish child
  after a holder restart loses the lock race and its exit is not counted.
- **The R2 ceiling is money-safe.** `r2_publish` raises `publication_failed`
  before any ACK or pointer write, so a failed publication releases no hold and
  cannot double-spend; the verified bytes stay in `launches/<id>/collected` for
  an idempotent manual replay, which is the right place for a later activation
  step to resume from.
- **Test coverage matches.** The design's tests 1-7 cover bounded retries and
  the durable count (1-2), the lost-exit predicate with the mkdir fence (3),
  publication replay and the five-failure terminal (4), both terminal status
  cases over a real collected generation (5), the serve/corrupt-money
  robustness (6) and the TRUSTED_FILES pin (7).

Skipped: I did not run the suite or measure the kill-window timing; the M1
closure is a source-read argument, not a measured one. I reviewed read-only and
saved nothing; the elephant records this report.

---

Reviewer: goldfish, OpenCode `openrouter/~deepseek/deepseek-pro-latest`, design review 2 (activation readiness addendum), 2026-10-30.
