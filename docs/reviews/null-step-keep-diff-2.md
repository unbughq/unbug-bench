# Goldfish review: null-change step keys `keep` only (diff 2)

- Worktree ub-keeprule, branch feat/null-step-keep on origin/main 5fa8c8ec, uncommitted diff to
  factory/prompts/builder.md, factory/prompts/reviewer-keys.md, tests/bench/test_reviewer_limits.py.
  Reviewer: fresh goldfish, round 2, read-only.
- Ruling (founder 2026-11-20): at the PROTOCOL.md S0 null-change step only, `keep` is the only correct
  response; G8 must not fail a keep-only key there nor debate harmlessness; builders key it that way. No effect
  on other steps or unannounced scoring.

**Verdict: PASS**

## Round 1 blocking: fixed

- reviewer-keys.md:33-37 now scopes the rule as "the PROTOCOL.md S0 null-change step (an announced step whose
  change touches nothing the bench runs, such as a README edit)". That matches PROTOCOL.md:181 ("Nothing (null
  change: a README edit)") and builder.md:300 ("PROTOCOL.md S0, an announced step"). The old "nothing the guard
  depends on changed" gloss is gone, so S1/S3/S5/S8-style steps where the guard happens to survive are not
  swept in.
- It adds an explicit fence: "This applies to no other step: steps that change code, data or versions keep their
  usual rules." "An announced step" keeps quiet windows out, and builder.md:294-298 still states unannounced
  accept-all.
- Round 1 nit 2 also addressed: "a contestant's change at that step" no longer reads as the step's own README edit.

## New problems

None blocking. Checked: S0 runs twice (PROTOCOL.md:197, start and middle); both are S0 and announced, so the
rule covers both and nothing else. No code path keys on S0 (only factory/public_fixture_smoke.py reads the dev
S0 files), so scoring is unchanged; this is a prompt and key convention only. Test passes on the branch; its new
strings do not exist on origin/main.

## Nits (non-blocking, carried from round 1)

1. reviewer-keys.md:33 sits under "Bench scoring rules", whose preamble says "Do not fail a case because the
   scorer applies them". Keep-only is a key convention, not a scorer rule. Fine as is; a "Key convention:" lead-in
   would be cleaner.
2. tests/bench/test_reviewer_limits.py:33 pins "touches nothing the bench runs, ..." but not "an announced step"
   or "applies to no other step", the parts that fixed round 1. Extending the asserted string to start at
   "null-change step (an announced step" would stop the scope from silently widening again.
