# Item 8 design review: live qualification and switch-on (`docs/designs/stream-d.md:3384–3507`)

**Verdict: FAIL — 4 blockers, 4 majors, 4 nits.**

The section is honest about what it doesn't know. It authorizes no code or spend, its $100 is a ceiling rather than a price, it forbids fake evidence and relabeling waste, and it keeps rows 9 and 39 open. But as written it can't be run: three structural facts in the current code make several scenarios impossible, and the plan treats them as optional instead of listing them as required work.

## Blockers

**B1. The USD 100 budget can't reserve a single Claude call.** (lines 3412–3418, scenario table 3444–3450, 3457–3458)
- Every Claude call must reserve its maximum before it starts. That maximum is fixed at $50 (`factory/token_prices.py:95`, `claude_gate_maximum`), and `budget.reserve_invocation` refuses any call where spent + pending + $50 is more than the job's commitment.
- Every scenario cap is $5–$25, so no Claude call fits anywhere.
- Only three model routes have an enforced maximum: Claude Opus ($50), MiMo (about $1.71) and DeepSeek (about $1.17). OpenAI/Codex has none.
- The strong calibrator must be Anthropic or OpenAI (`model_runtime.py:151`), so G10 (scenario 4) can only run on Claude, which doesn't fit $15.
- The account-2 check is meant to ride on a Claude call in scenarios 1, 5 or 6. That can't happen either, so switch-on is blocked by design.
- The plan says to use "A's reviewed, enforced smaller profile or leave the scenario blocked". No such profile exists, and no work item owns building it.
- **Fix:** make a smaller enforced Claude profile a hard prerequisite with an owner and acceptance tests, sized below each scenario cap. Then check whether the token limits that profile implies can still complete a real writer, stress or G10 call. A writer round alone has cost up to $15.05 (`stream-d.md:626`). If they can't, say which scenarios are infeasible at this budget.

**B2. "One throwaway worker" is impossible with the current holder.** (lines 3402–3409, 3438)
- Each holder operation owns its own `worker_id`.
- A resume launch requires the previous operation to be retired, and retiring it deletes its worker (`batch_holder.py:146–147`, `:308–369`). B's plan says the same thing.
- So scenario 1 (interrupt, then resume through B), scenario 2 (restore) and scenario 5 (resume after the fix) each need at least one new worker. The full set needs several.
- The plan pushes this into "resolve in the manifest… otherwise stop". That leaves a core design decision to whoever writes the manifest, and guarantees the stop.
- The $10 infrastructure reserve and the two-hour lifetime are sized for one worker.
- **Fix:** either redefine the rule as "at most one live worker at a time, each with verified deletion before the next", with a creation-to-deletion bound per worker and a maximum worker count that fits inside $10, or design worker reuse as a separate reviewed B change. Pick one here.

**B3. The plan has no source for its "real saved candidates".** (scenarios 1, 4, 6, 7)
- B's own record says no authenticated, admissible checkpoint exists. The only saved archive is a legacy one that the control key can't decrypt, and it has no batch binding. Under the one-launch-path rule it can't be imported.
- Scenario 6 needs a near-pass case with complete stress and an ordinary exhaustion. Scenario 7 needs a real nonconverging exhausted case.
- Producing those from scratch costs a full case: recorded cases ran $51–$52, and the design itself says a writer + stress + gate package can't be priced. That doesn't fit $25.
- **Fix:** name each candidate (case ID, archive hash, why it is eligible), or name the reviewed bootstrap path from B that makes it admissible. Otherwise mark scenarios 4, 6 and 7 as not runnable at this budget.

