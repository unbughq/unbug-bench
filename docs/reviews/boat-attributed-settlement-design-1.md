# Goldfish design review, round 1: `docs/designs/boat-attributed-settlement.md`

- **Mode:** REVIEW
- **Personas:** zoom_out, design_critic, implementation_readiness
- **Standards:** heilmeier-standard.md, implementation-readiness-standard.md
- **Target:** worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, HEAD `ebc648f`
- **Read against:** `bin/boat-spend`, `bin/boat-launch-guards.sh`, `factory/boat_lifecycle.py`, `factory/practice_cleanup.py`, `factory/launch.sh`, `factory/deployment_inventory.py`, `factory/practice.py`, `control/unbug-practice-cleanup@.service`, `tools/public-qualification/finish.py`, retained `billing.md` and `create.md`, the `tests/factory/fixtures/isolation-settlement-cloud/` fixture, `docs/reports/practice-run-20261102.md`, `practice-fresh-admission.md`, `isolation-settlement-cloud.md`, `docs/designs/pilot-run.md`, and Murphy register rows 17, 49 and 51.
- No live, provider or network calls were made, nothing was written, and no delegates were used.

## Verdict: FAIL

There are 2 Blockers and 6 Majors. All of them can be fixed in round 2 with small changes to the text.

The core approach is sound:
- It keeps the existing ledger and lock.
- A settled row becomes a permanent debit.
- Ledger-first replay prevents double counting.
- The cumulative cap never resets.
- It refuses to derive charges from balance deltas.

These keep the design small and avoid double-charging. The failures are in the edges of the lifecycle, and both Blockers can permanently stop Boat admission on this control home. Under the "no reset / no fresh home" rule in `pilot-run.md:22`, that also ends the pilot.

---

## Implementation blockers

### B1. Blocker: a lifecycle that never created a VM blocks admission forever

**Scope:** "Validation before querying usage": "A no-worker reservation is not discharged by this increment; no zero-cost inference". Also "Keep the existing single outstanding lifecycle policy" and "no new-batch reset".

**Finding:**
- `guard_init` runs `boat-spend --check` (`boat-launch-guards.sh:33`) well before the first `guard_new`.
- `factory/launch.sh` has several ordinary exits between those two points:
  - `launch.sh:383`: "selection requires statements-key; no VM created";
  - the `codex_login_gate` break at `:659`;
  - restore preparation failures at `:193–230`.
- When that happens, `guard_exit` sees empty `ids` with nothing unfinished and runs `--finish`. The row becomes `finished` with an empty worker set.
- Under this design that row can never settle. Since only one outstanding row is allowed and nothing resets, every later Boat admission on the home is refused permanently.

This is the most likely early failure. The practice log alone shows four stops before creation. It defeats the stated goal: "first pilot worker after practice as well as later workers".

**Zero cost is provable, not inferred.** `guard_new` writes and fsyncs `new.N.pending` before any provider request (`boat-launch-guards.sh:64–76`). Serials never replay, and resume launches never create. So a bound STATE with all of the following has provably submitted no create request:
- empty `ids`;
- no entry matching `new.*` (checked with lexists, including `.pending` and symlinks);
- a `finished` row.

**Minimal fix:** add exactly that case. Settle with `workers=[]` and `actual_spend_usd="0"` when the row is finished and bound, STATE is canonical, and the three conditions above hold. Keep the full `list --json` check as a cheap extra. Every other empty or unknown case still holds.

If the author rejects this, the design must state the consequence plainly: one admitted-but-uncreated lifecycle ends Boat use on this home forever. Since that interacts with the founder's no-reset rule, it needs founder acceptance.

### B2. Blocker: the practice run's own reservation can block the pilot

**Scope:** "Existing rows remain unknown unless the original spend record supplies those fields and an already-recorded state binding."

**Finding:**
- The live control home had no reservations ledger as of `stream-b-activation-practice-plan-20261031.md:161`.
- The practice run is paused on pinned source `3a50896`. `practice-run-20261102.md` says "original release pins retained; no code change or repin".
- If practice resumes on those pins, its reservation is written by the current `boat-spend`. That row has no STATE binding and no `vms`/`ttl_seconds`/`max_spend_usd` in the ledger.
- Under this design such a row stays unknown forever. The pilot is then permanently refused, and no reset is allowed.

The design never states this ordering requirement.

**Minimal fix:** add one sentence. The practice run must admit from a release that contains this increment, so its row is bound at admission. A practice run on older pins makes the home permanently unsettleable, which is a STOP to return to the parent. Name the pins that need re-cutting (practice release and policy pins) as a dependency after merge.

---

## Majors

### M1. Cleanup integration leaves design decisions to the implementer

**Scope:** "The independent cleanup owner … calls the same --settle command (and --finish first if controller died before it) … Retry can run from its existing loop, bounded per call."

