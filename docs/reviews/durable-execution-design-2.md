# durable-execution design review 2

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas zoom_out,
design_critic, implementation_readiness, Mode: REVIEW. Reviewed commit 27e44a0.
Verbatim below; the resolution follows at the end.

---

# Goldfish design review 2: `docs/designs/durable-execution.md` revision 2 (branch `durable-execution`, 27e44a0)

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Read-only.

**Tests run**
- `test_durable_contract.py`: 21 tests, OK.
- `test_durable_replay.py`: 4 tests, OK in 3 of 3 sequential runs (about 29–30 s each).

**Engine checks run against dbos 3.4.0** (scratch program, SQLite):
- A queue registered with `global_concurrency=1` runs ADMIT workflows one at a time across two cases.
- A child workflow started from a parent survives a parent `os._exit` and joins on replay.
- `DBOS.recv(topic, timeout_seconds=3)` returns `None` when it times out.
- `DBOS.register_queue` raises "System database accessed before DBOS was launched" if it is called before `DBOS.launch()`.
- `DBOS.patch` exists and does not need `enable_patching` (`_dbos.py:4180`, `:708-712`).

## Previous findings (design review 1)

| # | Status | Evidence |
|---|---|---|
| 1 | VERIFIED-FIXED | `contract.wait_seconds` has a 1 ms floor (contract:492-497). The replay test reads the clock through a `now()` step (replay test :304-306, :331). `test_restart_after_the_wake_time_has_passed` passes 3 of 3. |
| 2 | PARTIAL | The pinned `application_version` is proven by `test_changed_step_code_resumes_under_the_pinned_version`, and `DBOS.patch` is real. But nothing supplies the per-gate `bench_version`, and "pinned per case" contradicts "a gate change reruns that gate" (new 8). |
| 3 | VERIFIED-FIXED | The key is `case/seq/step/attempt` (contract:219), and `test_keys_never_collide_across_repairs` checks it. |
| 4 | PARTIAL | `Verdict`, `DIAGNOSIS`, `EXTEND`, `RESUME_AFTER_FIX` and the 3/5/progress limits are in code (contract:395-412), and WP10 owns them. But `decide()` sends a failed DIAGNOSIS step to DIAGNOSE again, each time starting another replacement (new 3). |
| 5 | PARTIAL | The protocols exist (contract:427-472), and `ArtifactStore` is scoped. Still missing: the wire format, key format, R2 credentials and three-state poll (new 6); how the Ledger learns or raises the bound, and the ceiling policy (new 7); lease sharing with the G10 child (new 5). |
| 6 | PARTIAL | (a) G10 is a child workflow, but concurrency on one worker, cancellation and inter-gate data are unspecified (new 1, new 5). (b) NOT fixed: snapshot-digest reuse never fires for early gates, because STRESS changes the snapshot (new 4). (c) The subset is defined, but `gate_state/` does not exist (it is `gate-cache/`), and it includes files that gates write. (d) The sequence is written, but G1 and the G8/G9 placement are wrong (N6). |
| 7 | PARTIAL | The queue with concurrency 1 works in 3.4.0, `STATEMENT_REGISTRY` exists and WP11 owns admission. But ADMIT cannot return the updated registry Ref, gets no INPUTS Ref, gets only one scope key, and has no failure route (new 1, new 2). |
| 8 | VERIFIED-FIXED | (a) The `REASON` grammar is tested. (b) `guarded_run` is tested. (c) The HMAC digest is in the `Ref` docstring. (d) `assert_no_conductor` covers env and config, but not the constructor argument (N8). |
| 9 | VERIFIED-FIXED | Rows were moved and added, and every named `new-*` row exists in the register. Publication rows sit with packages that do not publish (N5). |
| 10 | VERIFIED-FIXED | WP5a is the only `run.py` writer in waves 1–2, WP4 is a pure `classify.py`, WP5f owns `model_runtime`, and WP9 owns `run.py` in wave 3. The `classify` signature is still unfrozen (new 9). |
| 11 | PARTIAL | Goal, exams and cost were added. The stated count method gives 495 stops, not about 460, and `timeout` is 22, not 23 (N3). There is no time estimate (N10). |
| 12 | VERIFIED-FIXED | All listed modules exist. They measure 6,388 lines replaced and 1,560 deleted, matching about 6.4k and 1.6k. |
| 13 | VERIFIED-FIXED | The exception is stated (design :231-233) and is founder decision 5. |
| 14 | VERIFIED-FIXED | `max_consecutive_limits` is in `decide()` (contract:381), and the WP4 backoff rule is in WP4's "Done when". The counter is per `seq`, not consecutive (N4). |
| 15 | PARTIAL | Only the worker emits EXHAUSTED, and `--rounds` is set from the spec. There is still no per-case money field, although EXHAUSTED means "the case ran out of its own money" (new 7). |
| 16 | PARTIAL | Slot and replacement behaviour is stated. The rule that only review steps may escalate is not enforced (N1), and what a founder reply does is undefined (new 10). |
| 17 | VERIFIED-FIXED | `_exact` at every depth, kind checks on every `Ref` field, and `batch_spec_from_record` are all present and tested. `SealedCase` has no `from_record`, which is minor. |
| 18 | VERIFIED-FIXED | The `SCORECARD` kind is gone, and `SealedCase` holds only the archive. But the SEAL step cannot return that archive (new 1). |
| 19 | VERIFIED-FIXED | Design :5-6. |
| 20 | VERIFIED-FIXED | Design :151-154. |

