# durable-execution design review 3

Reviewer: fresh goldfish subagent (general-purpose), read-only, personas zoom_out,
design_critic, implementation_readiness, Mode: REVIEW. Reviewed commit db9a0d2.
Verbatim below; the resolution follows at the end.

---

# Goldfish design review 3: `docs/designs/durable-execution.md` revision 3 (branch `durable-execution`, db9a0d2)

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Read-only.

**Tests run**
- `test_durable_contract.py`: 20 tests, OK.
- `test_durable_policy.py`: 9 tests, OK.
- `test_durable_replay.py`: 4 tests, OK in 2 of 2 runs (42.9 s and 42.6 s).

**Contract and policy probes** (scratch, importing `factory/durable`):
- A SEAL OK with `archive` and `hard` passes `check_result_for`.
- A DIAGNOSIS OK with `CLOSE_TO_PASSING` and **no** feedback passes.
- A PROVIDER_LIMIT `StepResult` may carry a `snapshot`.
- A GATES OK may name a `gate`.
- `decide(GATES, GATE_FAILED repairable)` with `extensions_used=1, writer_rounds_used=3` returns REPAIR.

**On the trade.** One coarse GATES step running `run.run_gates` is the right simplification. It deletes the per-gate orchestration that caused review-2 findings 4 and 5. G10 overlap does survive, because `GatePipeline.run` (gate_pipeline.py:180-237) runs in one process. Moving policy out of the frozen contract is also sound.

But the trade costs three things the design does not admit:
- **The engine can no longer see which gates passed** (new 1).
- **Early-check reuse is only partly kept** (review-2 finding 4).
- **The lost-progress cost is wider than "a worker dies"** (N2).

## Review-2 blocking findings

| # | Status | Evidence |
|---|---|---|
| 1 | VERIFIED-FIXED | These are all present (contract:216-223, :270-272, :301-302, :308-323) and the probes pass: `StepResult.archive`/`hard` (SEAL only), `registry` (ADMIT only), `StepInput.inputs` (required), `evidence` (DIAGNOSIS only), and feedback on a close-to-passing DIAGNOSIS. Evidence passed between gates stays inside the one `run_gates` process. |
| 2 | VERIFIED-FIXED | `start_frame` takes a keys map and refuses an ADMIT without the batch key (contract:469-478). ADMIT that gives up returns `STOP_ADMISSION` (policy:53-54), and that action is not in `ENDS_LINE_OF_WORK`, so it starts no replacement (policy:94). |
| 3 | VERIFIED-FIXED | A DIAGNOSIS that gives up RETIREs (policy:55-56). `starts_replacement` allows one replacement per case and checks `max_cases_started` (policy:97-102). Factory bugs HOLD. The slot and target rules are in the design (:146-150). `Counters.diagnoses_used` is unused, which is harmless. |
| 4 | PARTIAL | The snapshot-digest problem is gone. But today's early reuse is the in-memory `c.early`/`c.early_hash` (gate_pipeline.py:149, :117), and that cannot cross the WRITER→STRESS→GATES process boundary. So G3, which is not in `gate_state.REUSABLE` (gate_state.py:14), always reruns. G4, G5 and G15 reuse only through `gate_state.load`, which demands the evidence files (gate_state.py:280-287, under the `inventory` roots :227-229). The design's subset does not list those files. The claim at design :15-17 ("keeps doing so") is overstated. See N1. |
| 5 | VERIFIED-FIXED | Fixed by removal. Overlap, the slot offset, `role_cancel` and the serial fallback all stay inside one `GatePipeline.run` (gate_pipeline.py:189-237). |
| 6 | PARTIAL | Frozen: `WORKER_COMMAND`, `attempt_paths`, `start_frame` and the three-state `Poll` (contract:445-497). Not frozen: how `poll`/`cancel` name the attempt, what they print, and what the two release digests mean (new 2). `ABSENT` on a transport failure allows two attempts at once (new 3). |
| 7 | PARTIAL | The seams exist: `open`, `raise_bound`, `settle_lost` and a case limit on `reserve` (contract:578-583), plus `case_money_usd_micros` and the ceilings (:347-348). But the ceilings act as hard stops that give up, and a case-limit refusal waits for a batch-bound message that cannot fix it (new 4). |
| 8 | PARTIAL | `acquire` takes both versions (contract:553), WP2 owns provisioning, and the worker returns `infra:version_mismatch`. But nothing defines what `plumbing_version` and `bench_version` hash, or where the worker reads its installed values (new 2). |
| 9 | VERIFIED-FIXED | The `Classifier` protocol takes `stop`, `step` and `now` and returns `Classified`, which reuses the `StepResult` shape rules (contract:511-526). |
| 10 | VERIFIED-FIXED | The `Topic` enum and the `BenchRelease`, `PlumbingRelease`, `BoundRaised` and `FounderReply` payloads are in contract:402-440. CONTINUE carries a ruling, and RETIRE retires. Waits loop on `recv` (design :216). The Stream D HOLD ruling is adopted (design :131-133). |

