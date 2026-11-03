# Three-case real pilot — design only
Founder decision (2026-11-02): replace full item 8 with three fresh REAL cases,
diagnosis ON and existing accounts, after practice PASS and lane-2 item-7 PASS.
Proposal only; goal: real diagnosis receipts. Risk/payoff: cheap/time-limited cases will probably exhaust or pause, not seal;
we learn their outcomes under explicit limits, not normal full-case completion rates.
## Scope, timing and remaining work
Exactly three fresh cases, one batch, concurrency one; no dry-run or legacy input.
Propose no replacements: retirement ends a case, not a fourth case (founder approval).
Choose review option (b): measure behavior under a 30-minute run cutoff per worker;
collect at start+30m, watchdog-delete at +45m, provider TTL +60m. This is NOT a real-case-duration estimate; ordinary workers default to 8h (Murphy 5/launch.sh).
Each case gets one initial lifecycle, <=1 checkpoint resume AND <=1 diagnosis resume:
<=9 creations total. No extra worker on uncertainty. Extensions must fit these slots.
Propose a 12h absolute window: 9×1h TTL plus 3h setup/collection/admission margin;
each admission still requires a full TTL before the deadline. Slot/time exhaustion
while paused is slot-exhausted/incomplete: retain its checkpoint, delete and inventory its VM. Cutoff/pause never triggers diagnosis; incomplete is the likely result.
S=config/small seam, M=bounded increment, L=integrated lifecycle work. Timeline: unknown until lane-2 merge and practice evidence; separate reviewed increments.
| Gap / owner | Size | Required change/evidence before activation |
|---|---|---|
| Pilot admission / B | M | HOLDER_ENABLED=False in batch_holder.py. Add authenticated pilot opt-in beside practice.active in batch_holder.active, consumed by existing key_holder/batch.bind. Keep global/default and old IDs off; practice.py remains one-case plumbing only. |
| Diagnosis scheduling / lane 1 | L | DIAGNOSIS_ENABLED=False; batch_service.plan has no production caller and ordered_queue no consumer. Wire collected authenticated generations to plan and resume requests to holder.reserve/dispatch, with ACK/retirement/money/replay checks; scope diagnosis to pilot pins, not a global permissive toggle. |
| Item-7 completion / lane 2 | prerequisite, not pilot sizing | Merge/qualify writer/stress/gate/comparison and diagnosis outcome routes through that holder path; factory-bug holds await separately reviewed fixes. Pilot cannot invent missing adapters. |
| First AND later lifecycle settlement / B | L | boat-spend refuses any other reserved/finished/reconciled_expired row, including practice's. Add reviewed attributed settlement to its existing ledger; retain cumulative charges/unknown holds. No reset, fresh home or new ledger to evade refusal. |
| Cleanup/deployment / B | M | Generalize practice_cleanup's hard-coded batch/timing binding on the same path. Authenticate PID/policy/operation/launch readiness before each dispatch; persist per-case checkpoint/diagnosis and total creation limits plus absolute deadline. |
| Manifest/routes / B config; route owners/headroom code | S config + M headroom | Three ordinary jobs, fresh IDs/S=0, $20 each/$60 batch. Reuse batch.build/verify and qualify-batch-inputs with pilot pins, not practice's exact manifest. Pin all five roles AND diagnosis to enforced maxima; reserve diagnosis headroom before initial work using those maxima. |
| Escaped-session containment / E | prerequisite O7 | Qualify selected routes against new-isolation-settlement-1 before live pilot; subscription billing does not waive containment. |
B builds settlement first, then admission/cleanup, then S config. Review/test each increment with locked suite and fresh review. Supersede full item-8
matrix/manual activation; keep journals/evidence. No parallel launcher, no row closures.
Murphy 9 remains open; new-batch-service-4 matters for later held-case recovery.
new-stream-d-current-comparison-1 applies only after extension then factory-bug resume;
that is unlikely here and must not be exercised unless lane 2 qualifies it.
## Money proposal — not existing real-case authority
Propose a founder exploration ceiling of $20/case INCLUDING diagnosis/extensions/
retries/unknown holds: 3×$20=$60 list-equivalent, about 40% of historical real cost.
docs/designs/stream-d-cost-evidence.json records $51.28–$53.64 cases against $70 limits;
Murphy 9 gives the $50 default. The old $20 dry-run manifest is NOT real-case authority.
stream-d.md:626 records a $15.0531879 writer alone: after diagnosis headroom, an
extension is probably unfundable. The only counted diagnosis path needs budget/round exhaustion within the first two lifecycles; that is unproven.
Propose infrastructure ceiling min($5, measured Boat credit left after practice),
shared across ALL lifecycles; each draws only remaining authority. No top-ups.
Thus $65 is the maximum proposal, not a quote or guaranteed usable balance.
Founder must extend practice's prepaid/no-auto-top-up/TTL acceptance to this pilot.
OpenRouter retains its existing min($11.63, observed credit) ceiling minus ledger
charges/holds, with the existing fresh-credit/overlap check; never reset/refill.
Subscriptions count toward $20/$60. Report actual remaining cash beside proposed caps.
## Founder steps, stops and pass
1. Founder approves exploration/30m cutoff, $60 models + measured infra<=5, three
   cases/no replacements, nine slots/12h and existing labels/distinctness waiver;
   refresh and dual-recipient rewrap locally; founder private key stays on Mac.
2. After prerequisite PASS results, pin merged release/UTC deadline; verify exact CLI,
   credential lifetime, router/R2/inputs/cleanup, live Boat credit and auto-top-up OFF.
   Refuse unless credit and cumulative authority cover a conservative full-TTL lifecycle;
   recheck before each creation. Unknown charges, depleted cash or unbounded routes abort.
3. Admit through key-holder only. Budget/round exhaustion→diagnosis is the only counted diagnosis path;
   accepted routes: retire, factory-bug held, or extension admitted/refused by money.
4. Stop admissions on batch cap/deadline, duplicate creation, unknown settlement/ownership,
   invalid diagnosis, unsafe cancellation or publication failure; keep cleanup until verified deletion.
5. Pass: three attributable terminal outcomes, >=1 genuine diagnosis with a recorded route,
   reconciled costs, caps met and completed deletion receipts/full absence inventory for all VMs.
   Case-budget→diagnosis→retire/hold counts; all-sealed/no-diagnosis, unfinished extensions,
   batch-level cap/deadline/refusal stops or missing proof are incomplete. Founder decides any next run.
