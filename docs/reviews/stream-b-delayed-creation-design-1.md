# Goldfish design review: `docs/designs/stream-b-delayed-creation.md` (design review 1)

**Reviewer:** fresh goldfish, read-only. Mode: REVIEW. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`.
**Worktree:** `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-ded79ec5`, branch `t3/batch-service-control-vm` at `0c4eb3a`. The design file is untracked.
**Read:** `docs/ENGINEERING.md`, the three persona files, both standards, the design, `docs/reports/stream-b-preparation-preflight-20261031.json`, `bin/boat-launch-guards.sh`, `bin/boat-spend`, `factory/control_resume.py`, `factory/batch_holder.py` (journal, reserve, reconcile, `_created`, `_retirement`, scans), `factory/launch.sh` (only its `boat` call sites), and `boat new --help` from the local 1.0.85 CLI.
**Public provider pages fetched (read-only, no auth):** `docs.boat.dev/api/reference/sandboxes/create-sandbox`, `docs.boat.dev/billing`, `docs.boat.dev/long-running-tasks/auto-stop.md`. The quotes below came through a summarizing fetch tool. The parent should save the pages verbatim before relying on any wording.
**Not done:** no edits, workers, paid calls, secrets, VM access, push or subagents. I did not run the test suite.

---

## Bottom line

The design is right that an active cleanup/admission adapter cannot be built today without inventing provider facts. It is also right not to add dormant machinery. But the documentation-only handback, as written, would send the parent the wrong blocker list:

1. It treats provider auto-stop as only "cleanup eligibility". The public docs give more than that: a bound on each worker that counts from creation, independent of the control VM.
2. It ties the legacy launch's fate to provider evidence. The repo's own launcher invariant, and the holder's existing reconcile rule, already speak to it locally.
3. It keeps a code path that releases holds by inventory subtraction, which the design itself forbids. That path can be deleted safely now.

**Verdict: NOT PASSING.** Three blocking findings are open. The scope "doc-only, blocked" is acceptable only after the evidence list is corrected (B1, B2). I recommend adding the one safe deletion (B3).

---

## Blocking findings

### B1. Blocker: the required-evidence list misstates what the provider already documents
**Scope:** lines 28–36, 64–72, 81–83. Personas: design_critic (faulty assumptions), zoom_out (root problem).

The design says the TTL "promises cleanup eligibility, not a billing-stop bound" (line 23). It says a finite billable lifetime "even if creation, visibility or deletion is delayed; include control-VM unavailability" is missing, and that "a timer alone cannot provide this" (lines 68–69). The public docs say otherwise:

- **Auto-stop is the provider's own timer, counted from creation or resume, not from activity.**
  - "from creation or from the last resume, not from your last activity."
  - "Your own jobs do not move the deadline."
  - The only automatic extension is a running `boat prompt` agent.
  - Manual extension needs `boat extend` / `PATCH`.
- **Stopped workers stop costing compute.**
  - `ttlSeconds` means "seconds before automatic archival"; the stop "starts within about 5 seconds".
  - Billing: per second; "boat never counts stopped time"; "A stopped sandbox costs nothing in VM time."
- **The factory never extends, resumes or prompts a worker.** I grepped `bin/`, `factory/` and `control/` and found no `boat extend`, `boat resume`, `boat prompt` or `fork` call. `factory_auto_resume` restarts work inside the original TTL envelope.

So a worker created late, after the local deadline, still stops about TTL + seconds after its own creation, whether or not the control VM is alive. That is exactly the control-VM-independent per-worker bound the design says is missing. Because the cap is in dollars, a relative bound per worker plus a hold per create that is never released without proof is enough. No absolute deadline is needed. The design dismisses this as "relative archival … not the needed absolute spending cap" (line 36) without showing why the dollar inequality needs an absolute bound.

The same reasoning cuts the "read-only request-resolution contract" item (lines 66–67) down from a safety prerequisite to a throughput item. An unresolved create keeps its full hold, which fails closed; resolution only releases holds earlier.

**The provider gaps that really remain, all narrower than the design's list:**

| # | Gap | Why it matters |
|---|---|---|
| a | Billing while a stop is `pending` or `failing` | The docs say a failing stop "is retried automatically until the sandbox archives", with no time bound. |
| b | Paid starts | Starts above plan limits are paid ("starts above a limit are paid, up to `startLimitsWithWallet`"), at an unknown price. |
| c | Egress | Not documented. |
| d | One CLI invocation may create more than one worker | Internal retries in Boat CLI 1.0.85 under the 300 s kill (`guard_new` line 75) are unknown. Calling the API directly once, with `Idempotency-Key` and `count=1`, would answer this. |
| e | Current verified rate | The preflight has `current_default_rate_verified: false`. `boat-spend` uses a static rate table dated 2026-10-18. |
| f | Charge for the AI credentials proxy | Listed in the billing doc. `--no-env` probably avoids it, but this is unverified. |

**Fix:** Replace lines 64–72 with the documented bound and this residual list. Cite the pages and the date fetched, and save them as retained evidence. Do not record the TTL as proving the cap. Gaps a–e still keep admission refusing, so the blocker stays open. It is just stated correctly.

### B2. Blocker: legacy disposition is wrongly made to depend on provider evidence
**Scope:** lines 14–20, 41–42, 73–75. Personas: zoom_out (reuse), design_critic.

The preflight lists b275's files as only `controller.lock` and `launch.json`: no `ids`, no `monitor.sh`, no `new.*`. Since the initial commit `4936347` (2026-10-26), the repo enforces this ordering:

- `control_resume.py` writes `launch.json`, then execs `launch.sh`.
- In `launch.sh`, the only `boat` calls before `guard_init` (line 365) are `ssh` and `list` (lines 176, 350). They do not create anything.
- `guard_init` truncates `ids` at `bin/boat-launch-guards.sh:14` before anything else.
- The only create is `guard_new`. It runs after `guard_init`, and the shell redirect opens `new.$serial` before `boat new` runs (line 75).
- `git log -S` confirms both the `: > "$state/ids"` line and the `> "$state/new.$serial"` redirect date from 4936347.

So under any launcher release in this repo's history, a launch directory with no `ids` and no `new.*` never submitted a create. `batch_holder._reconcile_one` (lines 345–354) already encodes this exact rule: both locks free, no `new.*`, missing `ids` treated as empty, therefore `preflight_refused`. In addition:

- `control_resume --resume-launches` skips b275, because it has no `monitor.sh`.
- `--resume-launch b275` exits with "launch initialization incomplete" before exec.

Nothing can create from it.

The design's "source inspection cannot reconstruct it" and "historical provider logs/support evidence" (lines 41–42, 73–75) are therefore the wrong prerequisite. **What is actually needed:**

1. A fresh read-only listing on the VM: file list, mtimes, and the `launch.json` argv/environment.
2. A check that b275's mtime is not older than the release that was deployed on the VM, so the ordering invariant applies to the code that actually ran.
3. A recorded disposition citing the invariant and `_reconcile_one`.

This is a parent/VM step, not a provider-contract dependency. I am not claiming it is closed: step 1 has not been done in this review, and the preflight is historical.

**Fix:** Rewrite the legacy item with this local-evidence route and its two residual checks. Also say which code currently treats b275 as blocking admission. I found no admission check that scans non-journal launches, so the design should state whether "blocks activation" is a code rule or a policy rule.

### B3. Blocker: the design forbids inventory-subtraction release but keeps the code that does it
**Scope:** "What it deletes" (lines 90–95) against `bin/boat-spend:112-124`. Personas: zoom_out (delete before adding), implementation_readiness.

At lines 112–124, `boat-spend --check` marks expired holds `reconciled_expired` whenever one complete, idle `list --all` page is seen. That is the "inventory subtraction" the design rules out at line 56. It also lets an unknown-outcome create (`new.N.pending`) lose its hold after TTL + 1800 s.

It is covered by `tests/factory/test_isolation_timeouts.py:409-418` and documented in `docs/designs/isolation-timeouts.md:112,121-123`. Deleting it fails closed: expired holds stay reserved until `--finish`. It needs no provider guarantee, adds no new path, and with the gates false it changes no live behaviour.

The design says "No runtime code is deleted", which leaves a known contradiction in the code.

**Fix:** Either make this deletion the increment's code change, plus the test inversion and an update to `isolation-timeouts.md`, or explicitly justify keeping it as a named open item. Deleting it is the coherent, safe implementation available now.

---

## Major findings

### M1. Major: no cumulative-cap baseline is described (Heilmeier "state of the art")
**Scope:** lines 77–83.

The current `--check` compares the estimate against the per-launch `--max-spend` and against balance minus other holds. There is no "settled + holds + new ≤ USD 5" across the batch. The design should say this plainly, so the parent knows the USD 5 cumulative rule is a new mechanism and not an adjustment. Without that, a reader can assume `--max-spend 5` already meets it.

### M2. Major: the wallet is not a fallback cap, and the design should record why
**Scope:** line 72.

The billing doc says the wallet "can go below zero during the grace period" (24 h, "Your sandboxes keep running") and "A personal account has no dollar cap". Org "per-member caps on … time and sandboxes" exist but were not examined. Record that the wallet is not a bound. Add the org per-member cap as a possible provider-side hard bound to qualify, because it may close gaps a–c of B1 at once.

### M3. Major: the plan leaves design choices to the implementer
**Scope:** lines 46–62.

This is acceptable for a blocked design, but the doc must not be read as an implementation plan. Undecided:

- whether the adapter is the CLI or the direct API (Idempotency-Key and labels exist only in the API);
- the intent record's schema and location;
- the supervisor's unit, interval and lock order relative to `money.locked` / `operation_lock`;
- hold formula terms;
- the stop-state polling contract.

Lines 85–88 should say explicitly that this section is a direction, not a plan.

---

## Nits

- **N1.** Line 15: the path `../reports/...` is relative to `docs/designs/`. Write `docs/reports/stream-b-preparation-preflight-20261031.json`.
- **N2.** Heilmeier cost and timeline answers are missing, even for the next qualification step (who reads the provider docs or contacts support, and how long it takes).
- **N3.** `bin/boat-launch-guards.sh:189-190` tells the operator to run `bin/hcloud-boat delete` and calls the "expires label" the backstop, even under `UNBUG_CLOUD=boat`. This is wrong guidance on the Boat path. It is out of this design's scope, so record it as a register candidate.
- **N4.** Line 31 says replay "can initiate a new creation". The docs are narrower: within 24 h, an identical body returns the same sandbox. A new creation happens only after a pre-creation failure releases the key (~2 min) or after 24 h. Not blocking, because the "do not replay after expiry" conclusion still holds.

---

## Is a safe, coherent implementation possible now?

**Partially, and it is small:**

- **Yes:** B3, the deletion in `boat-spend`. It is safe, fails closed, needs no provider fact, and fits "delete before adding".
- **Yes, as evidence and records:** B2, the legacy disposition through the local invariant. It needs one fresh read-only VM listing by the parent; no new code.
- **No:** the intent journal, the supervisor and cumulative USD 5 admission. B1 gaps a–e are real unknowns. Building admission now would only refuse, which is the same as the existing false gates. Do not build it yet.

## Readiness verdict

- **Design review: FAIL.** B1, B2 and B3 are open.
- **Implementation readiness of the cleanup adapter: NOT READY.** This is correct, but for the narrower reasons in B1.
- **No Murphy row closes.** Rows 6, 27, 28, 35 and 51 stay open. None of the above claims a blocker is fixed by being documented.

## Next steps for the elephant

1. Rewrite lines 22–23, 28–36 and 64–75 per B1. Save the three provider pages verbatim under `docs/reports/` with the fetch date.
2. Rewrite the legacy section per B2. Hand the parent the read-only VM checks: listing, mtimes, `launch.json` argv/environment, and the deployed release's commit.
3. Decide on B3. I recommend deleting `bin/boat-spend:112-124`, inverting `test_isolation_timeouts.py:409-418`, and amending `isolation-timeouts.md`. Then run the full suite (`uv run --with numpy --with scipy python -B tests/run.py`) to a committed log.
4. Address M1–M3 and N1–N2 in the text.
5. Get a fresh design goldfish re-review, then a diff review of the result. Keep both activation gates false.
6. Add a provider-qualification question list for gaps a–f, plus org per-member caps (M2), as the explicit prerequisite to the adapter increment.

## Elephant response

Accepted B1–B3 and M1–M3. Revised the design to implement the expired-hold release deletion and correct the provider and legacy evidence requirements. No finding rejected; fresh design review requested before code changes. N3 is retained as a follow-up candidate in the design; no live failure or row closure is claimed.
