# Preflight design review 1

Goldfish: fresh Claude (claude-opus-5-5) general-purpose subagent, read-only. Personas: zoom_out, design_critic, implementation_readiness; Mode: REVIEW. Standards: heilmeier, implementation-readiness. Design: docs/designs/preflight.md at 4985e0e.

## Verdict: FAIL

The direction is sound: it extends the existing `practice_preflight.py`, stays on the VM at $0, and lists every failure at once. That makes it consolidation, not a staging layer. But several checks cannot work as written, and the Codex condition would let real batches fail mid-run.

## Blocking

B1. `image_startup` cannot catch stop 10, and its test claim is false. The project name comes from `projects/medusa/compose.yaml:1` (`name: unbug-bench`). Using a unique project name renames every container, so a clash with `unbug-bench-postgres-1` cannot occur. The worker image is a Boat snapshot (`bench-env`, built by `bin/boat-bake:47-50`) that local Docker can't boot. The stop-10 diagnosis (`t3/batch-service-control-vm:docs/reports/practice-startup-error.md`) traces the clash to an unadopted container in the worker's own Docker state, and says local runs "do not reproduce the deleted worker's exact Docker metadata". So "with the old early-Compose code it fails on the clash" (design line 70) cannot hold. The real-Docker regression already exists on that branch, at `tests/factory/test_practice_startup.py`. Fix: delete `image_startup`. State that stop 10 is covered by the `t3/batch-service-control-vm` fix and its test, and leave the Boat smoke worker as the open founder decision.

B2. Gating the Codex check on "a manifest route starts with `codex/`" misses rotation-defaulted Codex roles. `model_runtime.select_models` resolves any role without an explicit flag from the rotation, and `factory/rotation-3writers.json` sets `strong_calibrator = codex/gpt-6.1-sol` in every slot shown. A launch with no explicit `codex/` text would skip the gate, and the worker would then hit the router's lease-time guard (`model_router.py:562`) mid-run, after spending has begun. Line 514 is in `factory_auto_resume`, which returns early when `batch_release` is set (`launch.sh:505`), so that path has no batch manifest at all. Fix: decide on the resolved roles, by running `select_models` over the launch args as `practice_preflight.roles()` already does. Apply this at 149, 514 and 654, and add a test with no `--strong-calibrator` that is still gated.

B3. The "launcher refuses without a fresh report" gate is unplaced and mis-scoped.
- Placement: in `launch.sh`, it fires after `batch_holder.dispatch` has written `dispatch_started=True` (`batch_holder.py:812`). That turns the single practice operation into terminal failed/`preflight_refused`, which is exactly what stop 7 did (report lines 197 and 220).
- Scope: the module is practice-only (`MANIFEST` and `DROPIN` are hard-coded), but the rule as written covers every release.
- Unattended launches: a 1-hour window blocks resume and replacement launches that run with nobody present, which breaks the no-pit-stop target in ENGINEERING.md section 3.
Fix: run the read-only checks inside `dispatch` before the `dispatch_started` write, for fresh admission only. That also removes the report file and the 1-hour window (see N1).

B4. The `router` check names the wrong code. The `dispatch` environment (`batch_holder.py:803-808`) never carries the router URL, token or trust. Those are packed by `router_delivery.pack` (`launch.sh:326-331`) and exported at `:343-345`. Building the `dispatch` environment also needs a reserved operation (`launch_id`, the `_config` file), so it is not read-only. Fix: call `router_delivery.pack` on the in-memory bundle, which already reads the config, calls the live router status and packs the three names. Then assert the names are present.

B5. The design relies on manifest fields that don't exist. `b-plumbing-practice-2.json` has only `money_limit_usd` (19.99): no decision list, no infrastructure cap and no paid ceiling. The manifest is exact-matched (`practice.matches`) and pinned, so adding fields means a repin, which the design doesn't mention. The decisions file has no path or schema. "OpenRouter credit ≥ paid ceiling" would have failed the real run: $11.36 was observed, and the plan accepts min($11.63, observed credit) (`practice-run.md:21`). Fix: keep the caps in `practice_preflight.LIVE`, which already holds 5.0 and 19.99. Put the decision IDs in a constant, and define the decisions file's path and JSON shape (`{id, text, recorded_utc}`). Adopt the min() rule.

B6. "Steps 1–3 become run preflight; all pass" deletes actions that change state, and the check order contradicts itself. Step 2 installs code, the router and the cleanup unit, and step 3 reserves and arms cleanup; a read-only preflight can't replace either. The `router` check needs the router already deployed, while the `sudo` check only helps before deployment. Fix: keep the step 2–3 actions. State that `sudo` and the other checks that don't depend on deployment run before step 2, and that `router`, `credentials` and `r2_openrouter` run after step 2 and before reservation.

B7. The Murphy rows and evidence don't meet ENGINEERING.md section 2.
- `new-preflight-5` (sudo) is claimed closed, but no listed test covers sudo.
- Stop 9 is not recorded anywhere I found. The cited report ends at stop 8 (13:56 UTC on 2026-11-02).
- The cited fixture `tests/factory/fixtures/practice-startup-conflict-20261103.json` exists only on the unmerged `t3/batch-service-control-vm` branch.
- `new-preflight-2` duplicates row 31, which is closed with the note "VM install pin remains a deployment prerequisite".
Fix: cite evidence for stops 9 and 10, and leave row 5 open or name a test on real `sudo -n` output. Reopen row 31 rather than adding `new-preflight-2`, and state the dependency on the unmerged branch.

## Non-blocking

N1 (over-built). The report file and the 1-hour freshness rule exist only because preflight is a separate step. Once `image_startup` is cut, the remaining checks are fast and read-only, so running them inline in `dispatch` replaces both.
N2. `sudo -n true` can pass on a cached sudo timestamp, and it can fail falsely when NOPASSWD covers only specific commands. Use `sudo -k -n` with the exact commands deployment runs, or `sudo -n -l <cmd>`.
N3. `key_holder.secret_labels` returns only Claude and OpenCode labels, so `credentials` needs the full label set. Also bind the report to the hash of `secrets.age`: stop 8 came from a bundle that was replaced after the checks.
N4. "Balance ≤ cap" (`boat_wallet`) only makes sense for practice; a real batch needs balance ≥ its estimate.
N5. Collecting "Go" up front changes a pause the founder approved in `practice-run.md` step 4. Note that the founder must agree.
N6. Define the exit code for `needs_founder`. The existing `code()` returns 1 or 3, never 0.
N7. The design states no cost or timeline (Heilmeier).
N8. `launch.sh:333` (requires `codex-auth.json`) and `:695` (qualifies the `codex` driver) stay unconditional. That is harmless, but the Codex deletion is only partial.

On question 3: nothing else depends on the launch-time Codex login check. The router re-checks at lease time, diagnosis uses the reviewer role, and the exam (`bin/run-exam`) doesn't go through `launch.sh`.

## Elephant resolution

All 7 blockers accepted; none rejected. N1–N7 adopted in revision 2. N8 noted in the design. Changes are listed in the revision 2 commit.
