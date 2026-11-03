# Goldfish review: Item 8 offline preparation, design round 2 (final)

**Verdict: PASS. I found no blockers, no majors and 4 nits.**

The amendment is now an honest, specified preparation document. It does not claim anything is executable. Every live path is gated behind O2 and O9, which are named, sized and owned no-launch gates. I am not asking for the enumerated gaps to be implemented, which would be outside this task.

**Scope:** I worked read-only in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c` at HEAD 2caa09f, reviewing the diff `c3ee6d9..2caa09f`. Mode: REVIEW, using the `zoom_out`, `design_critic` and `implementation_readiness` personas and the `heilmeier-standard.md` and `implementation-readiness-standard.md` standards. No tests, edits, model or provider calls.

## R1 dispositions, checked independently

**B1, timing (O9):**
- Lines 296–319 mark the old 70-minute / 8-hour / two-hour envelope KNOWN INSUFFICIENT.
- Scenario 4 is the real, unchanged 30-minute per-attempt `time_limit`, with and without a submitted guard. Call, zero-token, money or kill caps are explicitly excluded.
- The minimum timing arithmetic is stated: at least 60 minutes plus G16/G17, and 180 uncached G10 minutes. It matches `gate_state.py`'s pins (`pilot_tries=3`, `calibrator_minutes=30`) and the saved 148.1/144.4-minute gate run.
- O9 requires a matrix of all 20 per-slot root and child deadlines, lifetimes and billing bounds, a fresh timing review and founder sign-off.
- Line 25 claims no valid deadline. The same text is mirrored at `stream-d.md:3637–3650`.

**M1, the Q1 trigger and the 6a boundary:**
- Q1 is observation-only. Its predicate is bound to the job, the generation, X2, N, and `N.exhaustion_id != X2`.
- Q2 pauses after entry selection and before the `pending_call` reservation. Its durable record and its before/after snapshots of reservations and comparison directories are specified.
- I checked the 6a stop against the code, and it is real:
  - `run.py` `main` catches `BudgetError`, then `finalize_accounting`, then `diagnosis.record_exhaustion` (`run.py:3149–3154`). Its comment says "Model diagnosis belongs to a later same-owner resume, after B collection".
  - `_trigger('extension_incomplete')` requires a completed last row (`diagnosis.py:55–56`).
  - Then `seal(checkpoint=True)` and DONE.
  - So main dispatches once per worker. That supports the separate fault and diagnosis workers in 5a/5b and 6d/6e.
- The pending Y after 6d's comparison exhaustion is also consistent with the code:
  - `subsequent_entry` runs before any N+1 history row exists (`extension_package.py:600`).
  - Exhaustion becomes `infrastructure_exhausted` with a completed last row, so `record_exhaustion` writes a new pending ID.
- G4 change behaviour checks out: `comparison_pair` finds no pair for the new version vector, so 6d really does compare (`extension_compare.py:286–289`).

**M2, ordering:**
- `batch_service.ordered_queue` ranks settlement, then replacement, then resume (`batch_service.py:299–302`).
- The order 5c→5d, 7b→7a, 6b→6a follows that.
- The scenario-5 conflict on beta-fault is handled honestly. O3 must add a reviewed release-readiness guard; without it, the four-slot packing is declared infeasible before launch (lines 209–217, O3). No operator bypass is allowed.

**M3, money fit (O2):**
- Before launch, the summed honest maxima for the whole root path through 6f must be ≤ $12.50. The child gets its own separate $12.50 worksheet.
- Unknown Codex maxima or unproven reuse means FAIL.
- The global OpenRouter paid-credit headroom must also fit.
- Scenario 6 is stated as currently infeasible, with no late-stranding authorization and no cap increase (lines 321–339).

**M4:** run 4 (2a) now lists both stress timeouts.

**N1–N5:**
- G4-only source and hashed plumbing outside the science inputs, with version vectors computed offline (lines 272–280).
- Q2 inventory proof.
- Live active-package restore is explicitly unexercised (lines 385–390).
- A0 explicitly supersedes the stale `item8-draft.json` hash and keeps that file as non-launchable.
- Impact, 13–22 owner-days and an 8–10 working-day critical path are added.

**Money arithmetic:**
- $90 model + $8 lifecycle (20 slots × $0.40) + $2 shared = $100.
- Alpha $40, all beta $50 shared.
- The table gives 20 slots: 5a–5d is 4 and 6a–6f is 6.
- S+E cumulative authority, Rj shared per root, a child starting at S=0, and unknown holds counting against admission are all retained.
- The text never promises that $100 completes the path.

**Authority:** `batch-practice-manifest.md:109–117` matches.

**Murphy register:** `new-stream-d-current-comparison-1` is still open, and nothing closes.

**Size estimate:** the S/M/L sizes add up to about 13–22 days if M is about 1 day, so the estimate is consistent.

## Nits

- **N1. Stale live idempotence wording** (`stream-d.md:3626`, scenario 6 row). It still lists "replay idempotence" among the live proofs, but the amendment moves it offline. The supersession clause covers this; adding "(offline, retained artifacts)" there would make it explicit.
- **N2. Wording conflicts with the scenario-5 guard** (amendment lines 167–168). "All requested replacement-before-diagnosis priorities remain ordinary B behavior" reads as contradicting the guarded scenario-5 sequence, where diagnosis 5b runs before child 5c launches. The intent is that the child is admitted and queued before diagnosis, but launched later. Add "except the O3 release-readiness guard for scenario 5, which affects launch eligibility, not admission".
- **N3. Critical path assumes B can work in parallel** (lines 417–421). B owns or co-owns O2, O3, O4, O6, O8 and O9. B's serial share alone (O3 L, O4 M–L, plus shares of O6 and O8) can reach about 6–9 days before O9. The estimate says "rough", so this is fine; you could state the B-serialization assumption.
- **N4. Trailing whitespace** in `docs/reviews/stream-d-item8-offline-preparation-design-1.md` at lines 31, 54 and 62. `git diff --check` exits 2 on these. Strip them when you save this review.

## Persona notes

- **Zoom out:** no new ledger, scheduler, launch path, hook schema or runtime mechanism is added. The repacking reuses the existing `main` dispatch, finalize/seal, `ordered_queue` and the `runtime_revision` journal. The only new controls required are O3's guard and O6's Q hooks, and both are framed as reviewed future work.
- **Design critic:** the main risks (timing, full-path affordability, Codex maxima, candidate availability, billing and deletion bounds) are now stated as blocking infeasibilities, not optimism.
- **Implementation readiness:** within preparation scope, every remaining decision has an owner, a size and an exact exit condition. The document says plainly that it is not an executable manifest.

## Remaining blocker for the parent

None within this scope.

The live program stays not admissible until O1–O9 exit, scenario 6 in particular. The document already says so, and that is the correct state.

## Elephant disposition

Final PASS accepted; no blocker or major remains within offline preparation scope. Address N1 by marking scenario-6 idempotence explicitly offline/retained-artifact in the original table; N2 by distinguishing replacement admission/queue priority from the required scenario-5 launch-readiness guard; N3 by making the B-serialization assumption explicit. N4 removes trailing whitespace only in review 1, preserving its prose. No runtime, policy, science, hook, deadline or budget implementation changed after review. No full suite, provider query, credential access, model experiment or live worker action was taken. No Murphy row closes. O2 and O9 remain mandatory no-launch gates: the $100 cap is unchanged, but the old timing envelope and scenario-6 affordability are not certified. Parent handback is a passing preparation design, not launch readiness.
