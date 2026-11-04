# Goldfish diff review 5: `fbca505...9b950bf` (reselection follow-up, final review after merging factory-simplify)

Reviewer: fresh goldfish with no history: separate Claude Code cloud session
`session_01GLSX4g2DV59KGk5EZbU6KR` (model claude-opus-5-5, the same model family as the
writer, because no other family was available to this job). Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW.
Its scope was limited to the design addendum, the diff, and the files they reference. It was
asked to check these explicitly: ciphertext preservation, rejection authentication,
reservation fencing, duplicate-screening visibility, and Murphy closure.
Its reply is reproduced verbatim below. The elephant's dispositions follow it.

FAIL

# Goldfish review: reselection between history snapshot and handoff (`new-registry-pending-promotion-1`)

Mode: REVIEW. Personas: zoom_out and implementation_readiness. Standard: `implementation-readiness-standard.md`.
Scope: the design addendum and its "Review follow-ups" paragraph, plus `git diff fbca505...9b950bf -- factory tests docs/designs`.

## Findings

### B1 (Blocking): an authenticated release accepts a stale ciphertext, so the wrong ciphertext gets bound to the new digest
**Where:** `factory/registry.py:104-123` and `factory/statement_round.py:93-102`.

**Problem:** The history import path reads the history card's `statement_sha256` and `rejected_candidates`. It never checks that the history ciphertext belongs to that card. The candidate path in `same_worker_handoff` does check this, at `statement_round.py:71-73` (`statement_cipher_sha256`).

Suppose Y's collected card is already the new one (d2, rejecting d1) but `case-py.statement.age` in the history dir is still c1. Then `replace_rejected(..., historical=True)` releases Y's c1 entry and reserves d2 with c1's bytes.

I reproduced this in the scratchpad on a copy of `sealed/statement-registry` with real ciphertext:
- After X's wave, the entry has `statement_sha256 == d2`, `cipher_sha256 == sha256(c1)`, `complete=False`.
- Y's own handoff then passes the correct c2. It promotes by the row 7 rule ("keep stored ciphertext") and exports `cipher_sha256 == sha256(c1)`, not c2.
- Every later reservation therefore screens against the rejected c1 and never against the selected c2.

On the base commit this same input raised "different content" loudly. The diff turns that into a silent wrong binding. That breaks the design's own rule ("never silently replace different content or weaken duplicate screening"), and it is the register row's stated fix requirement.

The contradiction can be detected without any card data: identical ciphertext bytes with a different plaintext digest.

**Fix:**
- In `replace_rejected`, refuse the release when `sha256(ciphertext) == previous["cipher_sha256"]` while the statement digests differ.
- In `prepare`, check the history card's `statement_cipher_sha256` against the history ciphertext when the field is present, the same way the candidate path does.
- Add a test for each.

### M1 (Major, non-blocking): the decision is made outside the lock, and `transition` checks only the token
**Where:** `factory/registry.py:110-122` and `:187-197`. This was already present on base; the diff extends it to every history import.

**Problem:** The status check `previous["complete"] and status not in ("screening","building")` runs on an unlocked read. `transition(released)` checks only that the token matches and the entry is not released. It does not check status or digest.

So a complete entry can go from `building` to `completed` (or `known_public`) under the same token between the read and the release, and it is then released anyway. The follow-up paragraph's claim that "every race ends in success, retry or refusal" does not cover this case.

**Fix:** Do the compare-and-release under the registry lock. Either:
- give `transition` an expected status and digest (or a "release only if" predicate), or
- run the release and the reserve inside one locked section.

Moving the decision under the lock also removes the need for the retry loop, which is the simpler design (zoom_out).

### M2 (Major, non-blocking): a visibility gap between the release and the reserve
**Where:** `factory/registry.py:119` and `:123`. Already present on base for candidate reselection; this diff adds it to every other wave's history import.

**Problem:** The release and the following `reserve` take the lock separately. A concurrent `reserve` for another case Z that lands between them gets an `earlier` set with no `case-py` at all: neither c1 nor c2. Strictly, that contradicts the addendum's "stays visible to X and every later reservation".

