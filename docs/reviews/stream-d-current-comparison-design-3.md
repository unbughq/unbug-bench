# Goldfish design review: `docs/designs/stream-d-current-comparison.md` (round 3)

**Review setup:** Mode REVIEW. Personas `zoom_out`, `design_critic` and `implementation_readiness`. Standards `heilmeier-standard.md` and `implementation-readiness-standard.md`. Worktree t3-4ac6b632, branch `t3/stream-d-gates`, HEAD d482653.

I read `docs/ENGINEERING.md`, the three persona files, both standards, the design, and `docs/reviews/stream-d-current-comparison-design-2.md`. I then checked them against these files:
- `diagnosis_dispatch.py`, `diagnosis.py`, `extension_compare.py`, `extension_package.py`, `extensions.py`
- `gate_attempt.py`, `gate_pipeline.py`, `factory_waste.py`, `model_runtime.py`, `model_router.py`, `model_call_gate.py`
- `durable_checkpoint.py`, `recovery.py`, `restart.py`, `coordinator.py`, `factory/run.py`
- the tracked symlinks in the tree

The review was read-only. I made no edits, model calls or git changes, and started no subagents.

**Verdict: BLOCK.** The round-2 fixes hold up against the code. One new blocking finding remains: when the comparison can't finish, the case ends on a stop that nothing automatically relaunches or diagnoses.

---

## Round-2 fixes, checked independently

- **N1 (fixed).** The design now specifies each of these:
  - **Seal trap.** The child rebinds `run.seal` immediately after `setpgid` (line 124).
    - Every child-side `checkpoint_progress(c, seal, …)` call finds `seal` through the module globals when it runs. These are `run.py:200`, `:241` and `:900`. The rebinding therefore catches all three.
  - **`recipient` removed** from the phase context (line 186).
    - The `_opencode` checkpoint is skipped (`run.py:236`).
    - The `_gate_completed` checkpoint is skipped (`run.py:898`).
  - **`stress_checkpoint`** sends a request over the Pipe and returns `remote_durable`. `install_publication_barrier` already prefers this hook (`run.py:195–196`).
  - **The `_opencode` wrapper** (lines 331–337) uses the same condition as the original: not a user call, not a `stress_category_call`. Because `opencode()` looks up `_opencode` as a module global at call time, the child-only rebinding works.
  - **Tests.** The exact-one-checkpoint exams are added at lines 462–466.
- **N2 (fixed).** `CLAUDE.md -> AGENTS.md` is the only tracked symlink (`git ls-files -s`, mode 120000).
  - The new rule materializes it as a regular file: relative link, regular-file target inside the included set.
  - `bench_manifest` hashes content (`run.py:174–177`), so the copy's manifest will equal `c.manifest0`.
  - There is a test on the real repository tree (line 447).
- **N3 (fixed).**
  - **Marker shape.** The marker is the same shape as `stop_infrastructure` (`gate_pipeline.py:162`), plus a `diagnostic` key. No validator requires an exact key set:
    - `recovery.crash_stop` (`recovery.py:22–26`);
    - `diagnosis._input_stop_evidence` (`diagnosis.py:641–645`);
    - `_held_stage` (`diagnosis.py:235–247`).
  - **Diagnosis is queued.** `BudgetError('infrastructure_exhausted')` passes through main's handler (`run.py:3404–3409`), which sets `exhaustion_occurred`. `record_exhaustion` (`diagnosis.py:127–155`) then queues a new pending diagnosis:
    - the completed state is replaced only on a new exhaustion, which this is;
    - the `_trigger` check passes;
    - the last history row has an outcome.
  - **Stress.** Stress correctly uses `stress_validation_exhausted`, which is in `_trigger`, with no marker.
  - **Diagnosis inputs.** Adding `comparison-diagnostics` to the `names` list in `_write_input_tree` (`diagnosis.py:695–698`) is the right seam, and it uses `_input_bytes` safe reads.
- **M1 (fixed).** All three `apply` call sites are named:
  - `replay` (`:286`);
  - the valid-journal branch (`:345`);
  - `invoke` (`:458`).
  The fresh-`invoke` path is tested.
- **M2 (fixed).** `Records.load` raises `extension_snapshot_changed` for tampering and `extension_comparison_pending` for a version mismatch (`extension_package.py:68–100`). §2 states both and does not translate them.
- **M3 (fixed).** The check uses `extensions.tree`, which includes `freshness.jsonl`, and the label is `extension_snapshot_changed`. This matches `verify_proposal` (`extensions.py:441–443`).
- **M4 (partly fixed).** The diagnostic handoff and the factory-bug and close-to-passing loop text are added. However, its premise that pending stops relaunch is false (see B1).
- **M5 (fixed).** The 60-second `kill_tree` allowance and a 30-second total verification window are stated, and a probe timeout counts as survivors present. (Lines 223–224 contain a broken sentence; see the nits.)
- **Round-2 nits:** all addressed. These are `ctypes` `prctl` with errno, the exact rebindings, the copied factory-tree digest, the fail-closed module allowlist, and recording that `comparison_route` should be removed.

