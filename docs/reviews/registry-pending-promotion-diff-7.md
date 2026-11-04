# Goldfish diff review 7: `fbca505...f3cca5f` (reselection follow-up after the diff-6 fixes)

Reviewer: fresh goldfish with no history: separate Claude Code cloud session
`session_01GLSX4hBBmA2MkXcrr1S8o1` (model claude-opus-5-5, the same model family as the
writer, because no other family was available to this job). Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW.
It was asked to verify the diff-5 (B1) and diff-6 (G1) blockers independently and to check
five properties explicitly: ciphertext preservation, rejection authentication, reservation
fencing, duplicate-screening visibility, and Murphy closure.
Its reply is reproduced verbatim below. The elephant's dispositions follow it.

FAIL

# Goldfish review: reselection between the history snapshot and the handoff (`new-registry-pending-promotion-1`), diff-6 follow-up at f3cca5f

**Setup**
- Mode: REVIEW.
- Personas: zoom_out and implementation_readiness.
- Standard: `implementation-readiness-standard.md`.
- HEAD is confirmed as `f3cca5faa56280f3930645a6d2c938688d6dd6b4`. The base is `origin/factory-simplify` = `fbca505`.

**Scope**
- The design addendum and its follow-ups for diff-3, diff-5 and diff-6.
- `git diff origin/factory-simplify...HEAD -- factory tests docs/designs`.
- The files that diff references.
- `docs/ENGINEERING.md` §2 and §4.
- Murphy row `new-registry-pending-promotion-1`.
- I wrote nothing to the repo. All probes ran in the scratchpad, on copies of `sealed/statement-registry` and real `sealed/*.statement.age` files, against `git archive`d `factory/` trees of both base and HEAD.

## Findings

### Blocking

**H1: The G1 harm is still reachable through Y's own handoff. A different seal of the rejected statement is bound to the new digest, promoted and exported. Base refused the same input.**

- **Where:** `factory/statement_round.py:111-114` (the candidate path) and `factory/registry.py:116-118`.
- **What the diff changed:** `replace_rejected` now also releases a historical-only entry with a known digest. The added condition is `(previous["complete"] or old is not None)`, and the narrowed screening/building check is applied only when `complete` is set.
  - That new release is reached from the candidate path too.
  - The candidate path's `rejected` comes from the case's own card, and nothing ties that card to the collected bytes.
  - `prepare_restore` (`statement_round.py:71-73`) checks `statement_cipher_sha256` only when the card has it.
  - `coordinator_inventory.py:146-156` checks only that the worker and the host agree on the bytes, not that the bytes match the card.
- **The disposition is wrong:** The diff-6 disposition says "Candidate path, not changed". That is not true for this starting state, and the design's diff-6 paragraph closes G1 only for the history path.
- **Probe P1:**
  - Setup: another wave imports Y as history with d1/c1. Y's own card is the legacy shape `{statement_sha256: d2, rejected_candidates: [{d1}]}`, with no `statement_cipher_sha256`. Y's collected bytes are a different real seal (`real[5]`). Then `prepare(..., {case-py: d2})` runs.
  - HEAD: c1 is released and d2 is bound to the stale bytes with `complete=True`. Every later reservation now screens against the rejected statement instead of c2.
  - Base `fbca505`: "case already reserved with different content".
- **Related, but not a regression:**
  - P2, the same input from the *reserved* (screening) state, already bound the stale bytes on base. That hole is older than this branch.
  - P3, the exact stale bytes c1, is refused on both thanks to the byte-identity guard.
- **Reachability:** This is the same as G1: a legacy-shape or carried-over own card. The diff-6 review treated that reachability as blocking, and the same standard applies here. It also fails explicit check 1 as worded: no other seal can be bound to a new digest.
- **Fix:** Use the history-path rule for the new release.
  - Release a *historical-only* previous entry only when the caller's card binds the collected bytes, meaning `statement_cipher_sha256` is present and equals sha256(bytes). For example, have `prepare` pass `rejected=[]` for a candidate whose card lacks a matching cipher binding whenever the stored entry is historical-only. An alternative is a `bound=` argument to `replace_rejected` that gates the `not previous["complete"]` branch.
  - Keep base behaviour for screening/building entries, so the older P2 hole does not turn into a new refusal unless you choose that.
  - Add a test: a legacy own card plus `real[5]`, starting from the history state, must refuse and keep d1/c1.
  - Correct the disposition and add a design sentence.

