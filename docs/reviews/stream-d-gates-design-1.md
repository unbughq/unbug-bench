# Goldfish review: Item 5 scientific receipts and per-gate versions (stream-d.md, 30c9c79)

**Verdict: FAIL.** There are 4 blocking findings, 4 major findings and 4 nits. The direction is right. It uses automatic, content-derived per-gate digests, has no permissive migration, and treats G10 capped attempts as their own outcome. But as written, the design breaks its own headline claim that a plumbing change keeps passes. It also leaves the new G10/G16/G17 failure outcomes undefined.

## Blocking

**B1. The run.py confinement contradicts the plumbing-preservation claim.**
- The design says run.py changes are limited to "the G10 acceptance predicate". Every plumbing leak that matters lives in run.py, outside that predicate:
  - `calibration_identity` (`factory/run.py:2350`) binds `slot`, `role_calls`, `limits` (including `max_cost`, which is set to `None` for jobs at `:3003`, so whether a run is a job changes the identity), and `judge_dependencies`. The design says "G10 attempts use the same scientific dependency boundary", and that requires editing this function.
  - The strategy receipt signature (`run.py:1731`) pins `bench_manifest()` and the whole-file digests of `run.py`, `gate_state.py`, `calibration.py` and `registry.py`.
  - Hashing at function granularity cannot separate plumbing that is written inline in scientific functions. `calibrate` contains `resume_ledger`, budget flags, `model_runtime.prepare_dispatch`, pilot copy/chown and port rewriting. `checkpoint` contains the retry journal and `case_budget_boundary`. `model_call` is an explicit G16 root in `EXTRA_ROOTS`. So a router or ledger edit inside `calibrate` still invalidates G10, G16 and calibration.
- **Fix:** list which run.py functions get split or moved behind the transport boundary, and drop the confinement sentence. Or state which plumbing edits still invalidate passes.

**B2. A refused `wrong_fix` label becomes an infrastructure failure, not "inconclusive".**
- `fairness.verdict` returning `None` makes `independent_review.review` try the next reviewer family. When all families are used up, it raises `InfrastructureExhausted` (`factory/independent_review.py`, last line). So "G16/G17's code validator refuses a wrong_fix label… Such evidence stays inconclusive" would actually do three things:
  - classify a scientific capped attempt as infrastructure, which goes against ENGINEERING §3;
  - spend every reviewer family;
  - feed factory-bug routing.
- Also, `review_inconclusive: counts is None` in `diagnose`/`breadth` is unreachable today.
- **Fix:** define the outcome type. It should be a scientific G16/G17 fail or an explicit inconclusive result that is not infrastructure, with set card fields. Say how the validator tells "malformed reviewer output" apart from "label refused because of capped evidence".

**B3. The failure semantics of the new G10 easy criterion are undefined.**
- The new predicate fails G10 when every easy attempt is capped or not submitted. G10 is not in `repairable` (`run.py:2803`), so this ends the case. The design does not say:
  - what label or detail the card records (too easy, or inconclusive);
  - how diagnosis reads it;
  - how it differs from a demonstrated too-easy case.
- It also rules out a retry allowance. A real artifact already hits this path: public card index 15 in `invalid-runs-public-cards.json.gz` has easy `time_limit: 3`, `no_fix_submitted: 3`, `solved 0`. That card passed G10 under the old rule; under the new rule it would fail with no defined meaning.
- **Fix:** specify the outcome record and its route.

**B4. "Existing byte-identical identities remain reusable" is false, and the cost of the one-time revocation is not stated.**
- Removing `cache` and the plumbing files from `inputs()` changes every existing gate identity. Changing `judge_dependencies` or `calibration_identity` invalidates every saved G10 attempt (`completed_attempts`), stress binding (`run.py:886`) and G16 calibration binding.
- It also invalidates every already-sealed case's delivery proof. `sealed_audit.verify_exam` recomputes `calibration_identity` and `judge_dependencies` and rejects a mismatch as "stale delivery implementation". sealed_audit and verify_exam are not mentioned anywhere in the subsection.
- **Fix:** state which receipts are revoked once, and what that costs in re-runs across in-flight cases. Say whether sealed exam candidates must re-qualify or keep a versioned reader for the old identity. Delete the byte-identical claim or say what it compares.

