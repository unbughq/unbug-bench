I'm returning **FAIL**: 2 blockers, 7 majors and 4 nits. Nothing was written, committed or run. I did not run any tests or the full suite, and I make no claim about diff 24 or the 210eb39 results. The review text below is ready to save verbatim.

---

# Review: stream-d worker dispatch design 1 — FAIL (2 blockers, 7 majors, 4 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Scope:** `docs/designs/stream-d-worker-dispatch.md` (205 lines) at `df69412014652b9d5e2cdab07f25c1dcd91493fa`, branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. It is reviewed against these sections of `stream-d.md`:
- "Extension eligibility and progress"
- "Diagnosis and factory-bug routing"
- "Resume, accounting and checkpoints"
- "Increment 3"
- "Queued diagnosis inputs"
- "Queued input implementation boundary"

It is also reviewed against interfaces §8. I left out the untracked `.stream-d-next/` folder.

**Prior reviews read verbatim, with elephant responses:** `stream-d-diagnosis-input-design-3.md`, `stream-d-diagnosis-input-design-6.md`, `stream-d-diff-17.md`, `stream-d-diff-19.md`, `stream-d-diff-23.md`.

**Code inspected for feasibility only:**
- `run.py`: main entry ~2888–3060, `pending_call`, `resume_provider_wait`, `write_and_attack`, `validate_and_repair`, `make_pilots`, `pilot_wall`, `inherit_recovery_history`
- `model_runtime.py`: `dispatch`, `Runtime._call`, `_invoke`
- `model_router.py`: `routes`, `await_lease`, `valid_maximum`
- `model_call_gate.enforce`
- `budget.py`: `reconcile_reservations`, `invocation_role`
- `gate_state.py`: `inputs`, `inventory`, `save`, `load`
- `extensions.py` (whole file)
- `diagnosis.py`: `exhaustion`, `pending_projection`, `record_exhaustion`, `persist_factory_bug`, `restore_factory_bug`
- `late_recovery.invalidate`
- `batch_service._enqueue` and `plan`
- `job_config.install`
- `factory/launch.sh` secret export
- `bin/push-secrets`
- `rotation-3writers.json`

## Obligations from accepted reviews: preserved

- **Design-3 / diff-23 orphan check.** The exact reservation names `diagnosis-<id>` and `diagnosis-<id>-repair-<ordinal>` are kept (lines 59–60).
- **Diff-17 Ma2 / diff-19.** Validation and replay use the frozen inputs root and the original manifest generation. Later ledger or receipt changes never replace them (lines 44–46, 87–88).
- **Diff-22 N1.** Reconciliation and the no-active-calls check come before `queued_inputs` (lines 34–36).
- **Diff-23 N4.** History-invalid is sticky and never relabelled (line 47). It projects None and gets no model work (line 32).
- **Input design n5.** The role reads a separate copy of the verified inputs, not live work (lines 100–109).
- **Stream-d.md.**
  - One writer per extension; repair limit zero; cumulative `builder_rounds`.
  - A completed writer resumes at validation.
  - A pre-admission wait writes no history; the active extension reuses its operation.
  - Five lifetime extensions; strict progress at identical versions.
  - Malformed output gets one schema repair from the same family, then the next approved route.
  - The `factory_bug` result is held through the existing producer, with no waste attribution.
  - A decision never grants money or an extension.
  - Murphy rows stay open and A/B/E activation stays gated (lines 15–17, 201–205).

## Blockers

### B1. The budget bypass is checked before admission exists, so `budget_exhausted` cases can never get an extension

- **Where:** lines 153–167, against `run.py:338–341` and `run.py:343–348`.
- **What the code does:** `pending_call` checks the ordinary limit before `reserve_invocation`. It skips the check only when `c.active_extension_id` is set:

  ```python
  if role == 'writer' and not getattr(c, 'active_extension_id', None):
      ... spent + maximum > ordinary_limit_usd → budget_exhausted
  ```