This is mitigated, not eliminated. Y always takes a fresh reservation afterwards (promote or reserve) with recomputed predecessors, so Y screens against Z and pairwise coverage holds.

**Fix:** The single locked section from M1 fixes this as well. Otherwise, state the pairwise argument in the design.

### M3 (Major, non-blocking): the new branch is not reached from any real artifact
I checked all 53 `sealed/*.scorecard.json`: none has `statement_sha256` or `rejected_candidates`.

On real data, every history import therefore takes the unchanged `import_historical` branch. The only evidence for the new branch is the hand-authored cards in `tests/factory/test_registry_promotion.py:97-106`. This matters for check 5 below.

### N1 (Nit): history cards can now fail every wave
**Where:** `statement_round.py:97-98`.

History cards are now parsed for `rejected_candidates` and checked against the bound of 3. A history card with more than 3 entries, a `null` list, or a row that is not a dict now fails X's whole wave with a `ValueError`, `TypeError` or `AttributeError`. Before the diff, that field on history cards was ignored.

**Fix:** Parse `rejected_candidates` only when `digest is not None`. Treat a malformed list as no authentication, so the code falls through to `reserve` and refuses there, rather than crashing the import.

### N2 (Nit): untested branches
**Where:** `tests/factory/test_registry_promotion.py`.

- No test where the rejected list contains `None`, from a row with no `statement_sha256`, against a digestless entry.
- No test that a complete `completed` or `known_public` entry is refused through the `historical=True` path.
- The retry test is fully mocked. That is acceptable for proving the loop is bounded.

### N3 (Nit): the new tests can't tell a kept ciphertext from a replaced one
**Where:** `tests/factory/test_registry_promotion.py:110-124`.

The reselection test uses the same c2 file for both X's history and Y's handoff, so it cannot distinguish "kept the stored ciphertext" from "stored the new one". Row 7's `test_promotion_keeps_stored_ciphertext` covers promotion in general, and B1 shows why the distinction matters here.

## Explicit checks

1. **Ciphertext preservation: FAIL (B1).**
   - Holds: an entry not authenticated as rejected is never released. Same-digest calls return the stored entry and ciphertext. Released objects stay on disk. Promotion keeps the stored ciphertext. The test asserts that the X export digest equals Y's `cipher_sha256`.
   - Fails: an authenticated release accepts a ciphertext identical to the rejected one under the new digest. That binding is then kept and exported.
2. **Rejection authentication: PASS.**
   - A release requires `old is not None and old in rejected`, read from that case's own card: `history/<case>.scorecard.json` or `sealed/<case>.scorecard.json`.
   - A `None` digest never authenticates: it is guarded before the membership test, and a digestless historical entry falls through to `reserve`, which returns the entry or refuses.
   - Unlisted or mismatched digests raise "different content". Tests cover both cases in both starting states.
   - Caveat: this authenticates the digest only, not the card-to-ciphertext pairing (B1).
3. **Reservation fencing: PASS with caveat (M1).**
   - `transition` uses the token read from the entry. A stale token raises. The retry runs at most once and the second failure re-raises (tested, call count 2).
   - After a retry, the re-read either matches the new digest (returns the stored entry), is unlisted (refuses), or is released (fresh reserve). It cannot loop or accept different content.
   - Caveat: it can release a complete entry whose status changed under the same token (M1). This predates the diff.
4. **Duplicate-screening visibility: FAIL as a consequence of B1; otherwise PASS with caveat (M2).**
   - Only a candidate named rejected by its own card is removed. Pending history imports stay `completed`/`complete=False` and remain in `earlier`.
   - B1 leaves the rejected c1 bytes visible instead of c2.
   - M2 leaves an unlocked gap; pairwise screening is preserved through Y's recomputed reservation.
