I'm returning **FAIL**: 1 blocker, 5 majors and 6 nits. The narrower diagnosis-only scope is the right call, and most of the design-1 findings it covers are fixed. One money-loop gap blocks it, and five gaps would still leave design choices to the implementer. I wrote, committed and ran nothing. I did not run any tests or the full suite. The review text below is ready to save verbatim as `docs/reviews/stream-d-worker-dispatch-design-2.md`.

---

# Review: stream-d worker dispatch design 2 (diagnosis-only sub-increment). FAIL (1 blocker, 5 majors, 6 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Scope:**
- `docs/designs/stream-d-worker-dispatch.md` at `d439a25c948253388c1f5af286009c4a2e2c77d0`, branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
- The 6-line queued-input addendum to `docs/designs/stream-d.md` (around line 1435).
- I left out the untracked `.stream-d-next/`.

**What is assessed:** whether the *diagnosis-only* sub-increment is ready. That increment covers:
- entry, settlement and ACK;
- immutable input, decision and finding replay;
- journal and schema retry through A;
- the isolated reviewer;
- durable outcomes.

I am not assessing whether the whole dispatcher is done. Design-1 B1, B2 and the extension parts of M5/M6 remain **accepted and open** for a separately reviewed extension addendum. The revised design keeps them open and does not mark them resolved. I treat the old extension sketches as unqualified, and I raise no finding against them here.

**Read verbatim, with elephant responses:** `stream-d-worker-dispatch-design-1.md` (including its round-2 revision note), `stream-d-diagnosis-input-design-3.md`, `stream-d-diagnosis-input-design-6.md`, `stream-d-diff-23.md` and `stream-d-diff-24.md`.

**Code inspected for feasibility only:**
- `run.py`:
  - `main` (lines 2940–3110);
  - `pilot_wall`, `make_pilots`, `early_probe`;
  - `opencode`/`_opencode`, `resume_provider_wait`, `pending_call`;
  - `restore_gate_crash`, `inherit_recovery_history`, `finalize_accounting`.
- `model_runtime.py`: `dispatch`, `prepare_dispatch`, `Runtime._call` (the full retry loop), `_invoke`, `opencode_config`, `select_models`, `case_budget_boundary`.
- `model_call_gate.py`: `ENV_KEYS`, `Gate`, `enforce`.
- `model_router.py`: `routes`, `route_maximum`, `valid_lease`, `ACCOUNTS`, `CHAINS`.
- `diagnosis.py`: `exhaustion`, `_state`, `_trigger`, `record_exhaustion`, `validate_result`, `_finding_path`, `queued_inputs`, `_input_stop_evidence`, `require_model_work`.
- `recovery.py`: `infrastructure_exhausted`, `require_restart_stop`, `RETRY`, `HOLDER_STOPS`.
- `batch_service.py`: `_enqueue`, `plan`.
- Also: `batch_accounting.card_total`, `budget.invocation_role`, `require_case_budget`, `free_models.provider_config`, `worker_release.verify_selected_drivers`, `rotation.json`, `rotation-3writers.json`.

## Design-1 findings: disposition for this sub-increment

- **B1, B2:** accepted and open, outside this increment. The design keeps them open (lines 22–24, 218–250). Correct.
- **M1 (isolation): substantially resolved.**
  - `make_pilots(diagnosis=True)` makes no config or auth copy.
  - `pilot_wall(slot=None)` loads no scenario and opens no bench ports.
  - The root-owned `/var/lib/unbug-diagnosis` task chain is defined.
  - Each driver gets an environment key allowlist.
  - Exa and webfetch/websearch are disabled.
  - A temporary loopback permit is defined for the gate.
  - **Remaining:** the collection helper is underspecified (M2 below).
- **M2 (insertion and role): resolved.**
  - Entry is immediately after `job_config.install`, before `raised_limits`, `restore_gate_crash`, Compose, pilot archival and `pick_models`.
  - Archived roles are copied into `c.card['roles']`.
  - The archived reviewer driver goes through `verify_selected_drivers`.
  - Calls use `run.opencode`, never `pending_call`.
  - **Remaining:** how the public card is carried forward on this new path (M4 below).
