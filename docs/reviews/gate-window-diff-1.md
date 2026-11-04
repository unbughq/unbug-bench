# Goldfish review: gate-window diff 1 (verbatim)

Reviewer: fresh general-purpose subagent (Claude opus), personas zoom_out and implementation_readiness; Mode: REVIEW; standard implementation-readiness. Reviewed `git diff HEAD~1 HEAD` at 9ffc6f4.

---

# Goldfish review of 9ffc6f4 (Mode: REVIEW)

**Verdict: BLOCKING.** The window change and the G14 wiring are sound. One claim in the design is false: existing G13/G15 receipts do not stay valid.

## Findings

1. **[blocking] The G13/G15 binding is not byte-identical in value, so every existing receipt is invalidated.**
   - The identity dict is built the same way (`factory/run.py:1907` vs the old inline `signature()`). But its `inputs` field comes from `gate_state.inputs` -> `runner_inputs(gate)` (`factory/gate_state.py:162`). That field hashes the AST source of `g13`/`g15` and every same-module name they reach (`gate_state.py:58-87`).
   - `strategy_run`'s source changed (`run.py:1946`) and `strategy_binding` is now in its closure. I compared `source_inputs` at HEAD against `git show HEAD~1:factory/run.py`:
     - `g13 DIFF ['strategy_binding', 'strategy_run']`
     - `g15 DIFF ['strategy_binding', 'strategy_run']`
   - On deploy, three things go stale for every case: all `strategy-*-checkpoints` receipts, the whole-run evidence reuse in `strategy_run`, and the G13/G15 `gate_state` pass fingerprints. The failure is safe (it redoes work, never reuses it falsely), but it contradicts `docs/designs/gate-window.md:28-29`. It also redoes hours of G13/G15 work on in-flight cases, against the salvage rule.
   - Fix, pick one:
     - Leave `strategy_run` byte-for-byte unchanged (keep its inline `signature()`), and have only `g14` call a new binding helper. G13/G15 then really are unchanged.
     - Or keep the refactor and change the design to say the receipts are invalidated once.

2. **[nit] The design's premise that "G13/G15 get reuse from execute_cached" is untrue for every valid case, and G14 now does more than G13/G15.**
   - `bin/strategy:168` turns the cache off for the whole case if any step is `unannounced`. `factory/case_contract.py:82-84` requires a non-empty `unannounced` list. So G13/G15 never use the cache on a real v2 case; `medusa-oversell-v2` has U2.
   - G14 caches its announced units even when the case has unannounced steps. That is sound: `checkpoint` is a standalone `bin/checkpoint` subprocess, and `silent_checkpoint` is still called directly, so it is never cached.
   - The design (`gate-window.md:16, 27`) should say G14 intentionally drops `simulate`'s whole-case rule. It should also say that Murphy 42's "resume completed checkpoint units" is still not met for G13/G15. That supports keeping row 42 open.

3. **[nit] "Run counts unchanged" (`gate-window.md:34`) is false for cases with two or more unstated rules on one step.**
   - `run(step['reference'], 'reference')` (`run.py:2086`) builds an identical cache identity for each rule on the same step: same scenarios, guard, report, runs, seed, label `g14-reference-<index>` and workers. So the second rule's reference run is served from the cache in the same pass.
   - `case_contract` allows this layout. The verdict is the same in practice (same seed), but it means fewer bench runs. Either document it, or add `rule['id']` to the label to keep the old count.

4. **[ok] The shared window (item 1).**
   - `processes.deadline` is a ContextVar holding `min(end, previous)` (`bin/processes.py:198-205`). Nesting `check`'s own window inside `window()` can only shrink it.
   - G10's thread is submitted through `copy_context()` at G6, in the loop body and outside any mechanical window, so G10 never inherits a G13-G15 deadline. G10's own window is `nullcontext`.
   - The window now also covers these paths: the `around_gate` hooks (`capture` and `observe_gate` in `extension_package.py:235, 355`), the early-reuse branch of `invoke`, the reuse/fingerprint/inventory steps in `check`, `publish` and `record_crash`. None of them spawns a child: I grepped `gate_state`, `factory_waste`, `public_progress` and `extension_package`. So none of them can trip on an expired window, and none can deadlock.
   - The replay path returns before the window. Direct callers of `check` keep their own window.

5. **[ok] The G14 `execute_cached` wiring (item 3).**
   - The call signature matches `checkpoint(scenarios, guard, report, runs, seed, label)`.
   - `workers` equals `bench_workers`, the same value used as `factory_workers`, as in `simulate`.
   - The cache key covers the binding, scenario trees, guard tree and name, report, runs, seed, label and workers.
   - `results_root` and `restored_results_root` match G13/G15.
   - The cache dir `strategy-g14-checkpoints` cannot collide with `strategy-<name>-checkpoints`: there is no strategy named `g14`, and the binding uses a different name (`g14-ingredients`) and gate (G14).
   - A receipt is written only when `stored == summary` minus `_evidence_path`. So a summary served from the cache equals the fresh one, and the downstream `clean`/`check`/`harm` logic sees the same data.
   - Incomplete or invalid summaries are never cached.

6. **[nit] The test proves both claims, but it overstates how real it is (item 4).**
   - I ran it on HEAD: 3 tests OK. I also ran it on a `git archive HEAD~1` copy in a temp dir (since removed). It fails as the author says: `8 != 4` for G13, G14 and G15, and `4 != 8 : a completed unit was redone`.
   - It replaces more than "only `bin/checkpoint`" (`gate-window.md:46`): the Python `strategy.checkpoint` wrapper (skips `read_completed`), `silent_checkpoint`, and summaries are synthetic (`paths: {}`).
   - Every G14 window times out, so the G14 verdict logic is never run on cached summaries.
   - Line 107's comment ("finishes the rest") is wrong; the third window also times out.
   - Line 100 (`pipeline = run._gate_pipeline()`) is unused.
   - The wrap in `early_checks` has no test.
   - I did not run `tests/bench/test_strategy.py`; my instructions allowed only the one test file.

7. **[ok] Murphy rows (item 5).** `docs/murphy-register.md` is untouched by the diff, and the design says row 42 is not closed and row 35 is not claimed. That fits ENGINEERING section 2, since no real-artifact or live run proves row 42. Finding 2 is one more reason to keep row 42 open.

---

## Disposition (elephant, commit 71b2e84)

- 1 fixed: `strategy_run` restored; separate `g14_binding`; g13/g15 `source_inputs` digests verified identical to baseline.
- 2 fixed in design (G14 vs `simulate` rule; G13/G15 reuse off on v2 listed as remaining gap).
- 3 fixed: `reference-<rule id>` tag, so each rule stays a real run.
- 6 fixed: unused var removed, comment fixed, early_checks test added; wording of what is replaced corrected.