5. **Murphy row `new-registry-pending-promotion-1`: NO, do not close.**
   - ENGINEERING §2 and §4 "Real artifacts" require a test on real saved cards. The registry and ciphertext in the tests are real, but every scorecard digest and rejected list is hand-authored.
   - No real card in `sealed/` carries `statement_sha256` or `rejected_candidates`, so no real artifact reaches the new branch (M3).
   - B1 also shows the row's fix requirement ("never silently replace different content") is not yet met.
   - Recommendation: keep the row `open`, or mark it fixed-locally / not closed, until B1 is fixed and a real collected reselection card exists to test against.
6. **Other (implementation_readiness / zoom_out):**
   - No regression in existing behaviour: the row 7 tests and `test_statement_round` pass.
   - The 5 new behaviour tests fail on base `fbca505` and pass on HEAD, consistent with the design's "fails on parent".
   - Design/code mismatches: "every later reservation" (M2) and "every race ends in success, retry or refusal" (M1).
   - Zoom-out: the unlocked decision plus the retry-once is extra machinery that a single locked compare-and-release would make unnecessary.
   - N1 is a new failure mode on history cards.

## Tests run
- `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py`: 11 tests, OK.
- `BENCH="$PWD" python3 -B tests/factory/test_statement_round.py`: 18 tests, OK.
- The same promotion test module against base `fbca505`'s `factory/`, extracted with `git archive` into the scratchpad: 11 run, 5 errors. The failures are the reselection test (×2 subtests), the own-handoff release test, the retry test and the malformed-input test, as expected. The unauthenticated-refusal tests pass on base, also as expected.
- A scratchpad probe of B1 on a copy of the retained registry with real age ciphertext: confirmed that d2 is bound to c1's ciphertext and that Y's handoff exports c1.

---

## Dispositions (elephant)

Nothing rejected. Each fix below has a test that fails on 9b950bf (B1: 2 subtests, M1: 1, N1: 4 subtests)
and passes on the fixed head. The exception is N3, which is coverage only and passes on both.

- **B1, fixed.**
  - `replace_rejected` refuses a release when the offered bytes equal the stored ciphertext under a different digest.
  - `prepare` checks a history card's `statement_cipher_sha256` against its ciphertext when the field is present.
  - Test: `test_stale_history_ciphertext_cannot_take_reselected_digest`, which runs both starting states, X's wave, Y's own handoff, the bound card, and the consistent card.
  - Limit: a card that has no `statement_cipher_sha256`, for a case the registry has never seen, still cannot be checked. Base behaves the same way.
- **M1, fixed.**
  - `transition` takes `expect=(status, statement_sha256, cipher_sha256)` and checks it under the lock. The release passes the values it read.
  - If the entry changed under the same token, the release now raises "stale reservation". The single retry re-reads and refuses.
  - Test: `test_release_is_fenced_on_status_changed_under_same_token`.
  - The retry loop is kept. Merging release and reserve into one locked section would mean restructuring the merged row-7 `reserve`, which this job must not redo.
- **M2, accepted as documented (non-blocking).** The design now states the gap between the release and the reserve, and the pairwise argument for why it is safe.
- **M3, accepted.** It is the reason the Murphy row stays open; see below.
- **N1, fixed.**
  - `rejected_candidates` is parsed only for history cards with a digest.
  - A malformed list (null, a non-list, non-dict rows, or more than 3 rows) authenticates nothing, so the import falls through and refuses.
  - Test: `test_malformed_history_rejected_list_authenticates_nothing`.
- **N2, not changed.**
  - A None row against a digestless entry is already covered by the `old is None` guard, and the guard is unchanged.
  - The completed/known_public refusal predates this change.
- **N3, fixed.** Test: `test_own_handoff_keeps_reselected_ciphertext_imported_as_history`, which hands off a different real seal of d2 and checks that the stored c2 binding is kept.
- **Murphy row `new-registry-pending-promotion-1`: left open.**
  - No retained real card carries `statement_sha256` or `rejected_candidates`, so the new branch runs only on hand-authored cards.
  - That does not meet ENGINEERING section 2 or the section 4 real-artifacts rule.
