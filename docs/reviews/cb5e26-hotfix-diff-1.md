# cb5e26 hotfix diff review 1

Goldfish: fresh general-purpose subagent (Claude), Mode: REVIEW, given the goal and the diff only.
Reviewed: `git diff 5be58a7f..hotfix/cb5e26-diag` at ab6de536 (PR 203 diagnosis --continue and PR 205
cached-window cherry-picked onto 5be58a7f, the release cb5e26-h5 runs).

## Review (verbatim summary)

Verdict: PASS. Nothing blocks the release.

**Verified**
- The diff equals the two PRs line for line: PR 203 (3dfdde3c..4abb1ac0) and PR 205 (0b3a4f8c..5c4a47da)
  against 5be58a7f..HEAD, all 14 files (4 factory, 4 test, the fixture, 6 docs); the fixture blob is the same
  object. Only conflict: token_prices.py, where the PR's context held Neuralwatt's `_request_worst`; it was
  dropped and `openrouter_cached_tokens` kept as in the PR.
- No Neuralwatt or router-retry code (grep for neuralwatt, NW_, capacity_protocol, reserve_retry finds
  nothing); a recursive compare of the base tree and the worktree shows only those 14 files differ.
- Everything the port relies on exists at 5be58a7f (`math`, `Decimal`, `BudgetError`, `self.pilot_home`,
  the `diagnosis` flag, GATED_OPENROUTER prices; OpenCode already pinned 1.19.0, the version the
  `--continue` proof used).
- Gate identity unchanged, by the reviewer's own script on both trees: runner_inputs and dependency_files
  (real glob logic; `*.md` is top-level only, so docs/ and tests/ are never reached) for every gate,
  model_science, judge_dependencies, prompt hashes, release pins and `sealed_audit.delivery_contract()`;
  outputs byte-identical. Bench digest unchanged (d4a7127a... at both ends).
- Tests on HEAD: test_durable_diagnosis_invocation 19 OK (3 skipped, need Linux root), test_cached_window 5,
  test_model_runtime 11, test_model_call_gate_wall 8, test_budget 51 (1 skipped); related test_durable_diagnosis,
  test_durable_step_checkpoints, test_free_routes, test_narrow_fingerprints, test_router_cheap_maxima,
  test_router_paid_spend, test_helper_g10_and_checks pass.
- Reverting each fix's code makes its test fail (cached_window 4 of 5; diagnosis_invocation 1 failure, 1 error).

**Findings**
1. NIT (deploy note), factory/durable/checkpoints.py:132-155. The model verdict-code digest (hashes
   model_runtime.py and model_call_gate.py) moves from the pinned 3429db4f... (raw 898b3f9d...) to 73aa880a....
   Within-step engine-checkpoint receipts of the current step and helper jobs are keyed on it, so helpers must
   run the same release (they are the batch's pool workers, so a plumbing_release to the batch covers them).
   Gate reuse is keyed on gate_state.fingerprint, which is unchanged: G1-G9 and G13-G16 are not rerun. Main did
   not repin for these PRs either; no repin added here (it would be a further change needing its own review).
2. NIT, tests/factory/test_silent_limit.py failed once under load (timing-flaky); passed on base and twice on
   HEAD; neither fix touches its path.

Nothing blocking in the fixes on the older base: `--continue` is added only on turns after the first and
reset in `finally`; each diagnosis gets a fresh pilot home disposed afterwards; reservations still use the
full-price `worst_request`; a null `prompt_tokens_details` is still rejected; the provider charge is the floor.

## Operator checks beside the review
- Old-protocol worker vs the live router (77f25170): this tree's own `_admit`/`finish` (capacity_protocol 1, no
  chain) driven against main's `Store` in a separate process, every model in CHAINS with all accounts: 42 leases,
  0 failures, no Neuralwatt or LATE_ROUTES lane offered; a queued run gave 108 `capacity` waits, all accepted.
