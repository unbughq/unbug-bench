# Goldfish review: G8 checkpoint grading rule (diff 1)

- Branch feat/g8-checkpoint-grading, commit 08d02cdb. Reviewer: goldfish (fresh agent, read-only), personas
  zoom_out + implementation_readiness, Mode: REVIEW, against the commit message and the founder ruling (no design:
  under 20 lines, prompt text only). Verdict: **PASS**, no blockers.
- Checked: reviewer text copies the ruling word for word, in the key cross-check section; "graded = in
  `intent_checks`" matches bin/claims.py:111-115,208-209; builder line placement (after "Put intent_checks in each
  relevant key.json") and no conflict with unstated_rules (owner-only) or the unannounced-window rule; no conflict
  with other reviewer-keys.md rules (fits the 33609fc2 own-product rule); test passes with the change and its three
  new assertions are False against origin/main's files; effects: reviewer-keys sha is in the G8/G9 identity
  (gate_state.py:235-236) so new launches rerun G8/G9 once, builder.md is in no gate identity, calibration.py
  untouched so sealed cases are unaffected.
- Note: the persona/standard files live only in the main checkout; implementation-readiness-standard.md does not exist.

Findings and what was fixed:
1. SHOULD reviewer-keys.md: "because the scorer grades no other judge check" is false for approved pending steps
   (claims.py:92 `verified_pending_safe` needs every check) -> "because only a failed `intent_checks` check makes a
   checkpoint unsafe". Fixed.
2. SHOULD reviewer-keys.md vs builder.md: the defect sentence dropped the readable-clause qualifier and owner-only
   exception (wider than the ruling), and the builder said "from the first step it applies" (a different trigger)
   -> reviewer: "that a checkpoint where its clause is already readable leaves out of `intent_checks` is a case
   defect, unless it is an owner-only rule"; builder: "from the first checkpoint where the contestant can read the
   clause". Fixed.
3. NIT: `why` lives in answer-key.json entries -> "an answer-key `why`". Fixed.

Rejected: none.