## Major

**M1. The per-gate inventory is incomplete for an implementer.**
- "The inventory covers every pipeline gate and stress", but `DEPENDENCIES` defines only 9 gates. There is no inventory for G1, G2, G3, G7, G10, G11, G17 or stress, and no key name for stress in `scientific_version(c, gate, bench)`.
- The external files are not classified. Examples: `bin/factory_pool.py`, `bin/diagnostic_budget.py`, `bin/checkpoint`, `bin/checkpoint_evidence.py`, `bin/bench.py` (mixes execution and judging), `factory/free_models.py`, `factory/model_call_gate.py`. `registry.py` is in both the STRATEGY and MODEL lists.
- **Fix:** give a per-gate table of scientific files versus plumbing files.

**M2. "Execution settings" in the receipt is undefined.**
- The scientific version excludes `seed` and `slot`. The design does not say whether the receipt identity still binds `slot`, `bench_workers`, `concurrent_roles`, `max_role_calls`/`max_total_calls`, `max_cost`, or the `UNBUG_FACTORY_SLOT` environment variable. These are all bound today.
- G3 lowers `bench_workers` for memory (`run.py:2211-2216`), and slots change when a case is resumed on another slot. Both are plumbing that would revoke passes.

**M3. Row 39 closure depends mainly on perturbations.**
- Real saved artifacts prove only the no-submission half, and only as content-free counts (card 15 above). The design does not name that fixture.
- No real per-attempt row exists for a capped, submitted, failed attempt, or for a reviewer labelling a capped attempt `wrong_fix`. The fixtures hold no per-attempt `stop_reason`/`guard_submitted` rows; I only found card-level counts. So the "distinct from demonstrated wrong fixes" half rests entirely on authored stop variations.
- "Existing item-3 real-ledger settlement tests" are not named.
- **Fix:** name the exact fixtures and tests. State the residual risk, or defer that half of row 39 to item 8.

**M4. Heilmeier gaps.**
- No cost or timeline: no estimate of the re-run cost from B4.
- No stated payoff measure, for example how many retained passes survive a representative router or ledger edit.

## Nits

- **N1.** Readers recomputing outcomes must map `unrecorded` stops and legacy rows to unknown, never to uncapped. `attempt_summary` notes that "older records cannot … recover most caps". State this explicitly, since the easy criterion depends on it.
- **N2.** If `model_call` moves to the transport boundary, remove it from `EXTRA_ROOTS["G16"]`. Otherwise `source_inputs` raises "missing judge source".
- **N3.** Say that the G8/G9 `compatible_panel` fallback and G16's `calibration_binding` check carry over unchanged.
- **N4.** The "cheat" execution artifact is not in `invalid-runs-provenance.md`, which lists reset-invalid, G11 mixed, plain/reference/refuse-all, silent-window and traffic error. Fix the name or the source.

## Points that hold

- The content-derived digest replacing hand-maintained version numbers.
- No relabelling of old opaque identities.
- Evidence checks that never authorize reuse on missing or tampered evidence.
- G7, G11, G2 and G3 executions kept without revoking other gates' passes.
- Capped solves counted as solves.
- Invalid execution classified as infrastructure before any scientific count.
- Item 6 and lane 1 kept out of scope.

**Result: FAIL.** B1–B4 must be resolved before implementation. I edited no files and did not push or merge.

## Implementation response

Accepted B1–B4 and M1–M4. The revised item-5 subsection names the conservative mixed-code boundary, strategy identity change, exact settings, migration cost and inventories. It removes the unrequested new G10 admission threshold. Capped evidence is detected before paid independent review and returns a scientific inconclusive result, rather than exhausting reviewer families. The public diagnostics stay compatible. Row 39 closure is deferred if the available retained artifacts cannot prove the complete claim; authored cap perturbations will be identified explicitly. N1–N4 are incorporated. No findings rejected.