- **M3 (route accounting): resolved.**
  - Every pool is excluded for a route that failed deterministically.
  - Exhaustion is checked from `routes(model)` before any await.
  - Only GATED_CLAUDE is bounded; other routes wait on `unbounded_route` (I confirmed this in `route_maximum`).
  - **Remaining:** which route a repair is pinned to (M1 below).
- **M4 (journal and raw retention): mostly resolved.**
  - The exact fields are given.
  - `raw-bytes-<byte-sha256>` is distinct from the canonical `raw-result-*.json`.
  - The write order is decision, then finding, then completed state, and the replay matrix is given.
  - The orphan-check obligation is recorded in stream-d.md.
  - **Remaining:** operation-ID binding and stale output (M1 below).
- **M5:** extension only. Open. Correct.
- **M6:** the diagnosis stops are named in the table and the B adapter gaps are stated openly. The extension parts are open. One stop interacts badly with finalization (B1 below).
- **M7: resolved.**
  - Unknown-at-restore uses `card_total(checkpoint_card)`.
  - No `queued_inputs` call happens before the ACK.
  - The fail-closed property is tested as B's planner returning `diagnosis_unavailable` with `queue: []`, plus the worker refusing without job authority.
  - I confirmed `plan` returns that before any projection (`batch_service.py:296`).
- **N1–N4:** N1 (skip `build`/`validate_and_repair`), N3 and N4 are incorporated. N2 is partly incorporated: call counts are given but no dollar figure (N3 below).

The queued-input addendum in stream-d.md agrees with the dispatch text: a global repair ordinal, the journal `kind` telling repairs apart, distinct raw-byte names, and the orphan check to be extended before producers are wired. I found no contradiction there.

## Blockers

### B1. A completed decision can be re-minted as a new pending diagnosis, causing repeated paid diagnosis calls

- **Where:** stops table (lines 300–308), lines 35–37 ("restore ... original code-recorded stop context"), and lines 136–138. Checked against `run.py:3052–3059`, `run.py:2793` and `diagnosis.py:109–127`, `:70–84`.
- **What the runner does:** its stop handler sets `c.exhaustion_occurred = True` for *every* `BudgetError`. `finalize_accounting` then calls `record_exhaustion(card, new_exhaustion=True)`.
- **What `record_exhaustion` does:** for a *completed* state with `new_exhaustion=True`, it continues. It sets `stop = 'infrastructure_exhausted' if infrastructure_exhausted(card)`.
- **Why `extension_comparison_pending` is exposed:** it is not in `exhaustion()`'s excluded list. Unlike `retired_*`, `provider_wait` and the invalid stops, `exhaustion()` returns `infrastructure_exhausted(card)` for it.
- **What goes wrong:** take an `infrastructure_exhausted` case whose diagnosis completed as `close_to_passing`.
  1. The dispatcher stops with `extension_comparison_pending`, as the design specifies, and restores the original stop context, including the `infrastructure_gate` marker.
  2. Finalization mints a fresh pending `exhaustion_id`.
  3. The next resume diagnoses the same case again, gets `close_to_passing` again, and re-mints again.
- **Same path, other stops:** a completed decision that stops `money_wait` (table row 3) takes the same path.
- **Why this blocks:** this is a paid model loop, bounded only by the batch deadline. It breaks the rule "only a new literal exhaustion can replace a completed state" (the `record_exhaustion` docstring and input design-3). The design leaves this interaction unstated, so the implementer must decide it on a money path.
- **Required:**
  - Specify that dispatcher-produced stops never set `exhaustion_occurred`. Alternatively, `record_exhaustion` must refuse to replace a completed state unless the run produced a new literal trigger.
  - Name the mechanism.
  - Test it with a card carrying an `infrastructure_gate` exhausted marker and a completed `close_to_passing` state, over two resumes: the `exhaustion_id` is unchanged and no reservation is made.
  - Also cover the completed-decision `money_wait` row.