## New findings

### 1. BLOCKING: the contract cannot carry the data that flows between steps
- **SEAL cannot return its output.** `StepResult` has no field of kind `SEALED_ARCHIVE` and no `hard` flag (contract:223-234), and `receipt` must be `GATE_RECEIPT`. Probe: `StepResult(OK, "seal:pass", snapshot=..., receipt=Ref(.., SEALED_ARCHIVE))` raises "receipt must be a receipt Ref". `SealedCase.archive` and `SealedCase.hard` therefore cannot come from any step result.
- **ADMIT cannot return the updated registry.** No `StepResult` field is of kind `STATEMENT_REGISTRY`, so the next ADMIT in the queue cannot get the registry its predecessor wrote.
- **Later gates cannot read earlier gates' evidence.**
  - Gate steps never change the snapshot (design :84-86), and `StepInput` carries only `snapshot`, `feedback` and `registry` (contract:192-196).
  - But G11 reads G10's pilot passes from `c.pilot_passes` or `c.work/<role>/results.json` (run.py:2940-2943), and `c.card["difficulty"]`, which G10 sets (run.py:2932, used at :2945).
  - G17 and SEAL need `c.card['calibrators']`.
  - DIAGNOSIS needs receipts, transcripts and stop history (stream-d.md:320-323).
- **An EXTEND writer round cannot receive the diagnosis's guidance.** `check_result_for` forbids feedback from DIAGNOSIS (contract:269), and `StepInput.feedback` must be `WRITER_FEEDBACK`.
- **Fix.** Before fan-out, add the following and test each round-trip:
  - `StepInput.evidence: tuple[Ref, ...] = ()`, allowing kinds `GATE_RECEIPT`, `DIAGNOSTIC` and `DIAGNOSIS_REPORT`;
  - `StepInput.inputs: Optional[Ref]` (`INPUTS`);
  - `StepResult.archive` (`SEALED_ARCHIVE`, SEAL only) and `StepResult.hard: Optional[bool]` (SEAL only);
  - `StepResult.registry` (ADMIT only);
  - permission for `feedback` on a DIAGNOSIS OK whose verdict is `CLOSE_TO_PASSING`.

  State that the engine passes every receipt of the current snapshot as `evidence`.

### 2. BLOCKING: ADMIT has no inputs, the wrong key and no failure route
- **No INPUTS.** ADMIT gets no INPUTS Ref, although the promise text, app pin and rotation live there (contract:282). It gets only `registry`.
- **One key.** `WorkerChannel.start(..., scope_key: bytes)` (contract:457) delivers one key. ADMIT reads batch-scoped artifacts (contract:86) and writes a case-scoped snapshot, so it needs both keys.
- **No failure route.**
  - An ADMIT that cannot admit a bug ends in `decide(ADMIT, EXHAUSTED)` → DIAGNOSE (probed).
  - A DIAGNOSIS `StepInput` requires a snapshot (contract:209), and ADMIT never produced one, so that input cannot be built.
  - DIAGNOSE also starts a replacement. If the promise has no fresh bug left, this becomes an endless chain of replacements.
