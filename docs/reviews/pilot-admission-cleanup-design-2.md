**Round 2 verdict: BLOCKING.** One blocking finding remains. It comes from the round-1 B1 fix. R1 items M1–M5 and N1–N6 are resolved in the design text.

## Blocking

**R2-B1 — One failed launch now stops the rest of the pilot permanently.**

Severity: Blocker (it stalls the whole batch, the "no pit stop" target property in ENGINEERING §3). It fails safe: no money is spent and no worker is created.

- **Where:** design lines 145–154, the pilot gate in `armed`. Code paths: `factory/practice_cleanup.py:64-73`, `factory/batch_holder.py:395-424` and `:820-836`, and B's `0292abc` versions of `practice_cleanup.step`/`settle`/`bound_spend` and `bin/boat-spend --check` (lines 168–223).
- **How it happens:**
  1. An operation is marked `dispatch_started`.
  2. `launch.sh` then fails before any worker is created. Three ways this can happen:
     - an early launcher failure, such as secret or router delivery (`launch.sh` lines ~300–373);
     - `guard_init`'s `boat-spend --check` refuses the launch, which is the exact B1 scenario and the "unsettled prior row" precondition;
     - an exit while `ids` is empty.
  3. `_reconcile_one` correctly marks that operation `failed/preflight_refused` with `worker_id=None`.
  4. Its cleanup status can never become `complete`:
     - On the baseline, `step` returns `waiting` forever, because there is no `monitor.sh`, no `new.*`, and `ids` is missing or empty.
     - With B merged, a refused `--check` writes no ledger row. So once `spend-finished` exists, `bound_spend` finds zero matches and the status stays `uncertain`. Without `spend-finished`, it stays `waiting`.
  5. The new gate needs every other `dispatch_started` operation to be `complete` or `not_dispatched`. So every later dispatch in the batch gets `MoneyWait` forever. That covers the other cases' initial jobs and all successors.
  6. Nothing in the design ends it. The operation identity cannot be retried, no new identity is allowed, and the design forbids editing `step`.
- **Why it matters:** before R1, this failure lost one operation. With the gate, it blocks all remaining cases.
- **Fix, kept small. Choose one and test it:**
  - **(a)** In the gate, treat another operation as clear when the journal shows it as `state=failed`, `incident=preflight_refused`, `worker_id is None`, **and** it has no unsettled Boat liability. "No unsettled liability" can be shown in either of two ways:
    - B's `step` reports `complete` (zero-worker launch, reserved and then settled); or
    - there is a `spend-finished` record with empty `ids`, and the home ledger has no row whose `state_path` points at that launch. This means one read-only ledger lookup, reusing B's `bound_spend`, so the "no ledger inspection" line would need rewording.

    `step` stays untouched.
  - **(b)** Keep the gate as it is, and state plainly that any preflight failure after dispatch halts the pilot fail-closed until an operator steps in. Give the recovery procedure and accept this as a pilot residual.

  Under either option, add to test 4: a predecessor `dispatch_started` operation reconciled to `failed/preflight_refused` with empty or missing `ids`. The test asserts the chosen behaviour:
  - (a) the successor proceeds;
  - (b) TEMPFAIL, and the residual is documented.

## Nit (optional)

- **N-R2-1** (lines 145–149): the design does not say how `armed` gets the other operations. The caller already holds the `ops` it loaded under the lock (`batch_holder.py:817`), so pass those in, or read `_operations` without locking. Making `ops` a parameter and passing it at both call sites removes the guesswork.

## Checked and OK

- **Ordering (M1):** ready markers are written first, the live operation is stepped first, and terminal revalidation runs last.
- **Freeze (M2):** policy, release and pin stay frozen until every dispatched operation is terminal. Breaking the freeze leaves only the Boat TTL.
- **Deadline wording (M3):** the admission deadline and the creation-latency residual are stated honestly.
- **Unit and CLI details (M4):** the unit fields are exact, `--batch` is a bare flag, `[Install]` is added, and the key holder gets the pin through an `EnvironmentFile` drop-in.
- **`_admit` and startup (M5):** the order inside `_admit` is exact, and refusing to start without a pin is intended and covered by test 1.
- **Prerequisites:** the second check runs under the existing lock, before `dispatch_started`, with no recursive lock. Settling all home ledger rows and merging B are both stated as prerequisites.
- **Unchanged from R1:** there is one creation path and one B integration path. B's files are not edited.

Nothing was written. Per the brief there is no round 3, so this goes back to the parent as a three-line handback.

## Implementer disposition

Round-2 blocker handed back to parent under the two-round cap. No implementation
or third design review started. Choosing a liability-clearance interface or an
explicit fail-closed pilot residual requires parent direction.