**Findings:**
- **The loop stops too early.** `practice_cleanup.main` returns 0 as soon as `step()` reports `complete` (`practice_cleanup.py:132`). If settlement is still pending at that moment, nothing retries it, yet the design relies on this owner for retries.
- **`--finish` needs an exit code that cleanup doesn't have.** Its signature is `RECORD EXIT_CODE IDS_FILE`. The cleanup owner has no exit code, so the implementer would have to invent one.
- **Cleanup's `--finish` bypasses guard markers.** Calling `--finish` from cleanup skips the guard's `spend-finished` and `complete` markers (`boat-launch-guards.sh:202–211`). A resumed `guard_exit` would then call `--finish` again.
- **The status representation is undefined.** No field names or values are given for "records settlement_pending versus settled".
- **The retry interval is undefined.** The loop runs every 5 s, which would mean a provider `list` plus N `usage` calls every 5 s, indefinitely.
- **The file isn't scoped.** `practice_cleanup.py` is hard-coded to practice (`pilot-run.md` gives generalizing it to a separate M increment). The design doesn't say whether this increment edits it.

**Minimal fix:**
1. Delete "--finish first". Let `--settle` accept a bound row in either `reserved` or `finished` status once deletion proof holds, and move it straight to `settled`.
2. `--finish` replay already must not downgrade a settled row.
3. In `step()`, report `state="settlement_pending"` until `--settle` exits 0. Report `complete` only after both verified absence and settlement. Retry `--settle` at most once every 60 s.
4. Add `factory/practice_cleanup.py` to the target scope explicitly.

### M2. Passing STATE from non-batch launches contradicts the validation rules

**Scope:** "Pass STATE also for non-batch launch guards."

**Finding:**
- Without `UNBUG_LAUNCH_STATE`, STATE is a `mktemp -d` directory (`boat-launch-guards.sh:9`).
- `monitor.sh` is never written for such launches (`:46`).
- The directory is deleted with `rm -rf` after a clean `--finish` (`:212–213`).

The design requires `monitor.sh`, with `spend_file` resolving to RECORD. So non-batch rows can never settle. If inline settlement fails, the evidence is deleted, so a later standalone `--settle` is impossible.

**Minimal fix:** drop this line. State instead that non-batch launches (`exam-launch`, `run-gate-smoke`) remain unsettleable and keep today's blocking behaviour. This is no regression, since any other row blocks today.

### M3. The deployment inventory breaks after the first settlement

**Scope:** "Keep version 1 and add status settled."

**Finding:** `factory/deployment_inventory.py:20` has `STATUSES = ('reserved','finished','reconciled_expired')`. Once a row is settled, `unknown_statuses` becomes at least 1, `state` never becomes `ok` (`:220`), and preflight inventory fails before pilot activation.

**Minimal fix:**
1. Add `settled` to `STATUSES` and report the settled decimal sum.
2. Add `factory/deployment_inventory.py` and `tests/factory/test_deployment_inventory.py` to the scope.

### M4. Target scope and data shapes are incomplete (zero-decision rule)

**Findings:**
- **No file list.** Files touched implicitly include:
  - `bin/boat-spend`
  - `bin/boat-launch-guards.sh`
  - `factory/boat_lifecycle.py`
  - `factory/practice_cleanup.py`
  - `factory/deployment_inventory.py`
  - the host trusted-inventory file (name it)
  - `tests/factory/test_boat_settlement.py`
  - the existing tests in `test_isolation_timeouts.py`, `test_control_resume.py` and `test_deployment_inventory.py`
- **Spend-record mirror shape is undefined.** Is `actual_spend_usd` in the spend record a decimal string, like the ledger, or a float? `tools/public-qualification/finish.py:86` requires an int or float. Note that it already rejects today's `None`, which is a pre-existing gap worth recording. Also, the retained fixture record carries a historical numeric `actual_spend_usd: 0.09361` that is really a balance delta. State that a pre-existing value is never read as settlement and is overwritten only by the mirror.
- **Ledger settlement schema** needs exact key names, types and a rule that rejects unknown keys.
- **`--settle` exit-code contract is unspecified.** Settled, already-settled-and-repaired and unavailable need defined codes. Cleanup depends on them.
- **Timeouts under `boat-reservations.lock` are unspecified.** Name a `BOAT_COMMAND_TIMEOUT_SECONDS` for `list` and `usage`, and a total bound. `finish.py` kills `--finish` at 130 s, and `boat-call` defaults to 120 s per call plus its version probe.
- **How to parse `dollars` is unspecified.** Specify `json.loads(..., parse_float=Decimal)`, or `Decimal(str(x))` with an explicit rounding rule.
- **"Malformed creation record" is undefined.** `boat_lifecycle.ids()` silently skips lines that aren't JSON (`:24–25`) and follows symlinks (`read_text`, `glob`). That contradicts "regular files without following symlinks". Say whether `ids()` gets hardened, or whether the new validator re-checks `ids`/`new.N` with `lstat` and requires exactly one valid `created` event per non-pending `new.N`.

**Minimal fix:** add a "Files and shapes" block covering the items above.

### M5. Evidence claims overstate the fixtures

**Scope:** "using saved real deletion receipts and creation/spend layouts in isolation-settlement-cloud".

