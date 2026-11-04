# Goldfish diff review 6: `fbca505...857bc26` (reselection follow-up after the diff-5 fixes)

Reviewer: fresh goldfish with no history: separate Claude Code cloud session
`session_01GLSX4iAQf7VxHjYPdrQ7BW` (model claude-opus-5-5, the same model family as the
writer, because no other family was available to this job). Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW.
It was asked to verify the diff-5 blocker independently and to check five properties
explicitly: ciphertext preservation, rejection authentication, reservation fencing,
duplicate-screening visibility, and Murphy closure.
Its reply is reproduced verbatim below. The elephant's dispositions follow it.

FAIL

# Goldfish review: reselection between history snapshot and handoff (`new-registry-pending-promotion-1`), diff-5 follow-up at 857bc26

Mode: REVIEW. Personas: zoom_out and implementation_readiness. Standard: `implementation-readiness-standard.md`.

HEAD is confirmed as `857bc26a201d66e72bc515c05da0544cfb94267d`. The base is `origin/factory-simplify` = `fbca505`, which is also the merge-base.

Scope:
- The design addendum and its "Review follow-ups" paragraphs (diff-3 and diff-5).
- `git diff origin/factory-simplify...HEAD -- factory tests docs/designs`.
- The files that diff references.

## Findings

### Blocking

**G1: A stale ciphertext can still be bound to the new digest when the history card has no `statement_cipher_sha256`. On base, the same input was refused.**
- **Where:** `factory/statement_round.py:100-108` and `factory/registry.py:120`.
- **Problem:** The two B1 fixes leave a gap.
  - The byte-identity check in `replace_rejected` (`previous["cipher_sha256"] == cipher`) only catches the exact rejected bytes. It misses any other seal of the rejected statement.
  - The card check in `prepare` runs only when the card has `statement_cipher_sha256`.
- **Why other seals are normal:** age seals with fresh randomness. `run_artifacts.py:76-88` pops the field and re-seals the statement on every save. So a later collection of the same rejected statement normally has different bytes from the ones the registry stored.
- **Who produces cards without the field:** Cards that carry `statement_sha256` but no `statement_cipher_sha256` are a recognised legacy shape. The comment at `statement_round.py:69` says "Older cards have only the worker's plaintext digest", and `prepare_restore` still accepts them.
- **Effect:** For such a card naming d2 and rejecting d1, with collected bytes that are another seal of d1:
  1. X's history import releases Y's entry and stores d2 with the stale bytes.
  2. Y's own handoff then promotes under the row-7 rule. It keeps those stale bytes and exports them as Y's `cipher_sha256`.
  3. Every later reservation screens against the rejected statement instead of c2.

  That is the B1 harm. It breaks check 1 ("a stale/rejected ciphertext can never be bound to a new digest") and the register row's requirement ("never silently replace different content").
- **The documented limit is wrong:** The diff-5 disposition says the unchecked case is "a card that has no `statement_cipher_sha256`, for a case the registry has never seen". The probe shows the gap also covers a case the registry has already seen.
- **Probe:** Scratchpad copy of `sealed/statement-registry`. Real ciphertext, using a different real `.age` file as the second seal of d1. The card is `{statement_sha256: d2, rejected_candidates: [{d1}]}`.
  - HEAD: d2 is bound to the stale bytes. Y's handoff export has `cipher_sha256 == sha(stale)` and `complete=True`.
  - Base `fbca505`: the same input raises "case already reserved with different content".
- **Reachability:** The current writer always sets `statement_sha256` and `statement_cipher_sha256` together (`run_artifacts.py:83-87`). So this needs a legacy-shape or carried-over card. That is narrow, but it turns a loud refusal into a silent wrong binding of the bytes that drive duplicate screening, and the fix is small.
- **Fix:** In `prepare`'s history branch, authenticate a release only when the card's `statement_cipher_sha256` is present and equals `sha256(history ciphertext)`. Otherwise pass `rejected=[]`.
  - Without authentication, `replace_rejected` falls through exactly as base did: it returns the stored entry on a matching digest and raises "different content" otherwise.
  - Keep the byte-identity check in `replace_rejected` as a second guard.
  - Add `statement_cipher_sha256` to the tests' hand-authored reselection cards.
  - Add a test with a different real seal of d1 and a card that has no cipher digest. It should refuse.

### Major (non-blocking)

