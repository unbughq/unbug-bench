# Goldfish diff review 8: `fbca505...39e3648` (reselection follow-up after the diff-7 fixes)

Reviewer: fresh goldfish with no history: separate Claude Code cloud session
`session_01GLSX4gssiYEbjz8xQ5ZV3s` (model claude-opus-5-5, the same model family as the
writer, because no other family was available to this job). Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW.
It was asked to verify the B1, G1 and H1 blockers independently on both paths and to check
five properties explicitly: ciphertext preservation, rejection authentication, reservation
fencing, duplicate-screening visibility, and Murphy closure.
Its reply is reproduced verbatim below. The elephant's dispositions follow it.

FAIL

# Goldfish review: registry-pending-promotion, reselection addendum (diff-8)

**Personas:** Zoom Out and Implementation Readiness. **Mode:** REVIEW.
**HEAD:** `39e3648131656e8a0a1fa91ff17710135ebc636a`, confirmed. **Base:** `origin/factory-simplify` = `fbca505894bda2b5ac6042994ed46a507e678925`.

The probes ran on throwaway copies of `sealed/statement-registry` with real ciphertext from `sealed/case-*.statement.age`. They loaded the base and HEAD copies of `registry.py` and `statement_round.py` from the scratchpad. The repository was not modified.

## Findings

### F1 (Blocking): stale history bytes now fail another wave's whole `prepare`, where base succeeded. This contradicts the design's diff-6 claim.

**Where:**
- `factory/registry.py:119-126`, the release branch of `replace_rejected`.
- `factory/statement_round.py:100-107`.
- `docs/designs/registry-pending-promotion.md:112-114`, which claims an unauthenticated history card "returns or refuses exactly as base did, so it never fails the wave on its own".
- `tests/factory/test_registry_promotion.py:169`, which asserts the new failure.

**Problem:**
- `prepare` now sends every history import that has a digest through `replace_rejected`.
- When the previous entry has another digest, `replace_rejected` raises "different content" itself in two cases:
  - the card is not authenticated, so `rejected=[]` and `old not in rejected`;
  - the offered bytes equal the stored ciphertext (the byte-identity guard).
- In both cases it raises before it reaches `reserve`. On base, `reserve(historical=True)` returns the existing entry in this case through `if historical and previous["cipher_sha256"] == digest: return previous`. It keeps d1/c1 and binds nothing.
- The input is the B1 scenario: Y's card has moved to d2, but the collected `case-py.statement.age` is still c1. The reviews already treat that as realistic.
- Today that input fails another wave X with exactly the row's symptom ("another wave raises different content"). On base it was harmless. The failing case includes a plain legacy card `{"statement_sha256": d2}` that has no rejected list at all.

**Probe on a copy of the real registry, with real c1/c2 ciphertext.** In both starting states, Y reserved and Y historical-only:

