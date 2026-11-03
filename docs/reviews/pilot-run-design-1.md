# Goldfish design review: `docs/designs/pilot-run.md`, round 1 of 2

**Mode:** REVIEW, read-only. Personas used: zoom_out, design_critic and implementation_readiness. Standards used: heilmeier and implementation-readiness.
**Scope:** worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, HEAD `abc11ef`. The diff from `b75c9b4` touches only `docs/designs/pilot-run.md` (+60 lines). I changed nothing, ran no tests, made no live calls and used no secrets.

**Verdict: does not pass. 1 blocker and 3 majors are open.**

The gap sizing is mostly accurate when checked against the code, and it reuses the right path. Before the founder sees a ceiling, two things need fixing: the per-lifecycle time window is copied from plumbing practice, and the money is anchored to a weak source.

## Claims checked against source (accurate)
- `HOLDER_ENABLED = False` (`factory/batch_holder.py:26`). `active()` returns `HOLDER_ENABLED or practice.active(...)` (`:37-39`). `practice.py` is pinned to exactly one manifest, `b-plumbing-practice-2` (`EXPECTED`, `matches`).
- `DIAGNOSIS_ENABLED = False` (`factory/batch_service.py:21`). `plan()` (`:332`) has no caller outside `batch_service`. `ordered_queue` (`:299`) is only returned, never drained. `diagnosis_dispatch.py` also gates on the same constant (`:242`, `:255`, `:345`).
- `bin/boat-spend:90` and `:137-144` refuse with "infrastructure liability unsettled" when any `reserved`/`finished`/`reconciled_expired` row exists. Sizing this as L, and fixing it before admission "including practice liabilities", is correct.
- `practice_cleanup.py` is hard-bound to `practice.BATCH` and `practice.TIMING` (`:21-33`, `:59`, `:122-125`).
- The money citations exist: `$15.0531879` (`stream-d.md:626`), min($11.63, observed credit) (`router-shared-paid-spend.md:102`), and the founder-accepted prepaid balance under $5 with no top-up plus TTL (`practice-run.md:17`).
- Reuse direction is right. One opt-in at the existing `batch_holder.active` / `key_holder` / `batch.bind` sites and no second launch API both match the One-launch-path rule.

## Blocker

**B1. Lines 12–13, 22 and 47: the time and lifecycle limits make a pass unlikely by construction, and nothing records this.**
- Line 22 copies practice's `TIMING` (30-min run, +45-min deletion, 60-min TTL; `practice.py:9`) onto real cases. The real-case default worker TTL is 8 h (Murphy 5, `factory/launch.sh:24`).
- With at most two lifecycles per case, each case gets about 1 h of worker time. Diagnosis runs on the worker itself ("Same-owner worker diagnosis", `diagnosis_dispatch.py:1`), so it must also fit inside that window.
- Line 12 lets the second lifecycle be either a checkpoint resume or a diagnosis resume, not both. A real case cut off at 30 minutes will use its one resume on the checkpoint. No lifecycle is then left to act on a diagnosis, so the case cannot have a real routed outcome after it. The pass condition (≥1 real diagnosis plus a routed outcome) is mostly decided by the cutoff, not by how the case behaves.
- The arithmetic: six sequential lifecycles × 60-min TTL = 6 h, the whole proposed absolute window (line 47). `practice.admission` refuses when `deadline − now ≤ ttl_seconds`. If the earlier lifecycles run to TTL, the last one can never be admitted. Setup and diagnosis time make this worse.

**Fix:** pick one and write down the trade-off.
- **(a)** A per-lifecycle run/TTL backed by real-case duration evidence, and recompute the window and the infrastructure draw from it.
- **(b)** Say plainly that the pilot measures what happens under a 30-minute cutoff, and change the pass rule to match.

Either way, give each case its own checkpoint-resume count and diagnosis-resume count, and make the window at least lifecycles × TTL plus margin.

## Majors