- **What the addendum requires:** `extensions.admit` runs only after the real writer reservation exists (`on_admitted` → `admit`). It also limits the "existing modern budget bypass" to "a verified active extension".
- **What goes wrong:** for the `budget_exhausted` trigger, spent plus the writer maximum is above the ordinary limit by definition. No extension is active before admission, so the check raises `budget_exhausted` before any reservation. The first extension can never be admitted.
- **The tempting fix is unsafe:** setting `active_extension_id` from an unadmitted proposal keys a money bypass on unverified in-memory state. The design leaves that choice to the implementer, on a money path.
- **Required:**
  - Define the bypass predicate exactly: a proposal from `extensions.propose` for the current completed `close_to_passing` exhaustion, re-validated under the dispatch lock just before `reserve_invocation`.
  - Make `require_case_budget` / `job_authority.committed_total_usd` (`money_wait`) the only money check for that call.
  - Say how the bypass is cleared on every exit.
  - Test it with the saved 5813be ledger at an over-ordinary-limit total, plus a forged-proposal refusal.

### B2. Baseline reconstruction, as specified, cannot finish, cannot be isolated, and can corrupt live evidence

- **Where:** lines 144–151, against `gate_state.py:131–202`, `extensions.py:229–251` and `run.py` `write_and_attack`.

**a. Shared output roots.** The design says "evaluate changed stages ... on disposable copies". But the gate runner writes to:
- the module-global `BENCH/results` (including fixed-name files such as `runs/baseline.json`);
- `c.work/gate-details`;
- `c.work/gate-cache` (via `gate_state.save`);
- `c.card['gates'|'gate_results'|'failed_gate']`.

Evaluating the entry revision would overwrite the live current evidence. That is the same fixed-name collision the input design had to handle. A copied case tree does not redirect any of these roots.

**b. No standalone stress evaluator.** Stress review only exists inside `write_and_attack`, interleaved with the writer. The design names no entry point that runs one stress review on a revision with no authoring path. "No authoring" (line 149) is asserted, not built.

**c. `propose()` waits forever.** `extensions.propose` requires the live snapshot to equal the chosen comparison outcome exactly in `case_sha256`, `stages`, `frontier` and the `evidence` map (`extensions.py:247–251`).
- If the outcome revision is re-evaluated on a disposable copy, the live snapshot has no receipts under the new version.
- If it is re-evaluated anywhere else, the evidence paths and digests differ.
- Either way `propose` returns `extension_comparison_pending` forever, and no further extension is ever possible after a version change.

**d. No reservations or stop for reconstruction.** No call names or reservations are given for reconstruction model calls (stress, G2/G8/G9/G10/G16/G17). No terminal stop is given for "reconstruction still pending".

**Required:**
- The outcome revision is the live case. Verify `case_sha256` equals the stored outcome, then evaluate it in place, producing ordinary live stage receipts.
- Only the entry revision runs in an isolated context, with explicitly redirected work and bench result roots: a named slot or path, never the live fixed names.
- Name the stress-only evaluator, with no writer reachable from it.
- Specify the reservation call names and the stop label for unfinished reconstruction.
- Tests must show no live evidence bytes change during entry reconstruction, and that `propose` succeeds after a real version bump.

## Majors

### M1. Role isolation does not match the code it says to reuse, and the credential claim is wrong for opencode

- **Where:** lines 100–123, against `run.py:2426–2449`, `run.py:88–112`, `model_runtime.py:513–572`, `model_call_gate.py:22–27` and `launch.sh:311–322`.

**a. `make_pilots` copies the runner's credential store.** It copies `.config/opencode` and `.local/share/opencode/auth.json` from the runner home into the pilot home (`run.py:2438–2439`). Line 111 forbids exactly that, while line 100 says to reuse the `make_pilots` lifecycle. The implementer has to choose between a new parameter, a new function, or a post-copy deletion.

**b. Opencode gets every provider's key.** The opencode branch runs `sudo --preserve-env -H -u <user>` with `env = {**os.environ, **model_env}` (`model_runtime.py:513`, `:520`). The runner environment exports `CLAUDE_CODE_OAUTH_TOKEN`, `OPENCODE_API_KEY` and `OPENROUTER_API_KEY` (`launch.sh:319–322`).
- A minimax or deepseek diagnosis process would therefore receive every provider's credential, not "its own" (line 117).
- It would also read writer-authored case content, with internet egress and `OPENCODE_ENABLE_EXA=1` web search.
- By contrast, Claude filters to `ENV_KEYS`, and Codex preserves only `CODEX_HOME,PATH`.
- Line 113 ("filter ... to the driver's required keys") is the right intent, but no allowlist is given. The brief's constraints (no new permission to expose factory keys; provider transport scratch stays as it is) need an exact per-driver key list for the diagnosis role. For opencode that is the selected pool's key only, plus `OPENCODE_CONFIG`, `XDG_DATA_HOME`, `PATH`, `HOME`, `LANG`, `TMPDIR`.
- The Codex `auth.json` scratch copy (existing runtime behaviour) should be stated as unchanged.