**Finding:** the fixture holds only:
- one spend record;
- one readiness record;
- deletion request, completion-query and completion files for `bx_d6dzvjbc`.

It contains no creation or state layout: no `ids`, `new.N`, `monitor.sh`, `*.started`, or ledger. No such real layout exists anywhere under `tests/` or `docs/`. Under the "Real artifacts" rule in ENGINEERING §4, the claim must be accurate.

**Minimal fix:** reword the claim:
- The deletion receipts and spend record are real.
- STATE, creation and ledger layouts are produced by running the real `guard_init`/`guard_new`/`guard_exit` with authored `BOAT_CMD` edge doubles, following the `test_control_resume.py` pattern, and are labelled authored.
- No two-worker real receipt exists, so the two-ID tests are authored.

### M6. Heilmeier gaps and one row mislabel

**Findings:**
- **Cost** is not stated.
- **Timeline** is not stated.
- **Murphy 51** is mislabelled. It covers control-VM restart recovery, not lifecycle cost.
- **Objectives** are jargon-dense. Example: "attributable machine usage becomes a permanent cumulative debit".

**Minimal fix:** add one plain line for each of these, and correct the row reference.

---

## Live qualification gates

These do not block the offline build, and tests must not claim them. Authored provider doubles for `usage` and `list` are acceptable offline, provided they are labelled as validation and arithmetic only.

**G1. Post-deletion per-ID usage may not be served.** The retained contract weakens the design's core premise:
- `billing.md` says "Read one sandbox … while it runs or after it stops", which covers stopped sandboxes, not deleted ones.
- Both the dashboard and `GET /sandboxes?include=cost` fold deleted sandboxes into an aggregate line (`deletedCost`).
- So a 404 or month-scoped result for a deleted ID is plausible.

**Zoom-out recommendation (Major, not an implementation blocker):** before spending the L build, ask the founder to authorize one zero-cost read-only probe through the pinned CLI (`boat 1.0.85`): `boat-call usage bx_d6dzvjbc --json`. That ID is retained, already deleted (2026-10-29), and attributable, so the probe needs no creation and no spend. Record:
- whether the verb exists;
- the shape of the JSON;
- `running`;
- whether lifetime totals survive deletion and the month boundary.

If the probe fails, the design STOPs as it already says, and the build is avoided. Running it is not this reviewer's call: it is a live call, and I made none.

**G2.** The JSON shape of `usage` in CLI 1.0.85, including any ID field, must be captured. Until then:
- the offline rule that unknown fields are discarded stands;
- if an `id`/`sandboxId` field is present and differs from the queried ID, refuse. Specify this now, since it is cheap.

**G3. Practice-run checks.** The practice exam must show:
- no snapshot or proxy charges;
- auto top-up off;
- wallet credit covering the estimate.

It must also record the machine debit next to the wallet delta.

**G4. Wallet race and cap.** Murphy 17 stays open, and so do 49 and the real row-51 concern. The TTL is not a hard provider cap. The design's wording here is correct.

---

## Nits

- **Reuse existing parsing.** Monitor parsing already exists in `practice_cleanup.monitor()`: shlex, single assignment, `spend_file` under `results/spend`. Factor out its `spend_file` part rather than writing a second parser. The timing check stays practice-specific.
- **Pin the home.** `--settle` from cleanup should pass `UNBUG_CONTROL_HOME` explicitly. Both sides default to `~/.unbug-control` today, so this is correct only by coincidence.
- **Over-cap has no exit.** An actual debit above the cap stops admission permanently, with no recovery under no-reset. Say so explicitly as accepted, with the founder deciding what happens next.
- **Lock hold during settlement.** Holding the lock across provider calls is acceptable given the single-outstanding policy. State that `--check` blocks, without a timeout, while a settlement runs.

---

## Confirmed sound (no change needed)

- Ledger-first atomic write, then the spend-record mirror. A replay repairs the mirror without querying the provider again and without adding a debit.
- `--finish` must never downgrade a settled row. Today's replay branch at `boat-spend:169–174` does downgrade one, and the design names that correctly.
- No partial settlement across IDs. Over-cap actual cost is kept, never clamped.
- The cumulative cap is the minimum across caps and never replenishes. This matches `pilot-run.md`'s infrastructure ceiling of min($5, credit) shared across all lifecycles. Practice uses `--max-spend 5`.
- Deletion identity is reused from `_delete`, and inventory absence is never enough on its own.
- Hetzner is unchanged. Hetzner rows have no ledger path.

**Round-2 asks:** resolve B1 and B2 and M1–M5, add the M6 lines, and decide whether to run G1 before the build.

---
Writer disposition: B1/B2 and M1–M6 accepted; revision 2 specifies zero-creation proof, post-merge practice repin, cleanup retry semantics, non-batch scope, inventory support, exact shapes/timeouts and honest fixture provenance. All nits accepted. G1 remains a live qualification gate: no probe under the parent's offline-only instruction. G2 identity checks and G3/G4 evidence limits are explicit. No findings rejected; no live action or practice-state change.