- **Fix.**
  - Let start deliver `keys: Mapping[str, bytes]`, or add a separate `batch_key`.
  - Add `StepInput.inputs`.
  - Make a non-OK ADMIT that runs out of retries return RETIRE without a replacement, and stop new starts in the batch (for example `Action.STOP_BATCH`, or a rule in `STARTS_REPLACEMENT`).

### 3. BLOCKING: `decide()` loops through diagnosis and replacements without a bound
- **Diagnosing a diagnosis.** `decide(DIAGNOSIS, INFRA_ERROR, step_infra_errors=6)` and `decide(DIAGNOSIS, EXHAUSTED)` both return DIAGNOSE (probed). The result is another diagnosis and another replacement. Stream D treats a malformed or interrupted diagnosis as infrastructure, to retry within the batch bounds (stream-d.md:341-343).
- **One replacement per DIAGNOSE.** `STARTS_REPLACEMENT` contains DIAGNOSE (contract:350), so each extension that ends in DIAGNOSE starts another replacement: up to 6 per original. The design implies one ("both are kept", :121).
- **No cap on cases started.** A systematic factory bug turns every case into DIAGNOSE → RESUME_AFTER_FIX, which parks the case and starts a replacement that hits the same bug. Parked cases pile up, bounded only by money and the deadline.
- **Slot accounting is undefined.** Does a case that is diagnosing, extending or parked for a fix hold a `max_concurrency` slot? What happens to in-flight extensions when `target_sealed` is reached?
- **Fix.**
  - A DIAGNOSIS step that would DIAGNOSE returns RETIRE.
  - Add `Counters.diagnoses_used`, and start a replacement only on a case's first DIAGNOSE.
  - Add `BatchSpec.max_cases_started`.
  - A `factory_bug` verdict pauses new starts until the plumbing-release message arrives.
  - Write the slot and stop rules into the design.

### 4. BLOCKING: early-gate reuse by snapshot digest never fires
- **The snapshot changes between the early checks and the gate loop.** Early checks run after the writer. STRESS then appends to `c.case/freshness.jsonl` (run.py:682-690) and writes `attack-state.json`, which is in the retained subset (design :146-147). So the gate loop's G3, G4, G5 and G15 see a different digest, and the claim "the same rule reuses their results" (design :81) is false.
- **Today's code avoids this deliberately.** `case_hash` excludes `freshness.jsonl` (run.py:917-924), and `gate_state` excludes it and `BUILD-NOTES.md` for every gate except G8 and G9 (gate_state.py:150).
- **G8 and G9 run after a clean stress round, not after the writer** (run.py:1468, :1503, :1660-1661). The design says "after a writer round" (:79-81).
- **The retained subset contradicts the equal-digest test.**
  - It names `gate_state/`, which does not exist; the cache is `c.work/gate-cache` (gate_state.py:249).
  - It includes `infra-attempts.json`, which gates write (run.py:1888; gate_pipeline.py:95, :163).
  - So WP5a's "output digest equals input digest" test contradicts the subset it is asked to retain.
- **Fix.**
  - Add `StepResult.case_digest`: an HMAC of `c.case` without `freshness.jsonl` and `BUILD-NOTES.md`, set by WRITER and STRESS.
  - Key the skip rule on `(gate, case_digest, gate version)`, using the full snapshot digest only for G8 and G9.
  - Correct the subset path.
  - State that a gate step returns its input snapshot Ref unchanged and discards its `c.work` writes, apart from its receipt.
  - Move G8 and G9 to after a clean STRESS round.

### 5. BLOCKING: G10 concurrency on one worker is unspecified
- **Today's overlap rules.** Overlap needs reserved tester instances and a slot offset (gate_pipeline.py:191-202). A G10 failure wins at the next boundary (:187-190). A foreground failure cancels G10 (:222-228). G10 falls back to serial when `overlap_reason` says so (:192-196).
- **Under this design, the following is undefined:**
  - **Shared lease.** The parent and the child both call `WorkerPool.acquire(case_id)`, which is "idempotent per case" (contract:441). That is one lease running two concurrent attempts. Does each attempt restore into its own directory? How does the G10 attempt learn to use the slot offset?
  - **Release during a sleep.** A parent sleep longer than `release_worker_after_sleep_s` releases the lease while the child is still running on it.
  - **Cancellation.** After a foreground failure and REPAIR, is the child cancelled before the next writer round runs on the same worker? `DBOS.cancel_workflow(id, cancel_children=...)` exists (`_dbos.py:2397`), but it does not stop the worker attempt.
  - **Early G10 failure.** Is it detected before the join?
  - **Serial fallback.** Is there one?