**B4. "Enable only the scenario under test" has no mechanism.** (lines 3405, 3460–3461, 3489–3494)
- `DIAGNOSIS_ENABLED` is a constant compiled into the release, not a policy setting.
- `replacement_policy` applies to the whole batch, and its manifest hash is frozen when the batch is created.
- A replacement job copies its root job's template (`batch_service.resolve_job`), so it also copies the root's `requested_total_usd`. A replacement therefore doubles the commitment unless the root job is set at half the cap or less. That contradicts "replacement commitment inside that scenario's cap".
- In one batch with diagnosis on (needed for scenarios 5–7), the deliberate exhaustion in scenario 2 would trigger a real diagnosis and possibly a replacement.
- **Fix:** decide the batch layout now. For example: batch α with diagnosis and replacement off for scenarios 1–4; batch β on a separate practice release with diagnosis on and replacement enabled for scenarios 5–7. Fix how each job's `requested_total_usd` is derived so that root plus replacement stays within the cap.

## Majors

**M1. The live per-gate version check has no budget.** (lines 3477–3479) Changing a release and a gate's scientific version, then rerunning the affected gates, is paid gate work. It isn't in any scenario cap, and it isn't in the table, even though the plan claims "$90 includes every model call".
- Fix: make it a scenario with its own cap, or move it inside scenario 5 or 6 explicitly.

**M2. Scenario 5's cross-release support is written as conditional, but it's always needed.** (line 3448) "Fix via reviewed release, resume original" is cross-release by definition. Operation identity includes `release_sha256`. "Must be merged first *if this path needs it*" should be an unconditional prerequisite with a named owner.

**M3. Rollback through "the reviewed release/policy" is vague.** (lines 3504–3507) No policy setting for diagnosis exists. Rollback is a new release with the flag False, rolled on at a checkpoint. Say that explicitly, and state that `plan()` then returns `diagnosis_unavailable` and dispatch stops at `diagnosis_pending`, so pending entries are kept rather than dropped.

**M4. No timeline (required by the Heilmeier standard).** There's no wall-clock estimate per scenario and no batch deadline. A two-hour worker lifetime is asserted without checking it against real writer, stress, G10 and diagnosis durations.

## Nits

- **N1.** Scenario 4's wording, "submits a guard BEFORE reaching its existing cap", reads as if the attempt could finish uncapped. The acceptance check should say: guard submitted **and** attempt ends with a cap `stop_reason`, separate from the capped no-submission attempt. The later line "natural cap-with-guard" already has the right meaning.
- **N2.** Scenario 5: state that the "fix" release removes the injected fault, and which receipt proves the waste was charged once.
- **N3.** Section 3 of `ENGINEERING.md` needs replacements to launch immediately. With concurrency one, "immediately" can only mean "queued first by priority" (`ordered_queue`). Say so.
- **N4.** Item 7's remaining work (`stream-d.md:3370–3382`) is a prerequisite. Link it by name, not just "item 7 must be merged".

## What is satisfied

- Rows 9 and 39 stay open, with explicit conditions for closing each.
- Rows 8, 10, 11, 12, 15 and 21 are confirmed closed in the register, and the plan correctly keeps their closure scoped to saved artifacts.
- Row 13's live check isn't waived.
- G10 semantics match item 5 (lines 2822–2844): a capped or absent guard is inconclusive, never `wrong_fix`.
- All three diagnosis outcomes are covered, and boundary replays are labeled as replays.
- Account-1 fallback requires real provider rate evidence; missing credentials, occupancy and outages can't unlock it, and identity is confirmed privately.
- The $100 approval is separate from B's $25. There's no top-up or relabeled headroom, and unknown usage counts against the bounds.
- Prerequisites point to B's actual blockers, including the $50 dry-check.
- The flag stays False in normal releases, the activation commit is separately reviewed and founder-approved, there's no monkeypatching, and missing evidence keeps switch-on blocked.

This was a read-only review of the design text, B's practice plan, the Murphy register and the relevant router, budget, batch_service and batch_holder code. I made no edits and ran no test suite.

## Elephant response

Accept all blockers and majors. Revised plan below will name prerequisite owners, fixed batch layout and commitment split, candidate eligibility blockers, single-worker lifecycle prerequisite, rollback and bounded scenario time estimates. Fresh review required. No live authorization or spend.