## New findings

### 1. BLOCKING: a GATES result cannot say which gates passed, so WP1 cannot enforce progress or report per-gate results
- **Where the gap is.**
  - `policy.progressed(before, after)` needs the set of gates passed before and after an extension (policy:105-112). ENGINEERING section 3 requires code to enforce this.
  - `report.py` (WP1) must show "outcomes, stages and gates" on the public card (design :239-240).
  - Under revision 3, a GATES `StepResult` carries only the one failing or escalating `gate` (contract:263).
- **Why the engine cannot work it out.** It cannot infer the passed set from the failing gate:
  - The order lives in `run.GATES` (bench logic, run.py:34), and a `BenchRelease` can change it.
  - A G10 failure is reported at a later boundary, after G6–G15 may have passed (gate_pipeline.py:189-190).
  - Reused gates and dry-run skips also count.
- **Why it is blocking.** WP1 would have to open WP5a's private `GATE_RECEIPT` and parse a format nobody has frozen. Getting the set properly needs a contract change.
- **Fix (contract v4).** Add `StepResult.passed: tuple[str, ...] = ()`:
  - each entry matches `GATE`;
  - allowed only for GATES;
  - content-free.

  Add a strict round-trip test, and state that `progressed` and `report.py` read it.

### 2. BLOCKING: two ends of the worker seam are still unfrozen between WP2 and WP5a
- **`poll` and `cancel` input.** `WORKER_COMMAND + start|poll|cancel` (contract:445) never says how these two identify the attempt: argv, a stdin frame, the idempotency key or `attempt_id`.
- **Output encoding.**
  - Nothing says what `poll` prints. Presumably it is `to_record(Poll)`, since `poll_from_record` exists, but this is not stated.
  - Nothing says what `start` and `cancel` print or which exit codes they use.
  - Nothing says how a missing worker root is reported.
- **Release identity.**
  - WP2 must install "the requested release", and WP5a must check that the installed release "matches `plumbing_version` and `bench_version`" (design :183-184, :200-202). Neither digest is defined.
  - Today there are two different fingerprints: the bundle sha256 and `run.bench_manifest()` (launch.sh:683, :702).
  - The gate code lives in `factory/run.py`, so "plumbing" and "bench" are not separable trees as written.
  - If WP2 and WP5a each pick a definition, every attempt ends in `infra:version_mismatch`.
- **Fix (contract docstring and constants).** Add:
  - `poll`/`cancel` read `{"key": <idempotency_key>}` on stdin;
  - `poll` prints one `to_record(Poll)` line, and `start` prints nothing and exits 0 when the attempt is detached or already exists;
  - `RELEASE_MANIFEST = "factory-release/RELEASE.json"` with `{plumbing_version, bench_version}`, written by WP2 at install and read by WP5a;
  - one sentence each defining the two digests: for example, plumbing is the sha256 of the release bundle, and bench is `run.bench_manifest()`.

### 3. BLOCKING: ABSENT on a transport failure lets two attempts of one case run on the same work directory
- **What the code allows.**
  - The `WorkerChannel` docstring allows "transport failures come back as ABSENT or RUNNING" (contract:565).
  - The design says ABSENT makes the engine "retry at once" (design :189-191), with `attempt + 1` and a new key and directory.
  - A cancel happens only at the deadline (:193-194).
- **How it fails.** A `boat ssh` flake while attempt *n* is still running starts attempt *n+1* on the same worker and the same `c.work`/`c.case`.
- **Why it is blocking.** It is a wrong-result path, not a cost:
  - A stale WRITER attempt can keep editing `c.case` while GATES evaluates it.
  - SEAL can then archive bytes that differ from the bytes the gates passed.