- **Fix.**
  - `WorkerChannel` allows concurrent attempts per lease, each in its own directory keyed by the idempotency key.
  - Leases are reference-counted by open attempts.
  - The parent checks the child's status at each foreground boundary, and on a non-OK outcome calls `cancel_workflow` plus `channel.cancel` before it routes.
  - The worker uses `calibrator_slot_offset = bench_workers` for an overlapped G10, and the design states the serial fallback.

### 6. BLOCKING: the wire protocol and key material between WP2 and WP5a are still undefined (previous 5a and 5d)
- **The protocol.** WP2 (`channel.py`) and WP5a (`worker_step.py`) build the two ends in parallel, but the design never says:
  - the remote command;
  - how stdin is framed (the record plus the key bytes);
  - where the result record lives (the key contains `/` and `:`, contract:219);
  - how "the key already exists" is detected atomically;
  - how `cancel` finds the detached unit.
- **Two-valued poll.** `poll` returns `None` both for "running" and for "never started or died without a result" (contract:458). A lost attempt therefore waits `deadline_s` plus grace, up to 4 h at the default (contract:299).
- **Key format.** `KeyService.scope_key -> bytes` (contract:437) is used for both age encryption and the HMAC (contract:93). The byte format, the key derivation and the age library are all unchosen.
- **R2 credentials.** How workers get them is unspecified.
- **Fix.** Freeze these in the design:
  - the command: `python3 -B ~/factory/durable/worker_step.py {start|poll|cancel}`;
  - stdin: one JSON object `{"input": <record>, "keys": {scope: base64}}`;
  - the result path: `~/durable/results/<sha256(key)>.json`, written by atomic rename, with an `O_EXCL` attempt directory as the existence marker;
  - the unit name: `durable-<sha256(key)[:16]>`;
  - `poll` returns `running`, `done(record)` or `absent`; this changes the frozen signature;
  - keys: 32 random bytes, with HKDF-SHA256 deriving the age X25519 identity and the HMAC key, and a pinned library;
  - how R2 credentials reach the worker.

### 7. BLOCKING: money seams are incomplete
- **The Ledger cannot be given a bound.** It has `reserve` and `settle` only (contract:466-467). Nothing gives WP6 the bound in `BatchSpec.money_bound_usd_micros`, or delivers "bound raised" (design :109-111).
- **No ceiling policy.** No rule sets `money_ceiling_usd_micros` per step kind. ENGINEERING §3 says a writer round can cost $15.05, and WP1 would have to invent the ceilings.
- **No per-case money.** There is no per-case money field, yet EXHAUSTED means the case's own money ran out (design :106). Today's default is $50 (Murphy row 9).
- **Lost attempts.** No rule says how to settle an attempt that produced no `Usage`. Its reservation would erode the bound forever.
- **Fix.**
  - Add `Ledger.open(batch_id, bound)`, `Ledger.raise_bound(batch_id, bound)` and `Ledger.settle_lost(key)` (books the whole ceiling).
  - Add `BatchSpec.case_money_usd_micros` and `BatchSpec.step_ceiling_usd_micros: Mapping[StepKind, int]`.

### 8. BLOCKING: versions have no source, and the worker does not enforce them
- **No per-gate source.** `BatchSpec.bench_version` is one digest (contract:286), but a GATE step's `bench_version` is that gate's own digest (design :174-176). The engine cannot compute that digest: it may not read files outside steps (rule 1), and the code lives on workers.
- **Self-contradiction.** "Pinned per case, so a gate change reruns only that gate" contradicts itself. A version pinned per case never sees the change, and ENGINEERING §3 requires that it does.
- **Worker provisioning is unowned.**
  - Today, `launch.sh:685-707` installs and verifies the release, pins the CLIs and builds the image on each worker.
  - WP2's "Done when" covers only creating and deleting Boats.
  - No package installs code at a given version, so "a fix applies from the next step" (design :168-170) is not delivered for worker-side code.
  - The worker never checks that `plumbing_version` and `bench_version` match what it runs.
- **Fix.**
  - Add `BatchSpec.gate_versions: Mapping[gate, digest]`, computed at launch from `gate_state.STAGE_DEPENDENCIES` (gate_state.py:39-48), with a "bench release" message that updates entries.
  - Add a version parameter: `WorkerPool.acquire(case_id, plumbing_version)`.
  - Give provisioning to WP2.
  - The worker returns `infra:version_mismatch` when its installed code differs from the requested versions.