### Major (non-blocking)

**M1: A historical-only entry is released whatever its non-released status, including `known_public`. Base never released one.**
- **Where:** `factory/registry.py:118`. The status check applies only when `previous["complete"]` is set.
- **Probe P7:**
  - Setup: a historical-only d1 entry is moved to `known_public` with `transition`, then Y's handoff runs with a bound card that rejects d1.
  - HEAD: the entry is released and replaced (d2, `screening`).
  - Base: refused.
- **Why it is non-blocking:**
  - No code path sets `known_public` except the CLI (`registry.py:238`).
  - All 37 retained historical entries are `completed` and digestless.
- **The concern:** `known_public` reads as a deliberate operator mark, and the release removes it from screening.
- **Fix:** Require `previous["status"] == "completed"` for the historical-only branch, or document why `known_public` may be released.

**M2: The release→reserve gap (carried from diff-5 M2 and diff-6 G3).**
- **Where:** `registry.py:123` and `:128` take the lock separately.
- **Why it is acceptable:** The pairwise argument holds. Y's own later reservation recomputes `earlier` from every live entry. A resurrected stale d1 only over-screens, and the next authenticated import refuses it loudly.
- **One more sub-case for the "Known gap" paragraph:**
  - If `reserve` raises after a successful release (W resurrects d1, or "registry object corrupted"), Y is left released with no replacement until a retry.
  - Only content that Y's own card named as rejected leaves screening, so this is safe. Still, the paragraph should say it.

### Nits

- **N1 (zoom_out):** An unlocked decision, an `expect` fence and a retry-once are still three mechanisms where one locked compare-and-release would do. The previous dispositions accepted this, and the fence makes it correct.
- **N2:** In `test_registry_promotion.py`, the module docstring still describes only the Murphy row-7 scope, although the file now carries 10+ row `new-registry-pending-promotion-1` tests.
- **N3:** The design's diff-6 paragraph does not mention that the candidate path now reaches the historical-only release (see H1).

## Explicit checks

**1. Ciphertext preservation: FAIL (H1).**

What holds:
- The history path now authenticates only cards bound to the collected bytes. The diff-6 G1 input is refused in both starting states (tested). The G2 cipher-skew case no longer fails X's wave and keeps the stored bytes (tested).
- The byte-identity guard refuses the exact stale bytes on both paths (tested, and probe P3).
- Promotion keeps the stored ciphertext (`test_own_handoff_keeps_reselected_ciphertext_imported_as_history`).
- Exports carry the stored `cipher_sha256`.
- Released objects stay on disk.

What fails:
- The candidate path from the historical-only state binds another seal of d1 to d2 (P1). This is a regression against base.

**2. Rejection authentication: PASS on the history path. FAIL on the candidate path's new branch (H1).**

History path:
- A release requires `old is not None and old in rejected`.
- `rejected` is non-empty only when the case's own history card binds the collected bytes, is a list of at most 3 rows, and every row is a dict.
- A None digest never authenticates. Probes P5 (`[{}]`) and P6 (a digestless previous entry with `[None]`) both refuse.
- A malformed list authenticates nothing (4 subtests).
- Unlisted or mismatched digests raise in both starting states.
- A complete finished entry (`completed`) is refused (P4).

Candidate path:
- It needs no binding for the new historical-only release (H1).
- It still raises on a malformed own list. That is unchanged and documented.

**3. Reservation fencing: PASS.**
- `transition`'s condition parses as `token != r or released or (expect is not None and expect != (status, digest, cipher))`, compared under `LOCK_EX`. Callers without `expect` (the CLI) are unchanged.
- A same-token change (building/screening → completed) raises "stale reservation", and the retry re-reads and refuses (`calls == ["released"]`, tested).
- The retry is bounded at 2 (tested by a mock call count).
- After a retry the code re-decides from a fresh read. It cannot loop, release an unlisted entry, or accept different content.
- `complete` changes only by minting a new token, so the token covers it.

