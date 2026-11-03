# Goldfish design review, round 2 (final): `docs/designs/boat-attributed-settlement.md`

- **Mode:** REVIEW
- **Personas:** zoom_out, design_critic, implementation_readiness
- **Standards:** heilmeier-standard.md, implementation-readiness-standard.md
- **Target:** worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, HEAD `847e81e`
- **Read against:**
  - `bin/boat-spend`, `bin/boat-launch-guards.sh`, `factory/boat_lifecycle.py`, `factory/practice_cleanup.py`, `factory/deployment_inventory.py`
  - `factory/launch.sh` (lines 140–150, 376–383, 648–668), `factory/launch_manifest.py`, `tools/public-qualification/finish.py`
  - `docs/reports/practice-run-20261102.md`, Murphy rows 17, 49 and 51
  - round-1 review `docs/reviews/boat-attributed-settlement-design-1.md`
- I made no live, network or provider calls. I wrote nothing, used no delegates and did not access practice state.

## Verdict: PASS

No blockers are left. There are 2 Majors and 6 Nits.

The two Majors are both edges of the B1 fix. Each is a one-sentence change to the text. Neither needs a round 3, but both need to be in the implementation, and the diff goldfish must check them.

---

## Round-1 resolution check

**B1 (zero-creation lifecycle): resolved.** Lines 67–70 add exactly the provable case: a finished row bound to its STATE, a regular empty `ids` file, and no `new.*` entry checked with `lexists`. The source supports the proof:
- `guard_new` writes and fsyncs `new.N.pending` before the provider request (`boat-launch-guards.sh:64–76`).
- `--check` runs inside `guard_init` (`:33`), before any creation.
- The `codex_login_gate` break at `launch.sh:654` happens after `guard_init`, so this case is reachable and is now covered.

The lines 65–66 rule for reserved rows also holds. Creation is bounded by `while [ "$serial" -lt "$n" ]` (`launch.sh:653`), and a failed `guard_new` still uses up its serial. So once serials 1..vms each hold one `created` event, no slot is left that could create a VM after settlement. Requiring finished for the empty case is also correct: a reserved empty row can still have a live controller that will create.

**B2 (old-pin practice reservation): resolved.** Lines 14–18 make the re-pin a dependency and say an unbound old-pin row is a STOP. I checked the evidence: the practice abort happened at `launch.sh:150`, before `guard_init` at `:376`. The report confirms "Monitor absent" and creation records 0. So no Boat ledger row exists yet, and the dependency can still be met.

**M1 (cleanup integration): resolved.**
- Cleanup no longer calls `--finish`.
- `--settle` accepts reserved or finished rows, with full proof.
- `settlement` and `settlement_attempted_at` are defined, with `settlement_pending` before `complete`.
- Retries are at least 60 s apart and survive a restart.
- `UNBUG_CONTROL_HOME` is passed explicitly.
- `practice_cleanup.py` is explicitly in scope.

**M2 (non-batch STATE): resolved.** STATE is passed only when `UNBUG_LAUNCH_STATE` is set. `exam-launch` and `run-gate-smoke` keep today's blocking behaviour.

**M3 (inventory): resolved.** `settled` is added to `STATUSES` and validated through the same helper. `settled_usd` is added, `reserved_usd` is unchanged, and the test schemas are updated.

**M4 (files and shapes): resolved.** Exact reservation, settlement and worker keys are given, and unknown keys are rejected. The parsing is `parse_float=Decimal`, reject constants, precision 80, `Inexact` trapped. Exit codes are defined. The spend-record mirror is a float for `finish.py`, and the float is never read back. `ids()` is not reused for validation; a new `lstat`-based validator does that.

**M5 (evidence claims): resolved.** The receipts and the spend record are labelled real. The layouts, the two-ID cases and the usage/list replies are labelled authored.

**M6 (Heilmeier gaps): resolved.** Cost ($0 provider spend) and timeline (1–2 days, then a live gate) are stated. Row 51 is labelled correctly, and the Murphy labels match the register.

**G1–G4:** these stay honest live gates. G1 is deferred under the parent's offline-only instruction. Line 202 states that if per-ID usage after deletion is unavailable, this design cannot deliver reuse, and that is a STOP. No live qualification is claimed.

**Timeouts:** the arithmetic holds. The RPC budget is 40 s, each call gets `min(10, remaining)`, and the outer timeout is `remaining + 70`. So no more than 110 s passes after the lock is taken, which is under `finish.py`'s 130 s kill. Lock wait is excluded, and a caller killed mid-run recovers through ledger-first replay.

---

## Majors

### M-A. Zero-creation proof still requires `monitor.sh`, which leaves a window that blocks the home permanently

**Scope:** lines 58–59 ("including monitor… Its spend_file resolves to RECORD") together with lines 67–69.