- **Fix.**
  - In the contract docstring: ABSENT only when the worker answered and there is neither a result nor a live unit. A transport failure is RUNNING, bounded by the deadline plus the grace period.
  - In the design: before starting attempt *n+1*, the engine cancels attempt *n*.
  - In WP5a: `worker_step.py start` refuses, ending with `infra:attempt_busy`, while another attempt of the same case is live.

### 4. BLOCKING: the money rules turn an unevidenced per-step cap into a case outcome, and a case-limit refusal waits forever
- **The cap.**
  - The worker "stops at" `money_ceiling_usd_micros` and emits EXHAUSTED (contract:219; design :122-123), and EXHAUSTED gives up into DIAGNOSE (policy:75-76).
  - With one coarse step, the $20 `gates` ceiling now caps the whole pipeline: G2, G8/G9, G10 calibrators and pilots, G11, G16 and G17.
  - Stream D's cost evidence says no data can price that package. It warns not to "invent a higher figure", and it records one invocation at $32.61 (stream-d.md:578-579, :640-644).
  - A case whose gates cost more than $20 paid can therefore never seal. Each round ends EXHAUSTED → DIAGNOSE → probably RETIRE. A plumbing cap becomes the case's result.
- **The refusal.** "A refused reservation… waits… until `BoundRaised`" (design :164-165) also applies when the refusal comes from the case's own $50.
  - A case that has spent $31 can never reserve a $20 writer. `BoundRaised` raises only the batch bound, so the case waits forever.
  - Meanwhile the batch "stops starting cases".
  - Real cases do spend this much: e15450 spent $52.79 (stream-d.md:636).
- **Fix (design text plus WP1; no contract change).**
  - Set `money_ceiling_usd_micros = min(case money remaining, batch remaining)`.
  - Use `step_ceilings_usd_micros` only as an optional smaller cap for retries, never as a give-up trigger.
  - When the case's remaining money cannot cover a reservation, treat it as EXHAUSTED (DIAGNOSE). Only a batch-bound refusal waits for `BoundRaised`.
  - State how extension attempts are charged: per ENGINEERING, they draw on the batch bound and not on the case's $50.

### NITs
- **N1 (WP5a).** The retained subset (design :205-209) must also hold:
  - the evidence that `gate_state.load` checks: `gate-details/`, `judge_breadth/`, `review-*/`, and bench `results/` copied to `c.work/bench-results/` (gate_state.py:227-229, :284-285);
  - G10's own attempt receipts;
  - the private card `c.work/scorecard.json`, because the fingerprints read `c.card["roles"]`, `models`, seed and `factory_slots_prepared`, and SEAL reads `calibrators`.

  Without these, the "fresh worker reuses passed gates" test fails. Either persist `c.early`/`early_hash`, or state that G3 reruns in GATES. Also reword design :105 ("No code reads a scorecard back"): the private worker card is read back on every step, and only the public scorecard is not.
- **N2 (WP1, with WP5a). The accepted cost is understated.** Unsaved GATES progress is lost not only when "a worker dies" (design :19-20, :384). It is also lost:
  - on every PROVIDER_LIMIT sleep longer than `release_worker_after_sleep_s` (30 min), when the design itself releases the worker (:118);
  - for every gate outside the cache (G1, G2, G3, G7, G11, G17, and G10 beyond its own receipts), which reruns even on the same worker.

  This is worse than today's same-worker resume for long quota resets. Provider limits are 99 of the 435 counted interruptions.

  Fix: keep the worker while a GATES step sleeps. Or let a non-OK GATES result carry its snapshot: the contract already permits this (probed), and policy's RETRY would restore it. Then say so in "What this does not fix".
- **N3 (WP1).** One `step_deadline_s` (4 h) now bounds the whole gate pipeline. The real cards show 152 min to reach only G15 (14d35a, which never got to G7, the G10 join, G17 or G11) and 144 min for G10 alone (18681d). Give GATES its own deadline from evidence; `StepInput.deadline_s` is per attempt, so this needs no contract change.
- **N4 (WP1).** `decide` cannot tell that an extension is in progress. During an extension with ordinary rounds left, a repairable GATE_FAILED REPAIRs (probed), so the extension grows past ENGINEERING's "one writer round + stress + gate re-run". Add an in-extension flag to `Counters`.
- **N5 (WP1).** `check_result_for` accepts `CLOSE_TO_PASSING` without feedback (probed), which gives an EXTEND with no guidance. Refuse it in `decide_diagnosis` or the executor.
- **N6 (WP1).** ADMIT has two open questions:
  - A PROVIDER_LIMIT sleep inside a queued ADMIT holds the concurrency-1 queue for every other case. Re-enqueue it after the sleep instead.
  - How does an ADMIT read the latest registry Ref when it is dequeued, rather than when it was enqueued?
