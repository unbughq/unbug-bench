# Goldfish design review: `docs/designs/stream-d-current-comparison.md` (round 2)

**Review setup:** Mode REVIEW. Personas `zoom_out`, `design_critic` and `implementation_readiness`. Standards `heilmeier-standard.md` and `implementation-readiness-standard.md`. Worktree t3-4ac6b632, branch `t3/stream-d-gates`, HEAD fa89a43. I read the design and round-1 review, then checked them against `diagnosis_dispatch.py`, `extension_package.py`, `extension_compare.py`, `extensions.py`, `gate_state.py`, `gate_attempt.py`, `gate_pipeline.py`, `factory_waste.py`, `diagnosis.py`, `durable_checkpoint.py`, `run_artifacts.py`, `coordinator.py`, `factory/run.py`, `bin/run_validity.py`, `bin/processes.py`, `bin/boat-bake` and the tracked tree. The review was read-only: no edits, no model calls, no git changes.

**Verdict: BLOCK.** The six round-1 fixes hold up when checked against the code. There are 3 new blocking findings.

---

## Round-1 fixes, checked independently

- **B1 (fixed).** §1 now has `apply` return `0` under opt-in plus `DIAGNOSIS_ENABLED`, whatever state the old pair is in. `admit_extension → entry → subsequent_entry` is the only producer. There is no `ComparisonRequired` and no second entry call.
  - A resolved old pair at stale versions now goes through `compare` at the current vector, so it cannot slip past.
  - `propose` (`extensions.py:384–406`) still re-selects the pair and requires `case_sha256/stages/frontier/evidence` equality. That makes the `source_generation`-only rebind sound.
- **B2 (fixed).** `gate_state.py` and `scientific_version` are unchanged. `Records(expected_versions=…)` is used only by the evaluator. Side observation: `scientific_version` already pops `bench_workers` and `concurrent_roles` (`gate_state.py:211`), so serial child args cannot change the stress/args part of the version.
- **B3 (fixed, but see N2).** The source and the installed copy are both checked against `c.manifest0`, and the copy predicate shares one helper with `bench_manifest`. G1's `manifest_expected=c.manifest0` (`run.py:1853`) therefore sees a content-identical tree.
- **B4 (fixed).** `run_validity` is never evicted, and the identity assertion is specified. Only `bench`, `factory_pool` and `claims` are evicted. That covers today's in-process imports: `live_shop`, `live_traffic` and `refusal` bind bench paths at load time, but factory code imports them only in subprocesses.
- **B5 (fixed).** The design specifies:
  - `setpgid(0,0)` with an acknowledgement;
  - `killpg(child.pid)`, never the parent's own group;
  - a subreaper with the correct constants (36 set, 37 get);
  - a numeric `ps` sweep, `stop_pilot` for cross-user processes, and a single-thread precondition.

  The threads named in round 1 (router renew at `model_router.py:538`, call-gate at `model_call_gate.py:595`) exist only during calls.
- **B6 (fixed).** `comparison=True` forces `link=None`, so neither `resume_scope` nor `classify` runs.
  - The only `attempt()` openers today are `gate_pipeline.py:52` and `run.py:1592`. Direct `r.gN` calls go through neither, so the evaluator really is the only owner of the comparison scope.
  - `Attempt.publish` with `link=None` writes only InvalidInfra proofs, into `factory-failures`.

The scope constraints also hold. Existing tests keep their assertions, the extension limits and activation are untouched, no Murphy rows are closed, and the opt-in default is False.

---

## Blocking findings

### N1. The child's automatic checkpoint seam is not specified, and the obvious implementation overwrites the live checkpoint
**Severity:** Blocker (design_critic: wrong result and data loss; readiness: decision left to the implementer)
**Where:** §6, lines 284–300; §4, lines 163–168

The phase context is a shallow copy of the owner, so it inherits `recipient` and `ledger`. Inside the child, ordinary code calls `durable_checkpoint.checkpoint_progress(c, seal, …)` itself from two places:
- after every serial model call, at `run.py:236–241`. This applies whenever `hasattr(c,'recipient')`, it is not a dry run, and there is no `calibrator_slot_offset` or `stress_category_call`;
- in the stress publication barrier at `run.py:193–200`, unless `c.stress_checkpoint` is set.

`seal` is `RunArtifacts(HOME, BENCH, SEALED, …).seal` (`run.py:2958–2964`). In the child it would do four things:
- tar the **phase** work and **phase** card;
- move the private copy's `results/` into the phase work;
- copy pilot homes;
- write `~/sealed/<case_id>.checkpoint.tar.gz.age` and upload it to the case's R2 object.