**Finding:**
- `guard_init` reserves at `:33` but writes `monitor.sh` only at `:46–51`.
- Several exits fall between those two points:
  - `launch.sh` runs `set -eu`, so the margin validator's `sys.exit` (`:36–44`) exits the script when `BOAT_TTL_MARGIN_SECONDS` is invalid or the TTL is ≤ 1;
  - a TERM or INT arriving in that window;
  - `--check` failing after `save_ledger()` (`boat-spend:153`) but before its own exit.
- Each of these runs `guard_exit`, which calls `--finish` with empty `ids` and leaves a finished, bound row with no `monitor.sh`.
- Under lines 58–59, that row can never settle. Under the no-reset rule, that ends Boat use on this home.
- `control_resume.py:29` also skips a STATE without `monitor.sh`, so a reserved row from a controller killed in this window is never finished either.

**Simplicity rationale:** the ownership authority is already the STATE binding the ledger records at admission, keyed by RECORD. `monitor.sh` adds no proof. The deletion evidence path comes from RECORD (`spend.with_suffix('.deletions')`), not from the monitor.

**Fix:** use delete-before-add.
- For `basis=no_creation`, `monitor.sh` may be absent. If it is present, its `spend_file` must resolve to RECORD.
- Better still, drop the monitor requirement for settlement entirely, and keep the monitor parser only for practice timing.

### M-B. Zero-creation settlement has no automatic retry owner

**Scope:** lines 106–124.

**Finding:**
- For an empty lifecycle, the only automatic settlement attempt is the inline one in `--finish`. It includes a live `boat-call list`.
- If that one call fails or times out, the row stays finished and unknown.
- `practice_cleanup.step()` never reaches `settlement_pending` for this case:
  - with `monitor.sh` present, it raises "creation unknown" when `workers == []` (`:82`), so the state is `uncertain` forever;
  - without it, the state is `waiting` forever (`:74–78`).
- Recovery therefore needs a human to run `--settle` by hand. That is a pit stop, and it contradicts ENGINEERING §3. This is the most likely early-failure path (B1's own scenario).

**Fix:** add one sentence. In `step()`, an empty bound STATE (empty `ids`, no `new.*`, `spend-finished` present) moves to `settlement_pending` and uses the same 60 s `--settle` retry. `--settle` re-proves everything itself. After a successful settle, `main()` exits with `complete`, which also ends today's endless loop for this case.

---

## Nits

1. **Pin naming (line 15).** `b75c9b4` is not recorded anywhere in the repo as a practice pin. The last recorded live bundle is `unbug-practice-20261102-02f3bc9` (`practice-run-20261102.md:100–102`). Name `02f3bc9` (and `b75c9b4`, if the parent's context has it). The rule "never resume on existing pins" already covers both. Also cite the evidence that no Boat ledger row exists yet: the abort at `launch.sh:150` happened before `guard_init`.
2. **First `--finish` after a reserved settlement.** `boat-spend:185` writes `actual_spend_usd=None` into the spend record. Lines 106–107 plus line 93 ("tries settlement" on a settled row repairs the mirror) cover this only by reading two places together. State it once: `--finish` on a settled row must leave the mirror, i.e. `settlement` and `actual_spend_usd`, intact or repaired.
3. **Carrying the attempt timestamp.** `main()` overwrites `.status.json` with `step()`'s result on every loop. Say that `settlement_attempted_at` is read from the previous status on every iteration, not only on restart. Also say what "a future timestamp refuses" means: does it wait until the clock passes that timestamp plus 60 s, or block forever? A backward clock step must not create a pit stop.
4. **Cleanup's `--settle` call has no stated timeout.** Specify it, either none (the lock wait plus 110 s is bounded internally) or for example 180 s. Also state that the 5 s loop blocks during the call.
5. **Type of `dollars`.** `number()` accepts strings. Say whether a JSON string `dollars` is accepted or rejected (rejected is recommended: number or integer token only).
6. **Phasing.** The implementation-readiness standard asks for phases that each leave the build stable. Suggested order: (1) helper, schema and inventory with tests; (2) `--settle` and the `--check` STATE binding with the cumulative cap; (3) `--finish` and the guards; (4) practice cleanup. Also add one line saying that running Boat `exam-launch` or `run-gate-smoke` against this control home blocks it permanently, so operators do not do it by accident.

---

## Implementation and diff-review asks

- Fold M-A and M-B into the implementation.
- Add tests:
  - an exit between `--check` and the `monitor.sh` write still settles `no_creation`;
  - a failed inline list query recovers through the cleanup retry, with no human step.
- The diff goldfish should verify these two tests along with the round-1 negative controls.

No blockers remain, so no stop summary is needed.

---
Writer disposition: M-A/M-B and all six nits accepted. Settlement uses ledger STATE binding, not monitor.sh. Cleanup discovers the bound record from the existing ledger for an empty finished launch and retries automatically. Both mandatory regressions will be checked in diff review. No round 3, no rejected findings, no live action.