## Majors

### M1. The attempt lifecycle has three unspecified seams that the journal depends on

- **Where:** lines 76–125. Checked against `model_runtime.py:290–483` and `run.py:190–211`.

**a. Operation-ID binding.**
- `Runtime._call` uses `getattr(c, 'model_operation_id', None) or uuid4()`.
- Only `pending_call` sets `c.model_operation_id`, and the design forbids `pending_call`.
- Without an explicit step, every `opencode()` call gets a fresh operation. A pending row resumed after a provider wait or crash then cannot match "a retained ledger reservation's operation" (line 97), and the journal check will reject it.
- **Required:** the dispatcher sets `c.model_operation_id` to the journal row's `operation_id` (written when the row is created, before the call) for the duration of the call, and restores the previous value in `finally`.
- Also say when the pending row itself is written: before `opencode`, so that a pre-admission denial leaves a row with `invocations: []`.

**b. Stale or foreign output in `output/result.json`.**
- `Runtime._call` loops inside one `opencode()` call. After a per-call transport failure (`process_error`, outage), it takes another lease and re-invokes the CLI under the same call name (`model_runtime.py:464–483`).
- Each invocation's `_invoke` kills processes and cleans the scratch directory, but nothing clears the task tree's `output/`. A partial `result.json` from the failed first invocation can therefore be collected as the answer of the second.
- A crashed run (line 103: "completion whose raw file was not yet retained") also leaves the old task tree on disk. Nothing says the next attempt must not reuse it.
- **Required:**
  - Each `before_attempt` empties and recreates `output/` as `pilot:pilot 0700`, through the trusted helper, before the process starts.
  - Dispatcher entry removes any existing `/var/lib/unbug-diagnosis/<case>/<exhaustion_id>` with no-follow removal, then rebuilds the tree.
  - Test both cases.

**c. Which route a repair runs on.**
- "One schema-only repair ... from the same family" (line 110) lets A send the repair to any same-family route or pool.
- The accounting rule "each approved route gets one original judgment and one repair" (lines 114–115) then has no defined owner when the repair lands on a different route, and line 111 does not say which route gets excluded.
- **Required:** pin the repair to the judgment's route by excluding every *other* route through `router_excluded` (any pool on that route is allowed). Alternatively, state that the repair counts against the judgment's route and that exclusion targets that route. Test a repair that A would otherwise move to a second route.

### M2. The sudo collection helper is unnamed and unbounded

- **Where:** lines 167–172.
- **Unspecified:**
  - the file, for example `factory/diagnosis_collect.py`, shipped in the worker release and selected by the release digest;
  - the exact sudo command, for example `sudo python3 -I -B <path> <case> <exhaustion_id>`, with arguments validated against UUID and case patterns, never a path;
  - the return protocol.
- **No size limit:** `result.json` is written by the model. An unbounded read through a pipe into runner memory lets a misbehaving role exhaust the worker.
- **Required:**
  - Fix a maximum byte count, for example 1 MiB.
  - Over the limit, record it as a malformed result with a fixed error class and a digest of the truncated prefix, not as an infrastructure stop that would loop.
  - Say whether a single helper also does the input re-hash and the output reset from M1b, or name each operation.
  - Test with a symlinked `result.json`, a FIFO, an oversized file, and a missing file (which counts as malformed).

### M3. The diagnosis prompt, the repair prompt and `schema_sha256` are not specified

