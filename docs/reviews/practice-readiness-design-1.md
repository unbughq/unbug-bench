**Verdict: FAIL** (design round 1 of 2). There are 3 blockers and 6 majors. Both docs answer the safety question correctly: every live gap stops the run before anything is created, and nothing is faked. But the implementation side is not zero-decision yet, and one item is outside the practice scope.

I read only. No edits, network, credentials or workers.

## Blockers

**B1. The roles in the plan contradict the code, and the manifest isn't written out.** (`practice-readiness.md:28-31`, `practice-run.md:18`)
- `--rotation-slot` counts from 1 (`factory/run.py:3176`, choices 1–8). Slot 1 is the first entry in `factory/rotation.json`: writer anthropic, stress minimax, **strong calibrator openai = `codex/gpt-6.1-sol`**, reviewer deepseek. That breaks the plan's "no Codex route", and it doesn't match the planned roles (writer MiniMax, reviewer MiMo, strong calibrator Claude).
- The plan names paid models: MiniMax M3.1 Flash at $0.690001 and DeepSeek V4.1 Flash. The rotation families point at the `-free` routes. The plan says "Claude Opus4.5 compact", but the anthropic family is `claude/claude-opus-5-5`.
- The plan doesn't say which flag carries the MiMo reviewer (`--reviewer1` or `--reviewer2`). It also doesn't override `--easy-calibrator`, whose default is `opencode/glm-5.3-flash-free`, not MiniMax.
- The money fields aren't spelled out as JSON: `money_limit_usd`, `requested_total_usd`, `practice_admission.jobs.practice.{baseline_usd, incremental_usd}`, `replacement_policy`, `opencode_accounts`, case name.
- The existing `factory/batches/b-practice-20261031.json` (dry-run, slot 0, $20, same deadline) has no stated fate. "Historical b3" means `docs/practice/b3/`, not this file.
- **Fix:** put the full manifest JSON in the design, with the exact args array. Use explicit role flags with exact route strings for all roles, and either drop `--rotation-slot` or name the slot whose roles match. Add a test that every resolved role has a `route_maximum` (none is `None`) and none starts with `codex/`. State whether `b-practice-20261031.json` is deleted.

**B2. The watchdog (item 4) is not specified enough to build.**
- `guard_delete_receipt` is a heredoc inside `bin/boat-launch-guards.sh:148`. It depends on the shell variables `$root`, `$spend_file`, `$retire_id` and `$state`. It also refuses a second deletion request whenever `<id>.deletion-attempted` exists without a request file.
- The design doesn't say:
  - where the shared callable lives (a Python module or a shell function), or its signature;
  - how the watchdog gets `spend_file` (presumably from `monitor.sh`);
  - which file the `flock` is taken on, and how the existing `guard_retire` path acquires it;
  - the systemd unit: name, template, `Restart=`, who installs it, and how "active" is checked before `dispatch_started`.
- It also doesn't define behaviour when Boat's own 60-minute TTL erases the VM before the watchdog's admission+60-minute deadline. The deletion call then hits a missing target: is that a receipt, an incident, or held uncertainty?
- **Fix:** name the module, function and lock path. Give the unit text. Set the watchdog deadline strictly before the provider TTL, or define the not-found outcome as a retained hold. Make the watchdog refuse unless `UNBUG_CLOUD=boat`; `key_holder.py:737` and `batch_holder.py:791` already force that.

**B3. Activation scope (item 3) is undefined.**
- "Signed practice manifest" has no meaning in the code. Today the manifest is authenticated by the release/policy sha256 (`batch_money.manifest`); there is no signature.
- The four flag reads behave differently:
  - `batch.py:149`: when the holder is disabled, it refuses only carry-over and `-rN` jobs.
  - `batch.py:168` and `batch.py:178`.
  - `key_holder.py:443`: returns early when disabled.
  - `batch_holder.enabled()`.

  Replacing all of them with one `active(policy)` could change how ordinary launches behave.
- The design doesn't say which process environment carries `UNBUG_PRACTICE_BATCH` (holder, key-holder, the dispatch child).
- **Fix:** define "signed" as release sha + manifest sha + id match. Give the exact new rule for each call site, and add a test that ordinary and legacy behaviour is unchanged when the variable is set for a different id. Name the unit that sets the variable.

## Majors

- **M1. `stage_replacement` (item 1) is out of scope.** The practice manifest disables replacement and diagnosis, and no practice step calls it. It is replacement/carry-over work for item 8 inside the merged money path (`_admit`/`authorize_locked`), which goes against "item 8 separate". **Fix:** drop it and keep the D/B row as a separate hold for item 8.
- **M2. The fault-injection hook (item 6) is not located.** It doesn't name the function and file where collection consumes the marker. It doesn't give the expected journal changes: the `publication_failed` incident, how replay clears it, and how it interacts with `RETRY_LIMIT=5`. **Fix:** name the hook point and list the state transitions as test assertions.
- **M3. Pin tool (item 5) and preflight (item 7) outputs have no format.** The route-pin and "launch-blocked checklist" schemas aren't defined. The design doesn't say whether `docs/practice/b3/preflight.py` is deleted or superseded. **Fix:** give both JSON schemas and delete or retire the old preflight.
- **M4. The design doesn't follow `ENGINEERING.md` step 2.** It has no "what it deletes" section; the only removal is the `authorize_locked` test fixture. It names no Murphy rows, and "no closures" doesn't replace naming the rows touched or adding `new-<topic>-<n>` rows. **Fix:** add both sections.
- **M5. The likely outcome is an abort, and the plan doesn't say so.** Step 1 (b275 debt plus the provider bound on multiplicity and cost) is the most likely abort, and the offline watchdog and fault work only pay off if it passes. **Fix:** state that risk and order the work accordingly in the plan.
- **M6. It fails the plain-language test in `heilmeier-standard.md`.** Terms like "S=0/E=19.99", "b275", "ACK", "r2 refusal" and "Boat admission" go undefined, and there is no plain objective, impact or success exam. **Fix:** add a short plain-English objective and success line at the top of each doc.

## What's already fine

- Every live gap stops the run before creation and returns the specific gap to the parent, with no fabricated proof.
- The $25 total adds up, with no top-up and the shared OpenRouter ceiling.
- The pin doesn't depend on lane 2, and item 8 stays separate.
- The Hetzner parking path (`hcloud-park`) is not reachable, because the key-holder forces Boat.

## Elephant disposition
All findings accepted. Revision 2 spells out the manifest, shared lifecycle helper,
unit/locking/readiness contract, exact activation call sites and output schemas.
Queued-child staging is removed from this one-worker plumbing scope and remains
an explicit item-8 offline hold. Failure-injection transitions, deletions, Murphy
rows and likely zero-cost abort are documented. No blocker is rejected.

