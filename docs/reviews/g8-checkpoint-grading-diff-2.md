# Goldfish review: G8 checkpoint grading rule (diff 2)

- Branch feat/g8-checkpoint-grading at ba0ba7c2 (after diff-1 fixes). Reviewer: fresh goldfish, read-only,
  zoom_out + implementation_readiness, Mode: REVIEW. Verdict: **FAIL** (one blocker), everything else passes.
- Checked: ruling copied word for word; builder trigger and owner-only exception match the reviewer text; no
  conflict with unstated_rules, "Put intent_checks...", or the unannounced-window rule; diff-1 findings 2 and 3
  fixed; test exits 0 and its new assertions fail on origin/main; only G8/G9 identity changes, calibration.py,
  cases/ and bin/ untouched, sealed cases unaffected.

Findings and what was fixed:
1. BLOCKING reviewer-keys.md:20-21: "only a failed `intent_checks` check makes a checkpoint unsafe" is false
   (claims.py:208: unexpected path violations and `false_assurance` also do) and clashes with the prompt's
   "Only `false_assurance` makes a checkpoint unsafe" claim-label line -> "because a judge check outside
   `intent_checks` never makes a checkpoint unsafe (`intent_failures` in `bin/claims.py`)". Fixed; the test also
   asserts `def intent_failures` exists in bin/claims.py.
2. NIT reviewer-keys.md: defect sentence dropped "for a promise clause" -> restored. Fixed.
3. NIT builder.md: restore "itself"; "that checkpoint's" had no referent -> "in the intent_checks of every
   checkpoint from the first one where the contestant can read the clause". Fixed.
4. NIT builder.md: an intent check the checkpoint's judge does not report fails closed -> appended "and that
   checkpoint's judge must report it". Fixed.

Rejected: none.
