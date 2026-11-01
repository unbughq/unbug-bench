# Goldfish design review: `docs/designs/stream-d-current-comparison.md`

**Review setup:** Mode REVIEW, personas `zoom_out`, `design_critic` and `implementation_readiness`, standards `heilmeier-standard.md` and `implementation-readiness-standard.md`. I read the design in the t3-4ac6b632 worktree (branch `t3/stream-d-gates` at fe182c2) against the code it cites: `diagnosis_dispatch.py`, `extension_compare.py`, `extension_package.py`, `extensions.py`, `gate_state.py`, `gate_attempt.py`, `factory_waste.py`, `model_runtime.py`, `durable_checkpoint.py`, `run.py`, `bin/run_validity.py` and `projects/medusa/compose.yaml`.

**Verdict: BLOCK.** There are 6 blocking findings. Each one has a concrete fix below.

---

## Blocking findings

### B1. Two routes reach the same producer, and the design does not say which one may run checks
**Severity:** Blocker (zoom_out and readiness)
**Where:** §1, lines 37–57; §2

When the old pair is resolved, `apply` still returns `0`, and main then calls `admit_extension`. That calls `entry`, which calls the new `subsequent_entry`, which calls `extension_compare.compare` at the current versions (lines 43–44 and §2). If the version vector has changed since the old pair, this is the first run at that vector, so `entry` must run the checks inside `admit_extension`.

Line 55 says only the "second entry call … cannot evaluate it again". That leaves two readings:

- **`entry` may run checks.** Then `ComparisonRequired` and `compare_entry` add nothing. They run the same producer at the same point in main (`run.py:3386–3391`, after model selection and before build or admission). The authority, diagnosis, limit and active-row checks already run in `admit_extension`, `propose` and `verify_proposal`. That means two paths and two "entry" calls where one would do, which goes against "One launch path" and "Delete before adding".
- **`entry` may not run checks.** Then a resolved old pair at stale versions returns `0` and is never compared at the current vector. It stays `extension_comparison_pending` forever, which is a permanent pit stop.

**Fix (preferred):** Delete `ComparisonRequired` and `compare_entry`.
- Under `comparison_route=True` and `DIAGNOSIS_ENABLED`, the completed/other-exhaustion branch returns `0` whatever the old pair's state.
- `entry` (in `subsequent_entry`) becomes the only producer, and it may run checks.
- It raises `extension_comparison_pending` before `propose`, `writer_request` or `pending_call`.
- Without opt-in, keep the existing hold exactly as it is.

This still replaces the lane-1 boundary explicitly, and the old non-opted-in tests stay as they are.

**Alternative:** Keep the typed route, but state that `entry` never starts the evaluator. In that case `apply` must return `ComparisonRequired` whenever no completed pair exists at the *current* vector, not the retained outcome vector. That needs `apply` to compute current versions, which is why the preferred fix is simpler.

### B2. Version normalisation invalidates the gate cache for live ordinary runs, and the design says it does not
**Severity:** Blocker (no rerolls, accounting)
**Where:** §3, lines 89–95

`gate_state.load` (`gate_state.py:267–268`) rejects any cache record whose stored `scientific_version` differs from the current one. `save` stores `scientific_version(c, gate, bench)` (line 253).

`bin/factory_pool.py` is in `MEASURE`, and `MEASURE` covers every gate in `REUSABLE` (G4, G5, G6, G8, G9, G13, …). Today, when `bench_workers == 1`, the pool file is left out of the version. If `scientific_version` starts including it, every existing cache record made with one worker stops matching once this plumbing rolls onto running cases. Those gates would then re-run, with new spend and a stochastic re-roll of passes that were already cached.

That contradicts "Normal cache fingerprints retain their existing behavior" (line 92). It also breaks §3's target property that "a gate change re-runs only the gates that changed". It also invalidates first-entry records and retained snapshot vectors made with the old function.

**Fix (pick one and state it):**
- **(a) Delete §3's version change and the `execution_args` change.** Run comparison phases with the owner's `bench_workers` and `concurrent_roles`. The workers are this job's prepared slots, and children run one at a time.
- **(b) Leave `scientific_version` unchanged.** Inside the evaluator, check each Records version against the vector `compare` pinned for that stage (pass it in), not against a version recomputed from the child's runtime args.

Either way, add a regression test: a cache record saved by the current code with one worker must still load after the change.

### B3. A bad private bench copy becomes a scored G1 failure instead of an infrastructure stop
**Severity:** Blocker (infrastructure failures must never be scored; isolation)
**Where:** §4, lines 125–134

G1 runs `CaseContract.inspect(..., manifest_expected=c.manifest0)` (`run.py:1848–1853`). If they differ, `case_contract.py:214` returns the problem "bench files were changed", which is a scored G1 **fail**.

