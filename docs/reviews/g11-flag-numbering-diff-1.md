# Goldfish review: G11 flag numbering (diff 1)

- Branch: fix/g11-flag-numbering, commit c080cde7 on main 4b4c5aca; fixes in the next commit.
- Mode: REVIEW (zoom_out, implementation_readiness). No design doc (fix under 20 lines, obvious cause); reviewed against the commit message.
- Reviewer: fresh goldfish (Claude, same family as the writer; no other family was available to this session), read-only.
- Verdict: **code passes; one blocking finding about rollout to 8acb5c, accepted and handed to the operator (it needs a VM step this branch may not take). Nits fixed except the real-verdict fixture.**

## Findings and disposition

1. **BLOCKING (rollout, not the diff):** `independent_review.review` re-validates a saved verdict only when its journal status is `completed`. 8acb5c's two verdicts were journalled `inconclusive`, and the rebuilt G11 evidence (same seed) most likely hashes the same, so the same `independent-g11-<key>` directory is reused, both families are skipped, and G11 raises `InfrastructureExhausted` again without calling a reviewer.
   **Accepted, not fixed in code.** Changing `independent_review.py` would change the G2, G11, G16 and G17 identities (it is a listed file dependency; G16 is gate-cached). Operator step before resuming 8acb5c: run the new `validate` against that directory's real `verdict-*.json` and the case's `flags`, and if they pass, set both families' status in its `reviews.json` from `inconclusive` to `completed`. On resume `validate` re-checks the saved files, so no new review is bought and a bad verdict still fails.
2. **NIT:** accept one numbering for the whole verdict instead of choosing per row (`[[0,1,2],[3,4,5],[0,1,2]]` passed).
   **Fixed:** `validate` now compares the whole `findings_reviewed` list against all-per-fix or all-running numbering.
3. **NIT:** add the real 8acb5c verdict files to the fixture; add uneven counts with a zero-flag pass.
   **Zero-flag case fixed** (counts `[3,0,2]`, running `[[0,1,2],[],[3,4]]`), and a mixed-numbering rejection added. **Real verdicts not added:** they are case material on the control VM, which this change may not touch; the operator check in finding 1 runs `validate` on them before resuming.

## Writer's own check after the fixes

The first fix used `i` in a comprehension; `gate_state.source_inputs` resolved it to a top-level `i` and pulled `RECERTIFY_RERUN` into G11's identity. Renamed to `index`. Parent vs head, `source_inputs` for every gate root (G1-G17 with EXTRA_ROOTS), the stress and calibration judge closures and `g14_binding`: only G11's `g11` entry changes.