**G2: The history-card cipher check now fails other waves whose import needs no release, where base succeeded.**
- **Where:** `factory/statement_round.py:100-102`.
- **Problem:** A mismatch between a history card's `statement_cipher_sha256` and its collected `.age` raises `ValueError`. That aborts X's whole wave, even when the card's digest already matches the registry entry and nothing would be released.
- **When it happens:** One example is a crash between `staged.replace(...statement.age)` and the card write in `run_artifacts.py:87-88`. That leaves a new seal next to an old card.
- **Base behaviour:** Base returned the stored entry and carried on.
- **Probe:** Y's d1 is reserved. X's history has bytes that are another seal, and a card with `statement_cipher_sha256 = sha(c1)`.
  - HEAD: "historical statement ciphertext scorecard digest mismatch".
  - Base: X's wave succeeds.
- **Why it matters:** This is the cross-wave liveness failure that the N1 disposition set out to avoid for malformed lists.
- **Fix:** Use the fix from G1. A mismatch means "not authenticated" (`rejected=[]`), not a hard raise. B1's exact input then still refuses with "different content", as on base.

**G3 (carried from diff-5 M2, documented): the gap between the release and the reserve.**
- **Where:** `registry.py:123` and `:128`.
- **Problem:** The release and the reserve take the lock separately.
  - A concurrent reservation for another case Z that lands in the gap omits Y.
  - A concurrent wave W holding a stale d1 history card can re-import d1 into the released slot. X's `reserve(d2)` then raises "different content", with no retry.
- **Why it is non-blocking:**
  - The pairwise argument in the design holds. Y's later promotion or reserve recomputes its predecessors from all live entries, so it includes Z.
  - A resurrected d1 only over-screens, which is the safe direction. It is released again by the next authenticated import or by Y's handoff.
- **Fix:** None required. Mention the resurrection sub-case in the "Known gap" paragraph.

### Nits

- **N-a:** The candidate path (`statement_round.py:113`) still crashes on a malformed own-card `rejected_candidates`, while the history path tolerates one. This is unchanged from base and concerns the case's own card, so it is acceptable. A one-line note in the design would explain the asymmetry.
- **N-b (zoom_out):** The unlocked decision plus the `expect` fence plus retry-once is three mechanisms where a single locked compare-and-release would do. The disposition's reason (not restructuring the merged `reserve`) is acceptable. The fence makes the result correct.
- **N-c:** In `test_reselected_pending_candidate_survives_other_wave_and_own_handoff` and the related tests, the hand-authored cards carry no `statement_cipher_sha256`. So the happy path is proven only on the card shape G1 identifies as unsafe. With the G1 fix these cards need the field.

## Explicit checks

**1. Ciphertext preservation: FAIL (G1).**

What holds:
- An entry not authenticated as rejected is never released.
- Released objects stay on disk.
- A same-digest call returns the stored entry.
- Promotion keeps the stored ciphertext. This is now tested with a different real seal in `test_own_handoff_keeps_reselected_ciphertext_imported_as_history`.
- X's export carries Y's stored `cipher_sha256`.
- B1's exact input (the identical stale bytes) is refused in both starting states, through X's wave and through Y's own handoff.
- A card with a cipher digest that does not match its bytes is refused.

What fails:
- With a card lacking `statement_cipher_sha256`, a different seal of the rejected statement is bound to d2, then promoted and exported (probe above). On base this was refused.

**2. Rejection authentication: PASS for the digest. The card-to-ciphertext pairing is G1.**
- A release requires `old is not None and old in rejected`, where `rejected` comes from that case's own card (`history/<case>.scorecard.json` or `sealed/<case>.scorecard.json`).
- A `None` digest never authenticates. Probe: a legacy digestless historical entry with `rejected=[None]` raises "different content".
- A malformed list authenticates nothing: null, a non-list, non-dict rows, or more than 3 rows. Four subtests cover these.
- Unlisted or mismatched digests raise in both starting states.
- Complete `completed`/`known_public` entries are refused through the `historical=True` path (probe).

**3. Reservation fencing: PASS.**
- `transition`'s new condition parses as `token mismatch or released or (expect is not None and expect != current)`. Existing callers without `expect` (the CLI at `registry.py:238`) behave as before.
- The only `expect` caller passes the status, statement digest and cipher digest from its unlocked read, and these are compared under `LOCK_EX`.
- A same-token change (building→completed) raises "stale reservation". The single retry re-reads and refuses. This is tested, with `calls == ["released"]` and the entry left as `completed`/d1.
- The retry-once is bounded (`if attempt: raise`; a mocked call count of 2). After a retry the code re-decides from a fresh read: it returns the stored entry on the same digest, refuses an unlisted digest, or reserves a released slot. It cannot loop or accept different content.
- `complete` cannot change under the same token, because every `reserve` rewrite mints a new token, so the fence covers it.