- **Where:** lines 88–89, 110. Checked against stream-d.md lines 781 and 815, and `factory/prompts/` (no `diagnosis.md` exists).
- **Why it matters:** the sub-increment's core model call has no defined input. The implementer must decide:
  - the prompt file and its content;
  - how the model is told the inputs root, so that `evidence[].path` values are relative to it (`validate_result` checks them against `evidence_root`; say which root, the exposed copy or the runner's frozen copy, and that their bytes are identical);
  - that `checkpoint_sha256` must equal the manifest generation;
  - the fixed output path;
  - what the repair prompt contains (the retained bytes plus the schema error class only, not the inputs);
  - what `schema_sha256` hashes (the prompt file? a canonical schema document?);
  - what `input_sha256` hashes. "Canonical manifest digest" appears only for `decision.json`; say the same for `attempts.json`.
- **Required:** name `factory/prompts/diagnosis.md` (and a repair prompt, or a section of it), the exact digest definitions, and the evidence-root convention.

### M4. The public card on the dispatcher path is unspecified, and pilot cleanup is skipped

- **Where:** lines 32–43. Checked against `run.py:2953–2954`, `:2748–2766`, `:3017–3031` and `:3086–3104`.

**a. Card carry-forward.**
- `main` builds a fresh `c.card` with `gates: {}`, and `inherit_recovery_history` copies only a few keys.
- The dispatcher stops before any gate runs, so the checkpointed and published scorecard drops the archived `gates`, `failed_gate`, `infrastructure_gate`, `statement_sha256`, `stress_review`, and so on.
- Lines 35–37 ("restore the operational diagnosis/extension state and original code-recorded stop context") do not say which fields. The answer affects:
  - what B and the founder see in the scorecard;
  - the next `checkpoint_card`;
  - B1 above, since carrying `infrastructure_gate` forward triggers the re-mint.
- **Required:** an exact allowlist of archived public fields copied unchanged on the dispatcher path, with a test that a dispatcher stop preserves them byte for byte apart from `terminal_stop`, `status`, `diagnosis_state` and accounting.

**b. Pilot-home archival.**
- The ordinary resume moves old `pilot`, `pilot-strong` and `pilot-easy` homes into `previous-gate-runs-*`, and kills and removes those users (`run.py:3017–3031`).
- The dispatcher runs before that step, and `make_pilots(diagnosis=True)` *shreds* the `pilot` home instead.
- It leaves `pilot-strong`/`pilot-easy` processes and their firewall chains in place.
- **Required:** say whether the existing archival step (already slated to become a helper, line 38) runs before `make_pilots` on the dispatcher path. Running it is the obvious choice.

### M5. The activation boundary overlooks existing relaunch paths

- **Where:** lines 14–17 and the stops table row "Crash before/after a retained decision ... No automatic relaunch is claimed today". Checked against `recovery.py:192–208` (`require_restart_stop`, where `RETRY` matches `runner_error:.*`, `timeout`, `stalled`, `process_error`, and so on) and `HOLDER_STOPS` in `recovery.py` (used by `key_holder`).
- **What changes:** once this slice merges, *any* same-owner resume of a card with `diagnosis_state.status == 'pending'` makes a paid diagnosis call, whatever `DIAGNOSIS_ENABLED` says. Examples:
  - a `runner_error:*` stop during dispatch;
  - a holder stop;
  - a founder-raised budget resume.
- Today such a resume reaches `build` instead (the bug the design fixes). Replacing a writer round with one diagnosis is defensible.
- **But:** the document says B activation stays off, and says no automatic relaunch exists. Neither statement was checked against these paths.
- **Required:**
  - List the existing relaunch paths that can deliver a dispatcher-eligible card.
  - State plainly that model diagnosis becomes reachable through them, and that this is intended.
  - Or keep the dispatcher stopping before any reservation until B's adapter exists. That would contradict the slice's purpose, so stating it is the expected fix.
  - Add a test: a `runner_error:` card passes `require_restart_stop`, and the resumed worker dispatches no writer and at most the bounded diagnosis calls.

## Nits

- **N1. Reviewer independence (lines 66–68).**
  - The family check compares the reviewer with the writer and strong calibrator only.
  - `select_models` requires four distinct families, and the reviewer2 rule also excludes the stress tester, which shaped the case.
  - Add `stress_tester` to the contradiction check.
- **N2. Loopback permit details (lines 202–207).**
  - `pilot_wall` *appends* the LOCAL `REJECT`, so the permit must be inserted (`-I factory-pilot 1`) ahead of it, with the same conntrack ORIGINAL rule used for bench ports.
  - State that a crash leaves no live permit, because the next `make_pilots` flushes the chain (`-F`).
  - Keep the permit inside `with enforce(...)` in `_invoke`, only for `user == 'pilot'` and diagnosis call names.
  - Note that the existing Claude-calibrator-as-pilot path has the same loopback gap. It is out of scope here and not fixed by this change.
- **N3. Impact and cost (Heilmeier).**
  - Only GATED_CLAUDE is bounded, so diagnosis can run today only in slots whose reviewer is Anthropic: 1 of 8 in both `rotation.json` and `rotation-3writers.json`. Every other slot waits.
  - State this in one line.
  - Also state the dollar ceiling: 2 × the Claude gate `max_usd` per input/schema, plus interrupted attempts at the conservative reservation, all drawn from the existing job commitment.
- **N4. Paths and tests.**
  - State the paths for `attempts.json`, `decision.json` and `raw-bytes-*`; presumably `work/diagnosis/<exhaustion_id>/`, next to `finding.json` via `_finding_path`.
  - Add the orphan-check extension (refusal on raw-bytes, attempts or decision with no manifest) to the slice's test list. It is currently only in stream-d.md.
- **N5. Stops table row 3.** In this slice, a completed decision needs no money, because replay is model-free. Drop "or completed decision" from the `money_wait` row, or explain it. It also feeds B1.
- **N6. YAGNI (lines 38–40).** Factoring Compose and driver preparation "so the extension path can invoke them" is extension-addendum work. Limit this slice to the pilot-archival helper it needs (M4b), and defer the rest.

## Answers to the brief's focus areas

- **Attempt lifecycle.** The schema, phases, deterministic slots and pre-await exhaustion are sound and match A's real exclusion key. The gaps are operation-ID binding, output freshness across A's in-call retries and crashes, and repair-route pinning (M1). There is also finalization re-minting (B1).
- **Role isolation and credentials.**
  - The per-driver allowlists match the code. Claude's `enforce` already reduces the environment to `ENV_KEYS` with the lease's own token. Codex already preserves only `CODEX_HOME,PATH`.
  - The OpenCode change is correctly specified: no `--preserve-env`-all, only the lease account's key (none for the unkeyed free route), and no Exa.
  - The root-owned task chain is correct and cannot be renamed by pilot.
  - The gaps are the collection helper's bound and identity (M2), and leftover pilot users (M4b).
- **Bounded transport permit.** It is necessary: the wall `REJECT`s every LOCAL destination, and the gate listens on `127.0.0.1:<ephemeral>`. Its scope is correct. Only rule-placement and crash-cleanup details are missing (N2).
- **Scope.** The extension boundary is clean. `close_to_passing` and active extensions keep their state and stop pending, and no writer is reachable. B1/B2/M5/M6-extension stay open and are not mischaracterised. The "no runtime-ready claim" statement is honest about B's adapters. The claim about existing relaunch paths needs correcting (M5).

## Validation boundary

This is a design-readiness review only. No files were written, and no commits, merges, pushes, launches, cloud work, model calls, decryption, tests or suite runs were done. I make no claim about the 210eb39 full-suite or diff-24 results beyond what those review records state. No Murphy row closes. B's `DIAGNOSIS_ENABLED` stays false, and A/B/E activation stays gated.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

All findings accepted; none rejected. Completed states will require a new literal trigger in record_exhaustion, independent of a stale infrastructure marker. The dispatcher will explicitly scope model_operation_id, pin schema repair to the judgment route, reset output at every actual invocation and rebuild stale task trees. The helper, bounded wire protocol, prompts/digests, public carry-forward fields and pilot archival will be specified. For M5 the worker will read B's single existing DIAGNOSIS_ENABLED gate before any new diagnosis reservation; it adds no second flag or authority. Existing relaunches may enter the dispatcher, but with that gate false they cannot spend or reach a writer. Offline tests patch the same existing gate to exercise the future enabled path. This honors the user's fail-closed-until-B-enabled constraint. All nits are accepted. Extension design-1 blockers remain open.