In the child, `run.BENCH` points at the copy, but the runtime context inherits `manifest0`, which was computed on the live bench (`run.py:3374`). Any gap in the copy would produce a scored fail, which leads to `no_progress` or `regression` and then retirement. Possible gaps:
- a skipped symlink ("Do not follow source symlinks" does not say whether a link is skipped, preserved or rejected);
- an exclusion list that drifts from `bench_manifest`'s regex;
- a live bench edit between the manifest snapshot and the copy.

Checking only the scientific vector (line 130) does not cover this, because the vector excludes most manifest files.

**Fix:**
- After installing or checking the copy, require `run.bench_manifest()` over the copy to equal the owner's `c.manifest0`. A mismatch means `InvalidInfra`, so the result is pending.
- Define the symlink rule exactly. Recommended: any symlink in the source outside the excluded directories is `InvalidInfra`. Never preserve links, because an absolute link would point back into the live bench.
- Take the exclusion list from the same regex `bench_manifest` uses, rather than a second hand-written list.
- Add a test: a copy with one missing file must give a pending result, not a G1 fail.

### B4. Evicting bin modules breaks exception identity, because `run_validity` lives in `bin/`
**Severity:** Blocker (readiness: two rules contradict each other)
**Where:** §4, lines 117–121

`InvalidInfra` and `InfrastructureExhausted` come from `bin/run_validity.py`. Some factory modules import them at load time (`extension_compare.py:20`, `extension_package.py:16`, `independent_review.py`, `freshness_retrieval.py`, `ordinary_freshness.py`). Others import them lazily inside functions (`gate_attempt.py:22`, `calibration.py`, `fairness.py`, `factory_waste.py:58`, `gate_pipeline.py:58`).

If modules from the original `bin` are evicted, the lazy imports in the child load a second `InvalidInfra` class from the copy. An `except InvalidInfra` written against the first class will not catch it. For example, `snapshot`'s handler would miss it, and so would `factory_waste.Attempt.publish`'s `isinstance(error, InvalidInfra)` check. The infrastructure failure then turns into a "diagnostic RuntimeError" or an unattributed error. That contradicts "preserve the original … exception classes" (line 121). `run_validity` also holds module state (`_lock`, and the `runtime_revision` cache keyed off `__file__`).

**Fix:**
- Never evict `run_validity`.
- Evict only the bin modules whose module-level state resolves bench paths and which no factory module has already bound at fork time. Name them explicitly: `bench` (`ROOT`), `factory_pool` (`__file__` cwd/results) and `claims`.
- Assert in the child, after setup, that `run_validity.InvalidInfra is extension_compare.InvalidInfra`.
- Add a test: a child gate raises `InvalidInfra` from a lazy import, and the result is pending, not a RuntimeError.

### B5. Child processes are not contained, so the "no descendants" rule cannot be enforced
**Severity:** Blocker (process recovery and isolation)
**Where:** §4, lines 111–114 and 162–165

A child from `multiprocessing` fork stays in the parent's process group. "Terminate/join the child and its process group" would therefore signal the parent itself, unless the child first calls `os.setpgid(0, 0)` (or `setsid`), and the design does not say it does.

Even with its own group, the model CLIs are started with `start_new_session=True` (`budget.py:1177`), so they leave the group. Pilot and calibrator processes run as other OS users (`make_pilots`), so a non-root `killpg` cannot reach them.

As written, the rule at line 165 ("Do not start a second phase while the first has descendants") has no mechanism. A leftover CLI or pilot could keep writing into phase work after the next phase starts, or after the case moves on to ordinary execution.

The fork-safety precondition also covers only "no active model calls and no G10 executor". It does not cover other threads that might be holding locks: the router renew threads (`model_router.py:538`) and the `model_call_gate` server thread (`:595`).

**Fix:**
- The child calls `os.setpgid(0, 0)` first.
- The parent kills by `os.killpg(child.pid, SIGKILL)`.
- Before the next phase, the child's own `finally` runs the existing cleanups (`dispose_diagnosis_pilot` / pilot disposal, and `budget`'s `killpg` of CLI sessions).
- The parent then checks that no process in that session or group remains, and that no pilot user processes remain, using the same check the ordinary pilot teardown uses. If anything survives, the result is `InvalidInfra` (pending), and no new phase starts.
- Gate the fork on `threading.active_count() == 1` (or an explicit allow-list). Otherwise the result is pending.
- Add a test: a child leaves behind a detached grandchild, and the next phase does not start.

### B6. Comparison attempts can be linked to an old factory-bug resume and classify it
**Severity:** Blocker (factory-bug attribution must not change)
**Where:** §6, lines 217–222