**4. Duplicate-screening visibility: PASS with caveat (G3); harmed by G1 when it triggers.**
- Only a candidate that its own card names as rejected leaves screening.
- Pending history imports remain non-released, so they stay in `earlier`.
- Snapshots that already include c1 remain fixed.
- The release→reserve gap is real. The pairwise argument holds, because Y's own later reservation recomputes its predecessors.
- G1, when it triggers, leaves the rejected content visible in place of c2.

**5. Murphy `new-registry-pending-promotion-1`: NO, it cannot be closed.**
- ENGINEERING §2 and the §4 "Real artifacts" rule require a test on real saved cards.
- The registry and ciphertext in the tests are real copies of `sealed/`. Every scorecard digest, cipher digest and rejected list, however, is hand-authored.
- None of the 53 `sealed/*.scorecard.json` carries `statement_sha256`, `statement_cipher_sha256` or `rejected_candidates`, so no real artifact reaches the new branch.
- G1 also shows the row's requirement is not yet met.
- Leaving the row open is correct.

**6. Other (implementation_readiness / zoom_out): FAIL, because of G1.**
- Regressions against base:
  - G1: a loud refusal becomes a silent wrong binding.
  - G2: a successful history import becomes a wave-wide failure.
  - No other regressions: the row-7 tests and `test_statement_round` pass.
- Design/code mismatches:
  - The diff-5 disposition's stated limit ("for a case the registry has never seen") understates G1.
  - The design says `prepare` "checks a history card's `statement_cipher_sha256` when present, as the candidate path does". It does not mention that a mismatch now aborts unrelated waves.
- The claimed "fails on 9b950bf" holds for each fix:
  - B1: 2 subtests FAIL.
  - M1: 1 FAIL.
  - N1: 4 subtest ERRORs.

## Tests run

- `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py` at HEAD: 15 tests, OK.
- `BENCH="$PWD" python3 -B tests/factory/test_statement_round.py` at HEAD: 18 tests, OK.
- The HEAD promotion test module run against `git archive`d `factory/` in the scratchpad:
  - At `9b950bf`: 15 run, 3 failures (fence test, stale-ciphertext test ×2 subtests) and 4 errors (malformed list ×4 subtests).
  - At base `fbca505`: 15 run, 3 failures and 6 errors.
- Scratchpad probe, run on HEAD and on base, using copies of the real registry and real ciphertext:
  - P1, cipher skew on a history import that needs no release (G2): HEAD fails X's wave; base succeeds.
  - P2, a legacy-shape card plus another seal of the rejected statement (G1): HEAD binds and exports the stale bytes for d2; base refuses.
  - P3, `[None]` against a digestless entry: both refuse.
  - P4, complete `completed`/`known_public` entries through the history path: both refuse.

---

## Dispositions (elephant)

Nothing rejected. The new tests fail on 857bc26 (G1: 2 subtests, G2: 1 error, and the updated B1 test: 2 subtests) and pass on the fixed head.

- **G1, fixed as suggested.**
  - `prepare`'s history branch authenticates a release only when the card's `statement_cipher_sha256` is present and equals the sha256 of the collected bytes. Otherwise `rejected=[]`, and `replace_rejected` returns or refuses exactly as base did.
  - The byte-identity guard in `replace_rejected` is kept as a second guard.
  - Test: `test_history_release_needs_card_bound_to_collected_bytes` (legacy-shape card plus a different real seal of d1, in both starting states, refuses and keeps d1/c1).
- **G2, fixed by the same change.** A cipher mismatch now means "not authenticated" instead of a hard raise. Test: `test_history_cipher_skew_without_release_does_not_fail_other_wave`.
- **G3, design wording added.** The "Known gap" paragraph now covers the resurrection sub-case.
- **N-a: design note added.**
- **N-b: accepted.** Same reason as diff-5 M1.
- **N-c: fixed.**
  - The `wave` helper's default authored card now carries `statement_cipher_sha256` for its bytes, which is the current writer's shape.
  - The B1 test's mismatched bound card now expects the "different content" refusal instead of the removed hard raise.
- **Candidate path, not changed.** It still trusts its own card's digest. `same_worker_handoff` checks `statement_cipher_sha256` when present, and that check is unchanged from base.
- **Murphy row `new-registry-pending-promotion-1`: stays open.** No real card reaches the new branch.