Scope constraints hold:
- The opt-in default is False.
- Activation, limits and attribution validators are untouched.
- No Murphy row is closed.
- No existing assertion is weakened.
- Line 59 retains the history-before-card test (`test_dispatch_recovers_history_committed_before_card` in `test_stream_d_execution.py`).

---

## Blocking finding

### B1. A comparison that can't finish ends on a stop nothing restarts or diagnoses
**Severity:** Blocker (design_critic: a founder pit stop on a transient infrastructure fault, against ENGINEERING §3 "an infrastructure failure is retried"; readiness: the recovery route is unspecified)
**Where:** §2 lines 78–85; §4 lines 156, 200–202, 227–228; §5 lines 247–254; round-2 resolution lines 477–486

The design sends many infrastructure faults to "pending":
- unexpected child death (line 202);
- a missing file, a changed source or a bad copy (line 156);
- a fork that is not quiescent (line 124);
- a subreaper failure (line 218);
- an expired cleanup verification window (line 227).

When raised inside the evaluator callable, each becomes `InvalidInfra`. `snapshot` turns that into a pending row (`extension_compare.py:205–206`), `compare` returns `'pending'`, and `subsequent_entry` raises `extension_comparison_pending`. From there:

- **No diagnosis.** Main records `terminal_stop='extension_comparison_pending'`. `record_exhaustion` returns without queuing a diagnosis, because this label is not in `_trigger` (`diagnosis.py:51–54`).
- **No relaunch.** `coordinator → restart.plan → recovery.require_restart_stop` rejects the label: it is not matched by `recovery.RETRY` (`recovery.py:11`), it is not a crash, a freshness retry or a raised limit. The result is "stop needs a repair or budget decision" (`recovery.py:199–202`).
- **A crash has the same result.** `apply` has already set `status='stopped', terminal_stop='extension_comparison_pending'` on the live card (`diagnosis_dispatch.py:232`), and nothing on the comparison path clears it. Every parent checkpoint during the comparison therefore seals a card with that stop. If the VM or runner dies mid-comparison, the last checkpoint cannot be relaunched either.

The phase `gate_attempt` journal does not save this. §5 has the child run `execute` and "send an exhaustion message". A child that dies, or a setup check that fails, never reaches that journal, so no attempt is counted and no exhaustion is raised.

The design's recovery claims (lines 477–479 and M4's "every pending stop needs a coordinator relaunch") rest on a relaunch that does not exist for this label. A single OOM kill, Docker hiccup, or leftover thread after the in-process diagnosis call (see M2) therefore stops the case with no automatic route.

Unverifiable retained scores hit the same dead end. This is the case kept "pending, never re-evaluated" at lines 81–82, matching `extension_compare.py:291–294`. It is permanent, so it can never resolve. Round 2 M2 already argued that this kind of stop should end cleanly as an evidence stop instead.

**Fix (smallest that closes it):**
1. **Run `gate_attempt.execute` in the parent.** Its `invoke` sends the stage request over IPC and waits for the reply. Child death, IPC failure and per-phase setup failure (copy or manifest check, fork precondition, subreaper, cleanup quiescence) then raise `InvalidInfra` *inside* `invoke`. Each one is counted in the phase `infra-attempts.json`, and a retry starts a fresh phase child, with G3 setup run again as in §5. After `attempts=2` it reaches the existing §5 exhaustion route: a G marker plus `infrastructure_exhausted`, or `stress_validation_exhausted`. Both lead to diagnosis. No new allowance is needed.
2. **Give every remaining pending source of `subsequent_entry` an existing automatic route, and list them.**
   - A retained, previously scored pair that fails verification: after `compare` returns `'pending'`, re-select with `comparison_pair`. If the selected pair is a retained pair that is not pending, raise `extension_snapshot_changed`, which is an evidence stop.
   - Version drift between phases, or between start and finish: propagate as an `InvalidInfra`-counted attempt as in (1), or state the retryable label used.
   - Unresolved stress freshness: name the existing route, `freshness_evidence_unavailable` or whatever ordinary stress uses, or state explicitly why a hold is correct.
3. **Exams:**
   - A forced child death on each attempt, run through `finalize_accounting → record_exhaustion`, ends with a pending diagnosis.
   - A single child death followed by success produces a scored pair with no relaunch.
   - For every pending source of `subsequent_entry`, either `restart.plan` accepts the sealed card or `queued_inputs` succeeds. A non-retryable `extension_comparison_pending` is never the end state.
   - A mid-comparison checkpoint card can be relaunched by `require_restart_stop`, or the design states which label the parent sets before the first checkpoint.

---

## Major (non-blocking, should fix)