**4. Duplicate-screening visibility: PASS with caveats (M1, M2). Weakened by H1 when it triggers.**
- On the history path, nothing leaves screening except an entry that its own bound card names as rejected.
- Pending history imports stay non-released and are included in `earlier`.
- Snapshots that already include c1 stay fixed.
- The documented gap is real, and the pairwise argument holds.
- When H1 triggers, the rejected statement's content stays in screening in c2's place.

**5. Murphy `new-registry-pending-promotion-1` closure on real artifacts: NO.**
- ENGINEERING §2 and §4 "Real artifacts" require a test that uses real saved cards.
- The tests use a real registry copy and real ciphertext, but every digest, cipher binding and rejected list on the cards is hand-authored.
- None of the 53 `sealed/*.scorecard.json` carries `statement_sha256`, `statement_cipher_sha256` or `rejected_candidates`.
- The retained registry's entries are 37 digestless historical entries, 3 screening and 1 released. None of them can reach the new release branch.
- H1 also shows that the row's requirement ("never silently replace different content") is not met on every path.
- Leaving the row open is correct.

**6. Other (implementation_readiness / zoom_out): FAIL (H1).**
- Regressions against base:
  - P1: a refusal becomes a silent wrong binding on the candidate path.
  - P7: a refusal becomes a release, for historical-only `known_public` entries.
  - No other regressions found. The row-7 tests and `test_statement_round` pass.
- Design/code mismatch: the diff-6 disposition says "Candidate path, not changed", but the candidate path now releases historical-only entries without a cipher binding.
- Untested claimed branch: the candidate-path historical-only release is tested only with cards that bind the bytes. There is no legacy-card negative test.

## Tests run

**Focused tests at HEAD:**

| Command | Tests | Result |
|---|---|---|
| `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py` | 17 | OK |
| `BENCH="$PWD" python3 -B tests/factory/test_statement_round.py` | 18 | OK |

**Scratchpad probe** (`probe.py`), run against base and HEAD `factory/`, using copies of the real registry and real ciphertext:

| Probe | Input | Base | HEAD | Notes |
|---|---|---|---|---|
| P1 | Candidate path, legacy own card, another seal of d1, starting from history | refuse | **binds stale bytes, complete** | H1 |
| P2 | Same as P1, starting from reserved | binds | binds | Older than this branch |
| P3 | Candidate path, exact stale bytes, starting from history | refuse | refuse | |
| P4 | History bound card against a finished complete entry | refuse | refuse | |
| P5 | History bound card with rows `[{}]` | refuse | refuse | |
| P6 | Digestless previous entry with `[None]` | refuse | refuse | |
| P7 | Candidate path against a historical-only `known_public` entry | refuse | **release, then screening d2** | M1 |

---

## Dispositions (elephant)

Nothing rejected. Both new tests fail on f3cca5f and pass on the fixed head.

- **H1, fixed in `replace_rejected` itself, so the rule holds on both paths.**
  - The method takes `bound=`, meaning the caller's card carries a `statement_cipher_sha256` equal to sha256 of the offered bytes.
  - A historical-only previous entry is released only when `bound` is true.
  - `prepare` computes `bound` for history cards and for candidate cards.
  - Complete screening/building entries keep base behaviour, so the pre-existing P2 hole is unchanged and no new refusal is introduced.
  - Test: `test_own_handoff_needs_bound_card_to_release_historical_only_entry`. A legacy own card with a different real seal refuses and keeps d1/c1/historical; a bound card still releases.
  - The diff-6 "Candidate path, not changed" disposition was wrong. The design is corrected.
- **M1, fixed.** The historical-only release also requires status `completed`. Test: `test_known_public_historical_entry_is_never_released`, run through both the candidate path and the history path.
- **M2: the design "Known gap" paragraph now also covers a `reserve` failure after a release.**
- **N1: accepted, as before.**
- **N2: fixed.** The module docstring now covers both rows.
- **N3: fixed** by the diff-7 design paragraph.
- **Pre-existing P2 hole, not fixed here (out of scope).** It is a candidate path from the reserved state with a legacy own card. It needs its own design decision, because refusing legacy own cards there would change base behaviour.
- **Murphy row `new-registry-pending-promotion-1`: stays open.**