**c. Where the input copy lives is unspecified.**
- The runner home is mode 0700, so the copy must live outside it.
- A root-owned directory inside `/home/pilot` can still be renamed by the pilot, because the parent is pilot-owned. That defeats line 106.
- Name a root-owned chain, for example a root-owned `0750 root:pilot` directory whose parent is not pilot-writable.
- Name the writable output path, and how the runner (not root) reads pilot-owned output.

**d. `pilot_wall` fails on early exhaustions.**
- It calls `bench.load_scenario(c.case / "base")` and opens bench ports for a slot.
- A case that exhausts early (budget or prototype stage) may have no `base` scenario. The wall setup then fails, the dispatcher stops as infrastructure, and every resume loops on the same failure.
- Diagnosis needs no bench ports. Specify a no-ports wall variant, or prove `base` always exists for every exhaustion trigger.

**e. Web tools.** State the web-tool posture for case secrecy (ENGINEERING §4): whether Exa or web fetch is enabled for diagnosis, and why.

### M2. Where the dispatcher sits in `main()`, and how it resolves the role, is underspecified, and the obvious placement crashes

- **Where:** lines 26–33 and 53–57, against `run.py` ~2988–3043 and `model_runtime.py:300–301`.

**a. Placement.** "After `job_config.install`, before `build`" spans several steps:
- `raised_limits` and `restore_gate_crash`, which mutate `failed_gate`, `gates` and `failed_detail`;
- archiving old pilot homes and `userdel`;
- `COMPOSE up`;
- `pick_models` (which honours current `--reviewer1` overrides and `free_models.apply`);
- `verify_selected_drivers`.

The design must pin the exact position.

**b. Role check.** `Runtime._call` compares the requested model's family with `c.card['roles'][role]`, and raises `ValueError('role family changed')` on mismatch.
- If the dispatcher runs after `pick_models` and the current arguments name a different reviewer family, passing the archived reviewer crashes with a `ValueError`, not a clean refusal.
- If it runs before `pick_models`, the archived reviewer driver never gets driver qualification.

**c. Call path.** The design does not say which path it uses. `pending_call` writes `attack-state.json` and `builder_rounds`, so it is unsuitable for diagnosis. `opencode()` / `Runtime.call` is the suitable path; `invocation_role('diagnosis-…')` maps to `reviewer`.

**Required:**
- The exact insertion point.
- Set `c.card['roles']` (or `router_model`) from the archived `roles` for the dispatcher run.
- Qualify the archived reviewer's driver.
- Use `opencode(...)`, with `before_attempt` writing `attempts.json`.

### M3. Route-exhaustion accounting does not match how A excludes routes

- **Where:** lines 74–82, against `model_router.py:106–114` and `:429–447`, and `model_runtime.py:398–399`.

**a. Exclusion is per account.** `router_excluded` entries are `pool + '/' + route`, and the pool is the account (two Claude accounts, two opencode-go keys). Excluding the failing pool leaves the same route on the other account, which allows a third judgment on that route. The design says that must not happen (lines 77–78). Specify excluding every pool for the route.

**b. All-excluded becomes a wait, not a failure.** With `UNBUG_PROVIDER_WAIT=1`, `await_lease` turns "every choice excluded" into a deferred wait, not `provider_routes_exhausted`. The "deterministically exhausted → retire" rule (lines 79–80) would never fire. The dispatcher must compute exhaustion itself from `routes(model)` against `attempts.json`, before asking for a lease.

**c. Only one route is bounded today.** Only `GATED_CLAUDE` has a bounded maximum. Non-anthropic reviewer families (most rotation slots) therefore always wait on `unbounded_route`. This is correctly fail-closed, but state it, and test that it waits and is not deterministic exhaustion.

### M4. The shapes of the attempt journal, decision file and raw retention need tightening

- **Where:** lines 59–89, against `diagnosis.py:306–310`.