**M1. "owner.card" names the wrong object in the code** (§5 lines 255–259; §4 lines 169–172; §6 line 327)
- In `extension_package.entry` (`:421–426`), the local variable named `owner` is a copy whose `card`, `args` and `models` are deep copies. `compare` also works on its own `owner` copy (`extension_compare.py:251–252`).
- If the infrastructure marker, the cleared `c.early['G3']` and the parent checkpoint go to either copy, the marker never reaches `c.card`. The diagnosis then finds `infrastructure_exhausted` with no marker, `_input_stop_evidence` raises, and the case lands on `diagnosis_input_invalid`. That is N3's failure again.
- **Fix:** state that `entry(c, r)` calls `subsequent_entry(c, r)` with the **live** runner context, at the current `if extensions.read(owner)` line and before that function's `try`. Otherwise its `EVIDENCE_STOPS` handler converts the evidence stops back into pending. State also that the marker, the `early` reset and the checkpoints all use that live `c`. The exam at lines 488–491 will catch a mistake, but the text should not invite one.

**M2. The fork precondition will fail after the same-process diagnosis call** (§4 line 122)
- The expected path diagnoses and compares in one launch (line 477).
- Two threads from the diagnosis call can outlive it:
  - `model_call_gate.Gate.close` joins its server thread with `timeout=1`, and handler threads are daemons (`model_call_gate.py:595–606`);
  - the router renew thread joins with `timeout=6` (`model_router.py:538–542`).
- `threading.active_count() == 1` can therefore be false when `admit_extension` runs. Under the current text that becomes an uncounted `InvalidInfra`, which feeds into B1.
- **Fix:** allow a bounded wait for quiescence before refusing, with an explicit limit (for example 30 s), and count a refusal as an attempt under B1 (1). Test it: a leftover daemon thread that exits within the bound is accepted, and one that outlives the bound is counted and retried.

**M3. A factory-bug resume after a comparison crash does not return to the comparison** (lines 482–484)
- The text says a factory-bug decision "uses the existing held/fix workflow". But `resume_factory_bug` removes `diagnosis_state` and `infrastructure_gate` and returns True (`diagnosis.py:540–545`). `_dispatch` then returns False, so main takes `extension_id is None → build(c)` and `validate_and_repair` (`run.py:3392–3403`) on the live case.
- On that path:
  - `admit_extension` can never run, because it needs a completed `close_to_passing` state;
  - the comparison never resumes;
  - the ordinary build and repair loop runs on a case with extension history.
- This gap predates this design and affects every post-extension factory bug. This design adds a new way to produce one.
- **Fix:** either specify the resume target (a comparison identity that a later admission must finish), or record it as a branch Murphy row, `new-stream-d-current-comparison-1`, and remove the claim that the existing workflow covers it.

---

## Nits

- **Lines 223–224:** "repeat until no descendants remain, and / Each kill_tree retains …" is a broken sentence. Rewrite it as two sentences.
- **Lazy setup (§4 and §6, lines 341 and 406–407):** say that copy installation, subreaper enablement and manifest checks happen on the first evaluator call, not in `__enter__`. This keeps the completed-pair fast path free of setup, and means it won't recreate a bench copy that cleanup removed (lines 346–349).
- **Which module "run" means:** in production it is `sys.modules['__main__']`. `diagnosis.py:518` and `extension_package.py:300` can import a second `run` module. Say that the child applies the `seal` and `_opencode` rebindings to the runner object `r`, and also to `sys.modules['run']` if it is loaded.
- **Shared Docker image tag:** compose uses the fixed project name `unbug-bench` and image tag `unbug-bench-medusa:latest` (`projects/medusa/compose.yaml:1,30`). A G3 run from the private copy rebuilds the shared tag from the copied context. Because the manifests are equal this should be content-identical, but mention it next to the "shared Docker, sequential" note (lines 166–173).

## Heilmeier and readiness

- **Heilmeier answers present:**
  - objective in plain words (lines 442–444);
  - current state and limits (lines 17–22);
  - approach;
  - risks (lines 24–28);
  - cost: engineering cost plus checks under the existing money bound, with no offline cost claims;
  - timeline: one cycle;
  - midterm and final exams (lines 436–437).
- **Readiness:** the phases are two stable commits, then the full suite, then a diff review. The file list is explicit.
- **What still fails readiness:**
  - B1: no route out of pending for infrastructure faults;
  - M1: which object receives the marker, the G3 reset and the checkpoints.
- **Zoom-out:** no new subsystem is added beyond the evaluator. Reusing `gate_attempt` in the parent (B1 fix 1) removes the separate child-to-parent exhaustion message instead of adding a route.

**Result: BLOCK** (B1).

## Writer disposition

Accepted B1 and M1–M3. Parent-owned attempt accounting replaces child retry/exhaustion messaging; live runner context and all pending/error/checkpoint routes will be explicit. The pre-existing post-extension factory-bug resume target gap is recorded as an open obligation rather than claimed solved. Fresh review required.