That replaces the authoritative owner checkpoint with a phase archive. A later restore would bring back comparison scratch as the case work.

The design says this checkpointing "is replaced with this parent callback, not disabled without replacement", but it never names the seam. The §8 test only checks the parent side.

**Fix:**
- As the child's first step after `setpgid`, rebind `run.seal` to a stub that raises `RuntimeError('child seal')`. That one global covers the call sites at 200, 241 and 900.
- Set `c.stress_checkpoint` on the phase context to a function that sends the checkpoint request over the Pipe and returns the parent's `remote_durable` boolean.
- Remove `recipient` from the phase context, so the `_opencode` boundary is skipped explicitly rather than by accident. After each completed model call, the evaluator sends the checkpoint request itself, through the existing `on_complete` / effects message.
- Test: a child G2 model call and a stress publication each cause exactly one parent `checkpoint_progress(owner, r.seal, …)`. The child process writes nothing under `SEALED` and makes no R2 call. The owner card in the archive has no phase keys.

### N2. "Any symlink in the included source set is InvalidInfra" makes every comparison on a real bench InvalidInfra
**Severity:** Blocker (permanent pit stop; real-artifacts rule)
**Where:** §4, lines 132–141

`CLAUDE.md` is a tracked symlink at the bench root (`git ls-files -s` shows mode `120000`, pointing to `AGENTS.md`).
- `bench_manifest` includes it: `f.is_file()` follows the link, and `CLAUDE.md` matches none of the exclusions (`run.py:176`).
- `bin/boat-bake:40–44` builds worker benches with `tar -C "$root" … .`, which keeps symlinks.

So every real worker bench has a symlink in the included set. Under the stated rule, every comparison raises InvalidInfra and ends pending, which in turn leads to infrastructure exhaustion. None of the tests would catch this, because they use the saved practice fixtures rather than the real bench tree.

**Fix:**
- A **relative** symlink whose fully resolved target is a regular file inside the included set is copied as a regular file holding the target's bytes. `bench_manifest` hashes content, so the copy's manifest still equals `c.manifest0`.
- An absolute link, an escaping link, a dangling link, a directory link, or a link to an excluded path is InvalidInfra.
- Never create a symlink in the copy.
- Add a test that runs the copy and manifest check over the real repository tree, including `CLAUDE.md`, and asserts equality with `bench_manifest()` of the source.

### N3. The infrastructure-exhaustion route does not say whose card carries the marker, what shape it has, or what happens for the `stress` stage
**Severity:** Blocker (readiness; a terminal invalid state)
**Where:** §5, lines 226–233

"Set its existing `infrastructure_gate` to the stage" leaves three things open:
- **Which card.** The child's card is never copied back, because effects carry no terminal labels.
- **What shape.** Diagnosis validates `card['infrastructure_gate']` with `marker['exhausted'] is True` and `marker.get('gate') in GATES` (`diagnosis.py:641–645`). `_held_stage` reads the same field (`diagnosis.py:236–239`).
- **The stress stage.** `extensions.stages()` starts with `'stress'`, and `'stress'` is not in `run.GATES`.

As written, a missing marker, a wrongly shaped marker, or `gate='stress'` makes `queued_inputs` raise. The case then lands on `diagnosis_input_invalid`, which is terminal and is not an exhaustion. The ordinary stress path never uses this marker. It raises `BudgetError('stress_validation_exhausted')` instead (`stress_progress.py:65,104,164`), which is a `_trigger` stop.

**Fix:**
- For a G stage, the **parent** sets `c.card['infrastructure_gate'] = {'gate': stage, 'error_type': …, 'classification': 'invalid-infra', 'exhausted': True}` on the owner card. This is the shape `gate_pipeline.py:162`'s `stop_infrastructure` uses. It then raises `BudgetError('infrastructure_exhausted')`. Any phase-local diagnostic path goes in an extra key.
- For `stress`, raise `BudgetError('stress_validation_exhausted')` and set no marker.
- Test both cases through `finalize_accounting → record_exhaustion → queued_inputs`, and assert that a pending diagnosis is queued rather than `diagnosis_input_invalid`.

---

## Major (non-blocking, should fix)

**M1. Name every `apply` caller that must forward `comparison_route`** (§1, lines 32–34)
- `apply` is reached from three places: `replay` (`diagnosis_dispatch.py:281`), `_dispatch`'s valid-journal branch (`:337`) and `invoke` (`:442`). The `invoke` path is the common one, for a fresh diagnosis.
- "Forwarding through the dispatch/replay chain" does not clearly include `_dispatch → apply` or `_dispatch → invoke → apply`.
- If those are missed, the first close-to-passing decision still hits the old hold. The case then needs a coordinator relaunch, and `coordinator.py` stops at `len(actions) >= 3` with `launch_allowance_exhausted`. List all three call sites and test the fresh-`invoke` path under opt-in.