**a. `attempts.json` is missing fields:**
- attempt kind (original or repair) and the repair ordinal's scope (per route or global);
- route versus pool;
- `lease_id`, `invocation_id` and reservation `call_name`;
- terminal phases beyond pending/completed: valid, malformed, interrupted-reconciled, denied;
- which call name an original judgment on a fallback route uses (reusing `diagnosis-<id>` makes names ambiguous across routes);
- whether a crash-interrupted, reconciled attempt counts as that route's one original judgment.

**b. Raw-byte retention collides with the existing producer.** `persist_factory_bug` writes `raw-result-<canonical-json-sha>.json` by re-serializing through `atomic_json`.
- If the dispatcher first stores the raw bytes under the same convention, the producer overwrites the bytes the design says to keep.
- Non-JSON bytes would also sit in a `.json` file.
- Use a distinct name keyed by the byte hash (for example `raw-bytes-<sha256>`), and say the producer never overwrites it.

**c. Decision versus finding for `factory_bug`.** Specify which file is written first, and what replay does for a decision with no finding, a finding with no decision, and the two disagreeing.

### M5. The stage-receipt schema and the gate-to-status mapping are undefined

- **Where:** lines 125–142, against `extensions.validate_snapshot` and `gate_state`.
- **Specify the receipt:**
  - file naming and versioning under `work/evidence/extension-stages/` (per stage, per version, per case digest?);
  - exact fields and schema version;
  - overwrite rules;
  - how a receipt maps onto snapshot rows: is `binding_sha256` the full input fingerprint, and is `evidence_sha256` the receipt's digest?
  - the stress receipt's source: which report, and how coverage completeness is proven.
- **Specify the status mapping** from existing outcomes to pass/fail/pending:
  - `failed_detail.error` (operational);
  - `review_inconclusive`;
  - G10 capped or no-submission;
  - gate crash salvage from `restore_gate_crash`;
  - early-check problems.

  Without it, an implementer could score infrastructure failures as `fail`.
- **"Evaluate any entry passes ... even if the ordinary traversal stopped earlier"** (lines 172–173) needs a defined traversal, because `run_gates` stops at the first failure and later gates (for example G10 after a failed G3) may not be runnable. Alternatively, state that `progress()` returns pending for them, and what happens then.
- **Gate cache:** say why `gate_state.save`'s cache record is not extended instead (zoom-out reuse). "Do not make additional gates reusable" is a valid reason, but say it here.

### M6. Exits that are not terminal have no defined stop label or path back to B

- **Where:** lines 30–32, 150–151, 170–171, against `diagnosis.pending_projection` and `batch_service.py:278–280`.
- **The gap:** `pending_projection` returns None for a completed `close_to_passing` decision and for an active extension. B's `_enqueue` queues a resume only for a present projection or an unknown-total exhaustion.
- **Interfaces §8 says** "an interrupted extension resumes as ordinary same-owner work".
- **The design must name, for each exit:**
  - pre-admission provider wait or `money_wait`;
  - reconstruction pending or interrupted;
  - crash, provider wait or infrastructure stop during an active extension;
  - a completed decision whose worker died before admission;
  - in each case, the `terminal_stop` literal and the existing B path that relaunches it (the provider-wait queue, the money-wait queue, or orphan resume).
- **Otherwise:** state that these cases wait for B's adapter and retire at the batch bound.
- **Interface contract:** lines 150–151 ("remains pending until normal continuation") are an interface contract and need exact stop labels.

### M7. The settlement/ACK split and the fail-closed test need concrete seams

- **Where:** lines 34–49 and 191.
- **Which card decides "unknown at restore":** name the field read, for example the archived `checkpoint_card.case_budget.total_spent_usd is None`, never the post-settlement card.
- **No freeze before ACK:** state that the unknown-total run does not call `queued_inputs`. Otherwise the frozen ledger would hold a total B has not yet acknowledged, and the manifest would bind the pre-ACK generation.
- **Untestable assertion:** "No admission while B runtime is disabled" has no seam the worker can observe. `DIAGNOSIS_ENABLED` exists only in `batch_service.plan`, and `job_config.install` accepts same-owner source transitions. No worker flag may be added (line 17).
- **Required:** say that the fail-closed property is B's planner returning `diagnosis_unavailable` with an empty queue. Specify that test, plus worker-side refusal without a verified job authority. Do not imply a worker toggle.