`factory_waste.Attempt.__init__` calls `resume_scope(c, stage, case_sha256)` (`factory_waste.py:219–235`). It reads `factory-bug-resumes.json` from `c.work` and links to the last admission when that finding's failure receipts have the same stage and case hash.

The design runs comparison attempt scopes with `work=accounting_work`, which is the owner's root, and with `case_sha256` set to the evaluated revision. The last extension's outcome case often equals the case a factory bug was resumed on. When it does, a comparison G-stage under that scope publishes into `factory-replays` with the old `resume_id` and calls `classify(...)`. That rewrites factory-bug attribution from comparison work.

"Do not reclassify comparison spend" (line 221) does not say whether this link is allowed. That leaves the decision to the implementer, on the money and attribution path.

**Fix:**
- State that comparison attempt scopes never link to a factory-bug resume (`link=None`). They may only publish `factory-failures` proofs for their own `InvalidInfra`.
- Add a test using a saved factory-bug resume fixture whose failure receipt matches the outcome case and stage. Comparison must write no `factory-replays` entry and must not call `classify`.
- The existing factory-bug attribution tests stay unchanged.

---

## Major (non-blocking, should fix)

**M1. Infrastructure exhaustion leaves the case pending forever** (§5, line 177)
- Once the phase `infra-attempts.json` has used both attempts, `run_validity.retry` raises `InfrastructureExhausted` on every resume. The comparison stays pending indefinitely and the case is held in `extension_comparison_pending` with nothing to resolve it, which is a pit stop.
- Fix: name the terminal route, e.g. stop with the existing infra/factory-failure label so that diagnosis can classify it as a factory bug, instead of reusing `extension_comparison_pending`.

**M2. The `gate_attempt.execute` callbacks are unspecified** (§5, line 173)
- `publish` and `record_crash` are required arguments, and the design gives neither.
- Fix: state that `publish` forwards an operational event to the parent (and never writes card gate status), and that `record_crash` writes a phase-local diagnostic.

**M3. How the evaluator tells phases apart is unspecified** (§4)
- `compare` calls `evaluate(w, stage)` with a temporary `Workspace` and does not pass a phase.
- Fix: specify the mapping, e.g. `w.work.parent.name in {'entry', 'outcome'}`, checked against `original[phase]['case_sha256']`. Also say what happens if the entry and outcome case hashes are equal.

**M4. Shared Docker project after comparison**
- `compose.yaml` has the fixed project name `unbug-bench`, a named volume and a shared image tag. Child G3 re-seeds the shared database and rebuilds `unbug-bench-medusa:latest` from the copy, while the live `seed-ids.json` no longer matches the database.
- Fix: state that ordinary execution after comparison must not reuse an earlier live G3 preparation. `extension_package.run` already pops `early['G3']`; say so and test it.

**M5. Cleanup changes the shared machine and archive**
- §6 puts the whole private bench copy (about 15 MB or more) into every checkpoint seal until cleanup runs.
- That is acceptable, but state the expected size and confirm it stays within the R2 upload limits.

## Nits

- Line 59 cites `stream-d-outcome-routes.md` lines 60–67. The block that is replaced is the table row at line 60 plus the "Merge correction" paragraph at lines 62–73.
- §2 re-verifies receipts on the fast path, but `compare` already does that (`extension_compare.py:276–279`). Reuse that check rather than adding a second one.
- On Heilmeier: the objective is full of jargon, and "who cares" is only implied. One plain sentence would cover it: "decide automatically, without rerunning anything already scored, whether the last extra writer round moved the case forward".
- Tests that fork on macOS can crash under the Objective-C fork-safety check. State which platform the process-isolation tests run on.
- `compare` evaluates the outcome phase even after the entry phase came back pending. The durable records make that resumable, but it is wasted spend. Note it, and leave `compare` as it is.

## Confirmed sound

These are consistent with the code:
- the opt-in default (`comparison_route=False`) and the requirement that `DIAGNOSIS_ENABLED` be set;
- activation stays false and limits are unchanged;
- `propose` and `verify_proposal` are mandatory, and the source-generation rebind matches `propose`'s key comparison and `_entry_evidence_root`'s location rule;
- missing or tampered retained proof stays pending, so there is no reroll (`extension_compare.py:285–288`);
- original snapshots and history are left immutable;
- G2 freshness changes are confined to the phase copy (`case_hash` excludes `freshness.jsonl`);
- shared ledger and usage receipts via `accounting_work`;
- the phasing into two stable commits, then the suite, then a diff review;
- no Murphy rows are closed.

**Result: BLOCK** (B1–B6).

## Writer disposition

All six blockers accepted. The revised design removes duplicate routing and version normalization, validates private bench integrity, preserves run_validity identity, specifies process containment and cleanup, and excludes comparison from old factory-bug replay links. Majors M1–M5 and the nits are addressed in the revision. No blocker is self-verified; a fresh review follows.
