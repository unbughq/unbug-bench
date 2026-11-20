# Goldfish review: null-change step keys `keep` only (diff 1)

- Worktree ub-keeprule, branch feat/null-step-keep on origin/main 5fa8c8ec, uncommitted diff to
  factory/prompts/builder.md, factory/prompts/reviewer-keys.md, tests/bench/test_reviewer_limits.py.
  Reviewer: fresh goldfish, read-only.
- Ruling under review (founder 2026-11-20): at the null-change step (PROTOCOL.md S0 row), `keep` is the only
  correct response; G8 must not fail a key for accepting only `keep` there, nor debate whether some change is
  harmless; builders key it that way.

**Verdict: FAIL**

## What checks out

- builder.md:300 says exactly the ruling and scopes it right: "PROTOCOL.md S0, an announced step". It sits right
  after the unannounced rule (builder.md:294-298) and does not contradict it.
- Consistent with PROTOCOL.md:181 (S0: "Keep. No escalation."; any alert or escalation is a false alarm) and with
  the scorer: bin/claims.py:216-218 gives `response_correct` only for a response in `correct_responses`, so
  `["keep"]` makes `escalate`/`repair`/`withdraw` score wrong at S0, which is what the ruling wants. The S0 key's
  `escalation: inappropriate` still charges escalation as a false alarm (claims.py:220-221).
- Unannounced scoring is unaffected mechanically: factory/case_contract.py:92 and :120 still force G1 to require
  all four responses at unannounced steps.
- No existing key becomes a defect. Every S0 key in the repo is `["keep"]`: scenarios/dev/S0-null/key.json,
  cases/medusa-oversell-v2/scenarios/S0/key.json, cases/medusa-oversell-v2/answer-key.json `S0`, and the same three
  files inside all three tests/factory/fixtures/*/public-source.tar.gz. harbor/*/steps/s0-null carry no key.
- Test passes on the branch; both new assertions fail on origin/main (text is new).

## Blocking

1. factory/prompts/reviewer-keys.md:33 redefines "null-change step" more broadly than the ruling. The gloss
   "(PROTOCOL.md S0: nothing the guard depends on changed)" is not what PROTOCOL.md:181 says (S0 = nothing changes,
   a README edit). Read literally, it covers any step where the reference guard happens not to be affected, e.g. an
   S1 minor upgrade or S5 bundle where the guard is generic. There, PROTOCOL.md:182/186 say keep *if still valid*,
   and a harmless repair can be an acceptable response the key should list. With this wording a G8 reviewer must
   accept a keep-only key at such a step and is told not to argue harmlessness, which is exactly the debate the
   ruling allows outside S0. It also drops builder.md's "an announced step" qualifier, and reviewer-keys.md does not
   state the unannounced accept-all rule anywhere, so nothing in the G8 prompt stops a reviewer from reading a quiet
   window as "nothing changed". Fix: use the same scope as builder.md, e.g. "at the PROTOCOL.md S0 null-change step
   (an announced step whose change touches nothing the bench runs, such as a README edit)".

## Nits

1. reviewer-keys.md:33-36 sits under "Bench scoring rules", whose preamble (reviewer-keys.md:29-31) says "Do not
   fail a case because the scorer applies them". The scorer does not apply keep-only; this is a key convention.
   It reads fine, but a lead-in like "Key convention, not a scorer rule:" would be clearer.
2. reviewer-keys.md:36 "whether a particular change at that step is harmless": "change" can be read as the step's
   own change (the README edit). Say "a particular repair or other response".
3. tests/bench/test_reviewer_limits.py:32-33 only checks that the text is there. Consider (a) asserting the scope
   text from blocking 1 in reviewer-keys.md (for example "an announced step"), so the narrowing cannot silently go
   away; (b) one data check that every S0 key in scenarios/dev and cases/*/answer-key.json is exactly `["keep"]`.
   That ties the rule to real keys.
4. tests/bench/test_reviewer_limits.py: the new assertions have no `# Founder 2026-11-20 (...)` comment like the
   neighbouring rulings, and the final print message (line 34) does not mention the new rule.