- **N7 (WP1/design).** HOLD says a later batch may resume a case (design :131-133), but `BatchSpec` has no input for held cases or for their lineage counters. Name it as a planned contract change outside wave 1.
- **N8 (WP5a).** WP5a's note should list the in-step lifecycle branches it disables under the engine:
  - `validate_and_repair`'s in-process repair loop (run.py:3105-3145, including `late_recovery.mark_gates`/`invalidate`);
  - the final `builder-precheck` writer call inside the stress path, plus `stop_defect` (run.py:1693-1706);
  - `reselect_candidate`;
  - `_gate_completed`'s `checkpoint_progress`.

  Also, the card's `builder_rounds` counts extension rounds, but `Counters` does not.
- **N9 (WP1).** DIAGNOSIS needs the engine-side stop history (limits, infra retries), and no worker card holds it. WP1 should seal an engine-written `DIAGNOSTIC` and put it in `evidence`.

## Verdict: FAIL

Four findings are blocking:
- New 1 (passed gates) and new 2 (`poll`/`cancel` and release identity) each need a small contract-v4 addition.
- New 3 (ABSENT on transport failure) and new 4 (money cap and refusal semantics) are wrong-result or hang paths fixed by contract-docstring, design-text or WP1/WP5a changes.

The coarse-GATES trade is sound once new 1 and N1/N2 are addressed and the lost-progress cost is restated honestly.

---

## Resolution (elephant)

No finding was rejected. The fixes became revision 4 and contract version 4, with 24
contract, 11 policy and 4 replay tests, all passing.

| # | Resolution |
|---|---|
| 1 | Fixed. Added `StepResult.passed`: distinct gate names, GATES only, excluding the failed gate, with a strict round-trip. `progressed()` and `report.py` read it. |
| 2 | Fixed. Added `key_frame` for `poll` and `cancel`, plus the output and exit rules for `start`, `poll` and `cancel` in the contract docstring. Added `RELEASE_ROOT` and `RELEASE_MANIFEST` (`RELEASE.json`, written by WP2 and read by WP5a). `plumbing_version` is the factory bundle sha256 and `bench_version` is `run.bench_manifest()`, as `launch.sh` computes them today. Gate code ships with plumbing, and `gate_state` source fingerprints rerun only the changed gates. |
| 3 | Fixed. A transport failure is RUNNING, bounded by the deadline plus grace. ABSENT means only that the worker answered with no result and no live unit. The engine cancels attempt n before n+1, and `start` refuses with `infra:attempt_busy` while another attempt of the case is live. |
| 4 | Fixed. Per-step ceilings are removed. `Ledger.reserve` returns a `Grant` of min(requested, case remaining, batch remaining) with `limited_by`. EXHAUSTED under a batch-limited grant goes to `WAIT_FOR_BOUND`; under a case-limited grant it goes to DIAGNOSE. Extensions pass `draws_case_money=False`. |
| N1 | Fixed in the design. The retained subset adds the `gate_state` evidence, G10's receipts and the private card. G3 rerunning inside GATES is stated, and the scorecard sentence now says the public card is the one never read back. |
| N2 | Fixed in the design. Non-OK results carry their snapshot when they can, and a retry restores it. The lost-progress cost is restated in "What changed" and "What this does not fix". |
| N3 | Given to WP1: a GATES deadline from evidence, recorded in its "Done when". |
| N4 | Fixed. Added `Counters.in_extension`; an extension never repairs. Tested. |
| N5 | Fixed. `check_result_for` requires feedback with `CLOSE_TO_PASSING`. Tested. |
| N6 | Given to WP1: an ADMIT gives up its queue slot while it sleeps, and reads the registry when dequeued. |
| N7 | Fixed in the design. The input for held cases is named as a planned contract change, designed with WP10. |
| N8 | Given to WP5a: the disabled branches are listed in its "Done when". Extension rounds are counted in `extensions_used`. |
| N9 | Given to WP1: the engine seals its stop history as a `DIAGNOSTIC`. |