| X's history card for `case-py`, collected bytes c1 | base | HEAD |
|---|---|---|
| `{"statement_sha256": d2}` (legacy, nothing rejected) | ok, entry stays d1/c1 | **RAISE different content** |
| legacy d2, rejecting d1 | ok, entry stays d1/c1 | **RAISE** |
| d2 with `statement_cipher_sha256 = sha(c2)`, rejecting d1 | ok, entry stays d1/c1 | **RAISE** |
| d2 with a cipher binding of c1, rejecting d1 (the test's line-169 card) | ok | **RAISE** (asserted by the test) |

In every row, base binds nothing and keeps the d1/c1 entry visible to screening. The new raise therefore adds no safety, only a wave failure. The B1 harm, binding c1 to d2, was introduced by this branch. Base never had it, so refusing at this point regresses base instead of restoring it.

**Fix:** in `replace_rejected`, release only when the request is fully authenticated:
- the old digest is known and listed in `rejected`;
- the status and `bound` rules hold;
- the stored ciphertext differs from the offered bytes.

In every other case, fall through to `self.reserve(...)` and do not raise. `reserve` then gives base's answer on both paths:
- **History path:** it returns the previous entry when the bytes are identical, and otherwise raises "different content".
- **Candidate path:** it raises "different content", because the statements differ and there is no promotion.

Then change `test_registry_promotion.py:169` and the bound-c1 sub-case to assert that X's wave succeeds and the entry stays d1/c1. Keep the assertion that Y's own handoff with c1 raises (line 171): there `reserve` refuses on the candidate path. Also add a case for the plain legacy card `{"statement_sha256": d2}` with c1 bytes.

### F2 (Nit): the design misdescribes what happens after the slot is resurrected.

**Where:** `docs/designs/registry-pending-promotion.md:116-117`.

The design says "the next authenticated import refuses loudly instead of binding anything". Probe: an entry is released, a stale wave re-imports d1 as historical-only, and then a bound import of d2 runs through `replace_rejected(historical=True, bound=True)`. It **succeeds**: it releases the resurrected d1 and stores d2/c2, and Y's own handoff promotes it afterwards. That outcome is safe and arguably better than a refusal, but the text is wrong.

**Fix:** reword to "the next authenticated import re-releases it".

### F3 (Nit): the decision in `replace_rejected` is one dense boolean.

**Where:** `factory/registry.py:117-123`.

The release decision mixes `complete`, `old is None`, `bound` and `status` in one expression, and the F1 confusion between "not authenticated" and "refuse" grew out of it.

**Fix:** after the F1 change, split it into `authenticated = ...` and then `if authenticated: fenced release`, followed by `return self.reserve(...)`. That gives one exit for everything that is not authenticated.

## Explicit checks

### 1. Ciphertext preservation: **PASS on safety, FAIL on liveness (F1)**

No path this diff added or changed binds rejected bytes, or another seal of them, to a new digest:
- A historical-only release needs `bound`, the own card's `statement_cipher_sha256` equal to sha256 of the offered bytes.
- On the history path, `rejected` is empty unless the card is bound.
- The byte-identity guard is still there.

**Probes:**
- The G1 and H1 inputs (legacy card plus another real seal) refuse on both paths, and the entry stays d1/c1.
- Promotion keeps the stored c2 object when Y hands off another seal of d2.
- Exports carry the stored `cipher_sha256`.

**Caveat:** the safety comes partly from a raise that fails waves base accepted (F1).

### 2. Rejection authentication: **PASS**

- **Release requires all of these:**
  - the old digest is not None;
  - it appears in the case's own card `rejected_candidates`;
  - for a complete entry, status is screening or building;
  - for a historical-only entry, `bound` is true and status is `completed`.
- **These authenticate nothing:**
  - `known_public` (tested on both paths);
  - a None digest, which falls through to `reserve`;
  - a missing or mismatched binding, which gives `bound=False` and on the history path `rejected=[]`;
  - a malformed history list.
- **Still raises:** unlisted or mismatched content, tested in both starting states.

### 3. Reservation fencing: **PASS**

- `transition(..., expect=...)` compares token, not-released, status, digest and cipher under the lock.
- A same-token status change raises "stale reservation" (tested).
- The retry runs at most once (`for attempt in (0, 1)`, and a second failure re-raises), and it re-applies every check.
- In both interleavings of concurrent X and Y releases, my reading ends in the same digest or in a promotion, never in different content being accepted.
- `transition` without `expect` is unchanged: the `a or b or (c and d)` precedence is correct, and a probe showed a building transition still works.

### 4. Duplicate-screening visibility: **PASS, with the documented gap**

- Only content that its own card names rejected leaves screening.
- New content stays visible as historical, then is promoted.
- **Release→reserve gap:** a reservation made inside the gap omits this case. Pairwise screening still holds, because this case's later reservation (promotion or reserve) recomputes `earlier` and so includes that case.
- **Failed reserve after a release:** the slot stays released until a retry, and the retry self-heals (see F2). Acceptable as documented.

### 5. Murphy `new-registry-pending-promotion-1` can be closed: **NO**

- **The real-artifact proof is incomplete.** The tests use a copy of the real registry and real age ciphertext, but the scorecards are hand-authored with synthetic digests (`"1"*64`, `"2"*64`). The design admits that no retained real card carries `statement_sha256` or `rejected_candidates`, so the reselection shape has never been seen on a real artifact.
- **The precedent does not settle it.** Row 7 was closed on the same kind of fixture. Even granting that, section 2 asks whether the test "really proves the row", and the row's harm (another wave failing on "different content") is still reachable for stale-history inputs through F1.
- **The branch is right to leave the row open.**

### 6. Other blocking issues (readiness / zoom-out): **FAIL (F1)**

- **Regression and mismatch:** F1 is a regression against base, it contradicts the design text, and a test encodes the regression.
- **Pre-existing hole is not made worse:** for the candidate path with a reserved or screening entry and a legacy own card, the complete-entry branch keeps base's rule and adds only stricter guards (the byte-identity check and refusing invalid input before release). No new route reaches that state: the history path needs `bound`, and historical-only entries need `bound` on the candidate path.
- **Zoom-out, no new findings beyond F3:** the change reuses `reserve` and `transition` and adds no new modules. The simpler "authenticate or delegate to reserve" structure would remove F1.

## Tests run

| Command | Result |
|---|---|
| `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py` | Ran 19, OK |
| `BENCH="$PWD" python3 -B tests/factory/test_statement_round.py` | Ran 18, OK |

Scratchpad probes, run against both the base and HEAD copies:
- `/tmp/claude-0/-home-user-unbug-bench/699fd102-de79-5438-9681-370a2e5528d9/scratchpad/probe.py` covers the stale-bytes, other-seal, bound and own-handoff matrix in both starting states. It shows the F1 base-ok versus HEAD-raise rows.
- `/tmp/claude-0/-home-user-unbug-bench/699fd102-de79-5438-9681-370a2e5528d9/scratchpad/probe2.py` covers the resurrection gap and `transition` without `expect`. It shows F2.

---

## Dispositions (elephant)

Nothing rejected. The updated test fails on 39e3648 (2 subtest errors) and passes on the fixed head.

- **F1 and F3, fixed as suggested.**
  - `replace_rejected` computes one `authenticated` predicate. It requires all of the following: the old digest is known and listed; the digest differs; the stored ciphertext differs from the offered bytes; a complete entry is screening/building; a historical-only entry is `completed` and `bound`.
  - When `authenticated` holds, the method does the fenced release. Every input then exits through `reserve`, which gives base's answer: return, promote, or refuse.
  - The method itself no longer raises "different content".
  - `test_stale_history_ciphertext_cannot_take_reselected_digest` now asserts the following:
    - X's wave succeeds with c1 bytes for four cards: the default card bound to c1, the plain legacy `{statement_sha256: d2}`, the legacy card rejecting d1, and a card bound to c2.
    - Each of those leaves the entry byte-for-byte unchanged.
    - Y's own handoff with c1, even with `bound=True`, still raises.
- **F2: design wording corrected** in the diff-8 paragraph.
- **Murphy row `new-registry-pending-promotion-1`: stays open.**