**M2. Reused `Records.load` raises instead of returning pending** (§5 line 216; §8 line 362)
- `Records.load` raises `refuse()`, which is `BudgetError('extension_snapshot_changed')`, for a tampered envelope or support file. It raises `refuse('extension_comparison_pending')` for a version mismatch (`extension_package.py:66–98`).
- `compare` lets that BudgetError propagate (`extension_compare.py:201–203`), so the "stays pending" test would fail as written.
- Decide which behaviour is wanted and state it:
  - **(a)** Let it propagate as the evidence stop `extension_snapshot_changed`. This is recommended: it ends the case cleanly, rather than holding it pending and re-launching it against bytes that will never verify.
  - **(b)** Translate it to InvalidInfra, which means pending.

**M3. Live case mismatch in `subsequent_entry` has no label** (§2, lines 64–65)
- Use `extension_snapshot_changed`, which is the label `verify_proposal` already raises for the same condition (`extensions.py:430–432`).
- Note that `extensions.tree` includes `freshness.jsonl` but `case_hash` does not, so state that the check uses `extensions.tree`.

**M4. Relaunch dependency and the unchanged-runtime exhaustion loop** (§5; Heilmeier Cost and Timeline)
- Every pending stop needs a coordinator relaunch, and the allowance is 3 per case (`coordinator.py`).
- The `retry` key includes `runtime_revision()` (`run_validity.py:66`). On an unchanged runtime, an exhausted comparison journal re-raises at `start` without invoking anything. That gives a loop: diagnosis, then close-to-passing again, then immediate re-exhaustion, then another diagnosis. It ends only at `launch_allowance_exhausted`, which is a founder pit stop.
- The diagnosis input tree's work list (`diagnosis.py:694–697`) does not include `comparison-runs/`, so the diagnosis agent never sees the phase crash diagnostics. It sees only the marker and the `factory-failures` proofs.
- State how many launches are expected. Either add the phase `gate-details/*.crash-*.json` and the phase `infra-attempts.json` to the diagnosis inputs, or state that the `factory-failures` proofs alone are enough evidence to classify `factory_bug`.

**M5. The cleanup bound is ambiguous** (§4, line 199)
- `processes.kill_tree`'s `ps` probe deliberately allows 60 seconds (`processes.py:68–69`: "a short bound would skip every descendant").
- Say whether the 30-second refusal bound is a total wall-clock limit that starts after the last `kill_tree`, or a per-iteration limit. Say also that a probe timeout counts as "survivors present", which means InvalidInfra.

## Nits

- Python has no `os.prctl`. Specify `ctypes.CDLL(None, use_errno=True).prctl`, and say that a non-zero return or `errno` means InvalidInfra.
- "Set `parallel_calibrators` and `g10_overlap_reason` to serial choices": give the exact child-only rebinding, for example `run.parallel_calibrators = lambda c: False` and `run.g10_overlap_reason = lambda c: 'comparison serial'`.
- The copied `factory/` tree sits outside `bench_manifest` (the regex excludes `factory/` except `case_permissions.py`), so nothing checks its integrity. State what verifies it, such as the launch manifest or a digest of the live tree.
- On the eviction allowlist: add a child assertion that no module other than `run_validity` and `processes` in `sys.modules` has a `__file__` under the live `bench/bin` and is bound to bench paths, so that a future in-process import of `live_shop` gets caught.
- On zoom-out: the `comparison_route=False` default is dead in production, because `run.py:3347` is the only production caller and it opts in. It exists only so the existing guard tests keep passing. That is acceptable under the brief, but record that it should be deleted once item 7 is complete.

## Heilmeier and readiness

- The objective is now stated in plain words (line 399).
- The risks, the cost (engineering cost plus checks only, under the existing money bound) and the midterm and final exams are present.
- The timeline is one design and implementation cycle.
- The phases are two stable commits, then the suite, then a diff review, and each phase leaves the code testable.
- The file list is explicit.
- Readiness fails only on N1–N3 and M2–M3, where the implementer would still have to choose behaviour.

**Result: BLOCK** (N1–N3).

## Writer disposition

Accepted N1–N3 and M1–M5. The next revision specifies child checkpoint interception, safe materialization of included relative file symlinks, exact parent diagnosis markers, every routing call site, evidence refusal labels, retained diagnostic inputs, and cleanup timing. Nits are also incorporated. A fresh review must verify these changes.