### 9. BLOCKING: WP4's `classify` signature is not frozen, but WP5a calls it
- **Undefined input.** The input type of `classify(stop)` is undefined. The real stops are strings such as `provider_limit:opencode-go/mimo-v2.6-pro`, with no reset time.
- **No clock.** A pure function cannot return an absolute `retry_at` for its backoff without being given `now`.
- **Fix.** Freeze it in the contract or the design:
  - signature: `classify(stop: str, *, step: Step, now: float) -> tuple[Outcome, str, Optional[float]]`;
  - `stop` is the runner's `BudgetError` or `terminal_stop` text.

### 10. BLOCKING: the three waits have no message contract
The three waits are "bound raised", "plumbing release" and "founder reply".
- **Undefined.** Their topics, payloads and senders are not given.
- **Loop needed.** `DBOS.recv` returns `None` after 60 s by default (`_dbos.py:2039`; probed), so each wait must be a loop.
- **Missing payload content.** RESUME_AFTER_FIX needs the new `plumbing_version`, and nothing says the message carries it.
- **Founder reply semantics.** What the reply does (continue, retire, rerun which step) is a design decision left to WP1.
- **Conflict with Stream D.** The in-batch wait contradicts Stream D's parent ruling that factory bugs "do not wait for an in-batch fix" (stream-d.md:348-356). The design does not say it supersedes that ruling.
- **Fix.**
  - Add the topic constants and payload dataclasses to the contract, for example `PlumbingRelease(version)`, `BoundRaised(bound)` and `FounderReply(action ∈ {continue, retire})`.
  - Define what each reply does.
  - State the supersession of the Stream D ruling, with the founder's sign-off.