**M1. Lines 32–35: the $20 is anchored to a weak source, and the repo's own cost evidence is left out.**
- `factory/batches/b-practice-20261031.json` is a **`--dry-run`** legacy manifest. The current practice manifest is `b-plumbing-practice-2` at **$19.99**, for one plumbing case on cheap routes. Neither is authority for real-case money.
- The repo has real receipts. `docs/designs/stream-d-cost-evidence.json` shows real cases e15450 and 873d7f spending **$51.28–$53.64** against $70 limits. Murphy 9 records a $50 default per-case budget.
- The figure is not invented, but calling it "current authority" misleads.

**Fix:**
- Call $20 a founder exploration ceiling, about 40% of a historical real case.
- Cite the cost-evidence file.
- State what follows. With diagnosis headroom reserved first (line 23), a `close_to_passing` extension (one writer round, up to $15.05) is probably unfundable. The realistic outcomes are budget exhaustion, then diagnosis, then retire or factory-bug.

**M2. Lines 57–59: the pass rule clashes with the expected path and leaves "routed outcome" undefined.**
- "Cap stops are incomplete" does not separate two different events:
  - a **case** spending its $20, which ENGINEERING §3 says is exactly the diagnosis trigger;
  - a **batch** ceiling or deadline abort.
- Read literally, the most likely real diagnosis path counts as incomplete.
- "Authenticated routed outcome" is not defined. Under the pinned release, a factory-bug result can only be *held*: line 20 says so, and new-batch-service-4 confirms that `batch.bind` rejects carry-over. An extension is unlikely (M1). Retire is likely.

**Fix:**
- List which terminal routes count: retire, factory-bug held, and an extension admitted or refused by money.
- Classify case-budget exhaustion followed by diagnosis as the expected path, not a cap stop.
- Keep batch-ceiling, deadline and refusal stops as incomplete.

**M3. Lines 36–41: the "$5 infrastructure total" is a real ceiling of min($5, Boat balance left after practice), and nothing checks that the balance can cover a lifecycle.**
- Practice's bound *is* the prepaid balance. The pilot draws on whatever practice leaves.
- Lines 36–37 and 47 present $65 as the total, but the real bound may be lower, and no step confirms the balance before admitting a 60-minute worker. The same applies to OpenRouter's min($11.63, credit) minus prior charges (line 40).

**Fix:**
- State the ceilings as min(proposed amount, measured remaining balance).
- In step 2, read the balance and confirm top-up is off. Abort if the remaining Boat balance cannot cover one full TTL lifecycle.
- Report the measured figures to the founder alongside the $65.

## Nits
- **N1, line 18:** `HOLDER_ENABLED` lives in `batch_holder.py:26`, not in `practice.py`. Point to the single place the opt-in goes: next to `practice.active` inside `batch_holder.active`.
- **N2, line 20:** item 7 is a precondition (lane 2), not pilot work. Mark it "not counted in pilot sizing" so the S/M/L list is the pilot's own work only.
- **N3, Heilmeier:**
  - There is no explicit "Risks/payoff" line. One sentence would do, for example: likely outcome is budget exhaustion; payoff is the first real diagnosis receipts.
  - The timeline for building the M/L gaps is missing. A rough estimate per gap, or "unknown until lane-2 merge", is enough.
- **N4, lines 26–28:** new-stream-d-current-comparison-1 matters only if an extension happens before a factory-bug resume. Given M1, say that it probably does not apply.
- **N5, line 21:** rename the "Multiple lifecycles" row. The `boat-spend` refusal blocks the **first** pilot lifecycle too, because practice leaves a row behind.

## Not flagged (intentionally)
- Missing full implementation designs for each gap. The brief says this is a gap-sizing proposal.
- The Mac dependency. The holder runs on the control VM (practice step 4 disconnects the Mac). The key that stays on the Mac is only for the founder's rewrap.
- No-replacement scope and the account-distinctness waiver. Both are correctly sent to the founder for approval.

---

Writer disposition for round 2: accept B1 option (b), all majors and nits. Revision explicitly proposes cutoff exploration, separate checkpoint/diagnosis slots, nine lifecycles plus margin, receipt-based cost context, distinct case/batch stop semantics and measured remaining infrastructure credit. Parent's ownership split is recorded. All financial/scope changes remain proposals, not live authority. No practice state changed.