## Nits

- **N1. Deletions.** "Delete the ordinary build/repair fall-through" (line 180) should name exactly what goes, per stream-d.md:
  - delete: the post-loop `builder-precheck` call and its re-checks (`run.py` ~1436–1440);
  - keep: the stop emission (~1415–1434);
  - delete for dispatched cases: the `build()` call (~3043).
- **N2. Cost (Heilmeier).** State the worst-case diagnosis call count per immutable input: 2 × approved same-family routes. Also state that reconstruction model calls draw on the same job commitment.
- **N3. Crash between reservation and admission.** `reconcile_reservations` charges the full reserved writer maximum as an estimate for a call that was never invoked. This is acceptable as conservative behaviour, but state it so the test does not expect zero.
- **N4. Line 41.** "B must collect and acknowledge the known total before the next ordinary resume". Use "next diagnosis resume", as interfaces §8 does.

## Answers to the review brief

- **Isolation against the passed input design.** The intent is compatible. The text does not grant new permission to expose factory keys, and it leaves the per-invocation scratch behaviour as it is. But "reuse `make_pilots`" would copy the runner's opencode credential store. Today's opencode transport also passes every provider's credential to the role. M1 must be resolved for the isolation claim to hold.
- **Proposal and admission order.** This is feasible, and the snapshot survives:
  - `admit` copies the case and evidence at reservation time;
  - the existing pre-writer `late_recovery.invalidate` deletes only `gate-continuation.json`;
  - the new stage receipts are untouched, provided snapshots never reference `gate-continuation.json` or the live gate cache (state this).

  B1 is the defect: as written, the first admission is unreachable for `budget_exhausted`.
- **Baseline reconstruction with no writer calls, staying pending on missing evidence.** Not as written (B2). It needs a stress-only evaluator, isolated output roots for the entry revision, and in-place evaluation of the live outcome revision. Otherwise `propose()` cannot match and live evidence is overwritten.

## Validation boundary

This review covers design readiness only. No files were written, and no commits, tests, suite runs, launches, cloud work, model calls or decryption were done. I make no claim about the 210eb39 focused tests or the diff-24 full suite. No Murphy row closes, and all A/B/E activation stays gated.

## Elephant resolution

*(to be completed by the elephant)*

## Elephant response

All findings accepted; none rejected. B1 will use a lock-revalidated proposal as the explicit ordinary-limit bypass while preserving B's committed-total check. B2 will reconstruct the entry in a separate evaluator process with private work/bench outputs and a reserved bench slot, then re-evaluate the unchanged live outcome in place so propose can compare identical evidence. The stress-only evaluator, exact record schemas, role/environment/path policy, runner insertion point, route accounting, nonterminal stops and current B adapter gaps will be named. No code may be wired on this failed design. The input increment remains independently passed and unchanged.

## Revision for design round 2

The next implementation boundary is narrowed to worker diagnosis entry, replay,
isolation, retry and durable decisions. This is a sub-increment of the requested
dispatcher, not a reduction of the overall diagnosis-and-extension task. It
cannot invoke an extension writer: close-to-passing and active-extension state
stop `extension_comparison_pending`. B1/B2 and extension-specific M5/M6 remain
accepted and open for a separate concrete extension addendum; their earlier
sketches are explicitly unqualified. No blocker is rejected or marked resolved
by this scope boundary.

For this diagnosis slice, M1 now names make_pilots' no-copy mode, a no-bench-ports
wall (including early incomplete cases), exact root-owned path chain, privileged
descriptor reader, per-driver environment keys and disabled built-in web tools.
It also names the temporary UID permit for A's bounded loopback transport; the
wall otherwise blocks that transport too. M2 pins the entry before startup
mutation and the archived-role qualification/opencode path. M3 excludes all pools
for a deterministically failed route and detects exhaustion before awaiting A;
unbounded routes still wait. M4 gives strict journal/decision fields, distinct
raw-byte names and decision/finding write and replay order. M6 names exact stop
labels and openly records current B adapter gaps instead of inventing a resume
path. M7 uses the archived card_total result, forbids pre-ACK snapshot creation,
and tests B's actual disabled planner separately from worker authority refusal.
N1–N4 are incorporated in the applicable diagnosis text and retained extension
obligations. A fresh reviewer must assess this narrowed design before code.