### NITs
- **N1.** The design says only G8, G9, G16, G17 and stress review may return NEEDS_FOUNDER (design :123-125), but `check_result_for` does not enforce it. SEAL and WRITER escalate (probed). Enforce it in `check_result_for`.
- **N2.** `DBOS.register_queue` works only after `launch()`, and recovery starts at launch. WP1 should test that recovered cases enqueue only after the queue is registered.
- **N3.** The stated count method gives 495 stops over 50 cards. That includes `PauseRequested` (33) and `paused` (28), and `timeout` is 22. Neither 417 (the table's sum) nor about 460 matches. Fix the table and the total.
- **N4.** `step_spent_limits` counts per `seq`, not consecutively, so `max_consecutive_limits` is misnamed.
- **N5.** Ownership gaps:
  - No package owns the SEAL step: WP5a dispatches the writer, stress and gN steps, and WP5b–e omit G12.
  - No package owns the scorecard generator or publication, yet publication rows 16, 26 and 27 are assigned to WP1, WP8 and WP3.
- **N6.** Step sequence gaps:
  - G1 runs after each writer round, before the early checks (gate_pipeline.py:86; run.py:1703-1705), and the design omits it.
  - Today an early-check failure repairs within the same round. Under the design it costs a writer round. State this.
  - Say whether an EXTEND round counts in `writer_rounds_used`.
- **N7.** The design does not name the control-side `StepExecutor` that composes the pool, channel, ledger and store. Boat stderr raised by `acquire` or by the ledger is guarded only if those calls run inside `guarded_run`. Name WP1 as its owner.
- **N8.** `assert_no_conductor` misses `DBOS(conductor_key=...)` and DBOS Cloud mode (`_dbos.py:609-631`, `:952-958`). After construction, also assert that `conductor_key is None` and the instance is not in Cloud mode.
- **N9.** The daily `factory-simplify` merges touch `run.py`, which WP5a owns. Say who resolves the conflicts.
- **N10.** Heilmeier "how long" is unanswered (design :289-296). Give a per-wave estimate.
- **N11.** The replay timing assertion (`elapsed < 5.5`, including interpreter and DBOS startup) may flake under the suite's parallel load.

## Verdict: FAIL

Ten findings are blocking. Seven of them, findings 1–3 and 6–9, need fields or signatures added to the frozen `contract.py`: step results and inputs, ADMIT keys, policy, wire protocol, ledger, versions, and `classify`. Findings 4 and 5 rest on wrong claims about today's pipeline: digest reuse never fires, and G10 overlap needs shared-worker rules. Finding 10 leaves the two waits in WP1's "Done when" (resume-after-fix and escalation parking) without semantics. Wave 1 should not fan out until 1–10 are fixed, and the contract should go to version 3 with tests.

---

## Resolution (elephant)

No finding was rejected. Instead of patching each one, revision 3 removes the two
choices behind most of them:

- **Per-gate engine steps become one GATES step.** It runs today's `run_gates`,
  which already handles G10 overlap, early reuse and per-gate invalidation.
- **The engine policy leaves the frozen contract.** It becomes `policy.py`, owned
  by WP1.

The contract goes to version 3, with 20 contract, 9 policy and 4 replay tests.

| # | Resolution |
|---|---|
| 1 | Fixed. Added `StepResult.archive` and `hard` (SEAL), `StepResult.registry` (ADMIT), `StepInput.inputs` (every step), `StepInput.evidence` (DIAGNOSIS), `StepInput.ruling`, and feedback on a close-to-passing DIAGNOSIS. Evidence that passes between gates stays inside the one GATES step, as today. |
| 2 | Fixed. `start_frame` carries a keys map (case key, plus the batch key for ADMIT). Admission that cannot finish gives `STOP_ADMISSION` (policy). |
| 3 | Fixed in `policy.py`. A diagnosis is never diagnosed: it RETIREs. A case starts at most one replacement (`starts_replacement`). Added `BatchSpec.max_cases_started`. Factory bugs HOLD per the Stream D parent ruling. The slot and target rules are written into the design. |
| 4 | Removed. Early checks stay inside WRITER and STRESS, and reuse stays with the `gate_state` fingerprints inside GATES, which already exclude `freshness.jsonl`. The `gate-cache/` path is corrected. G8 and G9 sit after a clean stress round. |
| 5 | Removed. G10 overlap stays inside `run_gates` on one worker. |
| 6 | Fixed. The wire protocol is frozen in the contract: `WORKER_COMMAND`, `attempt_paths` (O_EXCL marker, atomic result, unit name), `start_frame`, and `Poll` with RUNNING, DONE and ABSENT. Keys are 32 bytes through `derive_keys` (HKDF, RFC 5869 vector tested). Workers hold no R2 credentials; the channel moves blobs. |
| 7 | Fixed. `Ledger` gains `open`, `raise_bound` and `settle_lost`, and `reserve` takes the case limit. `BatchSpec` gains `case_money_usd_micros` and `step_ceilings_usd_micros` (defaults in `DEFAULT_STEP_CEILINGS`). |
| 8 | Fixed. `bench_version` is the batch's bench release. `BenchRelease` is adopted at the next GATES step, where `gate_state` fingerprints rerun only the changed gates. `acquire` takes both versions, and WP2 owns provisioning. The worker returns `infra:version_mismatch`. |
| 9 | Fixed. Added the `Classifier` protocol (`stop`, `step`, `now`) and the `Classified` record. |
| 10 | Fixed. Added the `Topic` enum and the payloads `BenchRelease`, `PlumbingRelease`, `BoundRaised` and `FounderReply` (CONTINUE with a ruling, or RETIRE). Waits loop on `recv`. Adopting the Stream D ruling removes the in-batch fix wait. |
| N1 | Fixed. `check_result_for` allows NEEDS_FOUNDER only from STRESS, or from GATES naming G8, G9, G16 or G17. |
| N2 | Fixed. Engine rule 6, and a WP1 test. |
| N3 | Fixed. 435 interruptions, with the method stated and exclusions named. |
| N4 | Fixed. Renamed to `max_spent_limits_per_step`. |
| N5 | Fixed. SEAL goes to WP5a, `report.py` to WP1, and publication to WP8. The publication rows are reassigned. |
| N6 | Fixed. G1 and the early checks stay inside WRITER as today, and early repair stays in the round. Extension rounds count separately. |
| N7 | Fixed. `executor.py` belongs to WP1, inside `guarded_run`. |
| N8 | Fixed. `DBOS__CLOUD` is refused, and WP1 checks the constructed instance. |
| N9 | Fixed. WP5a's owner resolves `run.py` merge conflicts. |
| N10 | Fixed. Per-wave estimates are added. |
| N11 | Fixed. The test uses a 20 s limit and 12 s of downtime, asserting under 17 s (starting the wait over would take at least 20 s). |
