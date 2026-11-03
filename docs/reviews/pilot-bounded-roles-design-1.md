Codex gpt-6.1-sol review, substituting because Claude and the free OpenCode reviewer hit usage limits. Writer: gpt-6.1-terra. No paid OpenRouter, provider calls, credentials, edits, or delegation used.

**Verdict: changes required — one blocker and one major.**

1. **Blocker — the pinned easy calibrator fails real statement dedup.**  
   `docs/designs/pilot-bounded-roles.md:23–27` pins both writer and easy calibrator to MiniMax. `factory/run.py:844–845` raises `ValueError("Statement dedup must not use the writer's family")` whenever prior statements exist. Passing `select_models` therefore does not establish a runnable three-case pilot; later cases encounter earlier statements.

   **Required change:** choose an already bounded easy-calibrator route from a different family than the writer, update its maximum and cost discussion, and update `docs/designs/pilot-run.md`. Add a test exercising real `statement_precheck` with nonempty prior statements and synthetic model output. Preserve the independence guard. Affected implementation/test scope includes the eventual pilot admission pins and their tests.

2. **Major — per-job validation does not reject an invalid pilot plan before its first launch.**  
   `docs/designs/pilot-bounded-roles.md:18–19,45` specifies validation of each resolved job at `_admit`. That function resolves only the requested job (`factory/batch_holder.py:213`). A three-job manifest with valid pins in job 1 and Codex in job 2 can therefore admit job 1 before discovering the unsupported plan.

   **Required change:** explicitly validate every pilot job/template in the authenticated manifest before admitting any pilot operation, and recheck the selected resolved job for replacement/resume lineage. Keep this before replay returns and money mutations. Add a mixed-manifest test: qualifying/reserving the valid first job must refuse when another job contains Codex, missing pins, or reviewer2; assert unchanged authority and operation state. Affected files: design, `factory/batch_holder.py`, holder/qualifier tests.

3. **Nit — specify the argparse regression matrix more literally.**  
   `docs/designs/pilot-bounded-roles.md:35–40,78–82` has the right intent, but “abbreviations” needs an exact-first parsing oracle. Production argparse treats exact `--builder` differently from ambiguous `--buil`, while `--reviewer2-effort` and its unique abbreviation `--reviewer2-e` select the effort option, not reviewer2. A blanket prefix rejection would reject legal non-role options.

   List tests for `--writer`, `--stress-tester`, `--pilot`, their equals/abbreviated forms, appended overrides, ambiguous prefixes, and legal effort options. Compare against the actual `run.argument_parser()`, using correctly transformed worker arguments rather than feeding it launch-only `1`, `--ttl-hours`, or `--max-spend`.

The remaining reviewed points are sound:

- Four principal families satisfy `select_models`, `diagnosis_dispatch.reviewer`, and G16/G17 independence. G16/G17 also use the independent reviewer; describe that alongside the strong solver.
- Exact ID `b-real-pilot`, deferred activation, retained global disablement, and unchanged Codex refusal are appropriate.
- Router/maxima dependencies are already fingerprinted through `launch_manifest.TRUSTED_FILES`. Keep production validation independent of importing the runner; rebuild the authenticated release after host-code changes.
- The diagnostic test reaches the real runtime/router with synthetic authority and prevents CLI invocation. It proves the refusal, not live qualification.
- Cost arithmetic is correct: `$0.012894 − $0.0042488 = $0.0086452`. The receipt supports that single token-count illustration; it does **not** support an expected per-case delta.
- The limited workaround, explicit deletion assessment, retained prerequisites, and leaving Murphy 30 open are appropriate. Practice retry should remain dependent on its separate preflight landing.

Read-only inspection only; tests were not executed. Worktree remained clean.

## Writer disposition

Accepted blocker 1 and major 2: use DeepSeek for easy calibration and check
all job templates before any pilot admission. Add the requested dedup and
mixed-manifest tests. Accepted the argparse matrix and clarified G16/G17.

