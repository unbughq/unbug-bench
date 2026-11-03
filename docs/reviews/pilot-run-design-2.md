**Verdict: passes for founder review, no blockers. 1 major and 2 nits are still open.** None of them requires a round 3. The major is a wording fix: the design calls budget exhaustion the expected path, but under the 30-minute cutoff it isn't.

I reviewed worktree `t3-ded79ec5`, branch `t3/batch-service-control-vm`, at HEAD `25d200f`, against the round-1 review in `docs/reviews/pilot-run-design-1.md`. I worked read-only: no edits, tests, live calls, secrets or delegates, and I didn't touch practice state. Personas: zoom_out, design_critic, implementation_readiness. Standards: Heilmeier, plus implementation readiness applied only at gap-sizing depth, as the brief asks.

## Round-1 findings
- **B1, resolved.** The revision takes option (b): line 10 says this is not a real-case duration estimate, and the 8h default is cited correctly (`factory/launch.sh:4,26`). Each case gets its own slots: 1 initial, ≤1 checkpoint resume, ≤1 diagnosis resume, so ≤9 lifecycles. The 12h window is 9×1h plus 3h margin, which meets "lifecycles × TTL plus margin". Line 14 keeps the rule that every admission needs a full TTL before the deadline.
- **M1, resolved.** $20 is labelled an exploration ceiling, about 40% of real cost. The design cites `stream-d-cost-evidence.json`, which records $51.28 and $52.79 against $70 limits, plus Murphy 9's $50 default. It says the dry-run manifest is not authority and that an extension is probably unfundable.
- **M2, resolved.** Lines 53–54 list the routes that count. Lines 57–59 separate a case running out of budget (counts) from batch cap, deadline or refusal stops (incomplete).
- **M3, resolved.** Infrastructure is min($5, measured Boat credit), shared across lifecycles with no top-ups. $65 is called a maximum, not a quote. Step 2 rechecks credit before each creation. OpenRouter keeps min($11.63, credit) minus ledger charges.
- **Nits, resolved.** N1 is fixed on line 19. N2 is on line 21. N3: the risk line is line 4 and the timeline line is line 16. N4 is on lines 29–30. N5 is on line 22.
- **Ownership** matches what the parent assigned: lane 1 owns diagnosis scheduling, lane 2 owns the item-7 prerequisite, E owns O7, and B owns settlement, admission, cleanup and config.

## Open findings

**Major, M4: the "expected path" contradicts the cutoff (lines 37 and 53, against lines 4 and 15).**
- **What the code does:** `factory/diagnosis.py:83-97` (`exhaustion`) does not trigger diagnosis on `paused`, `ttl_retired` or `provider_wait` stops. `_trigger` (`:51-62`) fires only on stops like `budget_exhausted`, rounds exhausted or `infrastructure_exhausted`. A 30-minute cutoff is never a diagnosis trigger in itself.
- **Why that matters:** a case only reaches diagnosis if it uses up its $20 (less reserved diagnosis headroom) or its rounds within about 1h of worker time (initial run plus checkpoint resume). Real cases took 5–6h, with writing alone about 2h (`launch.sh:4`). The likelier outcome is that all three cases are cut off with no diagnosis, the diagnosis-resume slots go unused, and the pilot ends incomplete.
- **The contradiction:** line 15 says this "may" happen. Line 37 says "Expect budget exhaustion→diagnosis→retire/hold", and step 3 calls it "expected". The founder would approve the money without a clear view of the payoff.
- **Fix (wording only):**
  - Say that a cutoff or pause does not trigger diagnosis.
  - Say that the pilot passes only if a case runs out of budget or rounds within its first two lifecycles, and that this is unproven, so incomplete is the likely result.
  - Change "expected" on lines 37 and 53 to "the only counted path".

**Nit, N6: the build order for B is not written down (lines 17–25).** The parent set the order: first- and later-lifecycle settlement, then admission and cleanup, then S config. The table lists admission first. Add one line giving the order.

**Nit, N7: the state of a case whose slots run out while paused is not named (lines 14–15 and 57).** Pass needs "three attributable terminal outcomes", but the design doesn't say whether a paused case with no slots left counts as terminal, or what happens to its checkpoint. Name that state, and say it is incomplete and must still be deleted and inventoried.

## Checked and fine
- **Sizing:** admission M, diagnosis scheduling L, settlement L, cleanup M, config S plus headroom M. This matches the code: `HOLDER_ENABLED=False`, `DIAGNOSIS_ENABLED=False` (also gated at `diagnosis_dispatch.py:242,255,345`), practice is hard-bound to `practice.TIMING` (`practice.py:9`) and `practice_cleanup.py:59`, and `boat-spend` refuses any unsettled liability.
- **12h timing:** with concurrency one, all non-lifecycle time across the run has to fit in the 3h margin. That holds, and line 14 already enforces it.
- **Not flagged:** I didn't ask for full implementation designs per gap (out of scope). The no-replacement rule and the distinctness waiver are correctly left for the founder to approve.

Since no blocker remains, the writer doesn't need the 3-line stop. Fixing M4, N6 and N7 means editing about 4 lines.

---
Writer disposition: M4, N6 and N7 accepted and fixed. Cutoff/pause is not a diagnosis trigger; incomplete is likely. The first two lifecycles must exhaust budget/rounds for the counted diagnosis path. B's build order is explicit. A paused case without slots is slot-exhausted/incomplete, retains its checkpoint, and still requires VM deletion/inventory. No findings rejected; no round 3; no practice-state change.
