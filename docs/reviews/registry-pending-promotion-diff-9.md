# Goldfish diff review 9: `fbca505...48b8e3c` (reselection follow-up, final code review)

Reviewer: fresh goldfish with no history: separate Claude Code cloud session
`session_01GLSX4ibAggFnXUBv6soTZA` (model claude-opus-5-5, the same model family as the
writer, because no other family was available to this job). Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW.
It was asked to verify the B1, G1, H1 and F1 blockers on both paths, to compare the
non-release behaviour with base, and to check five properties explicitly: ciphertext
preservation, rejection authentication, reservation fencing, duplicate-screening visibility,
and Murphy closure. Its reply is reproduced verbatim below. The elephant's dispositions
follow it.

PASS

# Goldfish diff review: reselection between history snapshot and handoff (`new-registry-pending-promotion-1`), diff-8 follow-up at 48b8e3c

**Personas:** Zoom Out and Implementation Readiness. **Mode:** REVIEW.
**HEAD:** `48b8e3c940f2e17816f6f78aa008df566d474e33`, confirmed. **Base:** `origin/factory-simplify` = `fbca505894bda2b5ac6042994ed46a507e678925`, fetched; it is the merge-base.
**Scope:** the design addendum and its diff-3, -5, -6, -7 and -8 follow-ups; `git diff origin/factory-simplify...HEAD -- factory tests docs/designs`; `factory/registry.py`, `factory/statement_round.py` and `tests/factory/test_registry_promotion.py`; ENGINEERING.md and the Murphy register row. No repository files were changed, and nothing was decrypted.

## Method

I extracted base's `registry.py` to a scratchpad and compared base with head on copies of the real retained registry (`sealed/statement-registry`, 41 entries) and real `sealed/*.statement.age` ciphertext. The probe script is `/tmp/claude-0/-home-user-unbug-bench/7b994200-c680-5651-a6cb-6f78ede08747/scratchpad/diff_probe.py`.

It covered every combination of the following, 3,360 combinations in total:

- **Previous state of `case-py`:** none; complete screening, building, completed, known_public or released; historical completed, known_public or released, each with digest d1 or None.
- **Path:** history (base `import_historical`; head as `prepare` does it) or candidate (`replace_rejected`).
- **Offered digest:** d1, d2, None or invalid.
- **Offered bytes:** c1 (the stored bytes), c2, another real seal c3, or non-age junk.
- **Rejected list:** `[]`, `[d1]`, `[d2]`, `[None]` or `[d1, None]`.
- **Bound:** true or false.

For each combination it compared the outcome, the `case-py` entry (minus token and revision), the set of objects, and every other entry.

**Results:**

- **3,136 identical.** This includes every history-path input where head does not release.
- **16 differ, with head releasing.** These are all the intended new releases. In every one the offered digest is new, d1 is in the caller's list, the bytes differ from the stored ones, the history path had `bound`, and a historical-only entry was `completed` and `bound`. The resulting entry binds exactly the offered digest and bytes. I checked each of these with assertions.
- **208 differ with no release, all on the candidate path, of two kinds:**
  - **200: invalid digest or non-age bytes.** Both base and head refuse, but base could release the reservation first and then fail inside `reserve`. Head refuses before any release. This is strictly safer; only the error message differs.
  - **8: the same stored bytes c1 offered under a new digest d2, with d1 listed as rejected, from complete screening or building.** Base released and bound c1 to d2. Head refuses with "different content". This is the deliberate diff-5 B1 guard (see Major M1).

## Findings

### Major (non-blocking)

**M1: one intended divergence from base contradicts the design's "base's answer" wording.**
- **Where:** `factory/registry.py:122` (`previous["cipher_sha256"] != cipher`) and `docs/designs/registry-pending-promotion.md`, the diff-8 paragraph ("Every input then goes to `reserve`, which gives base's answer").
- **Problem:** On the candidate path, base released and re-reserved when the offered bytes equalled the stored ciphertext under a new digest. Head refuses with "different content". So for this input head does not give base's answer.
- **Assessment:** The new behaviour is the correct one. Base bound stale bytes to a new digest, which explicit check 1 forbids. It is tested in `test_stale_history_ciphertext_cannot_take_reselected_digest`. Only the design text is wrong.
- **Fix:** Add one sentence to the diff-8 paragraph: "Exception: identical stored bytes under a new digest now refuse on the candidate path, where base released (diff-5 B1)."

**M2: the design addendum is a stack of superseded rules.**
- **Where:** `docs/designs/registry-pending-promotion.md`: the addendum's "Change" and "Unchanged / refuses" paragraphs, and the diff-3, diff-5 and diff-6 follow-ups.
- **Problem:** The earlier paragraphs still state things the code no longer does:
  - release is "the same authentication as before";
  - a release "is also refused" on byte identity;
  - "the next authenticated import refuses loudly".
  
  Only the diff-8 paragraph is accurate. A fresh implementer has to replay six paragraphs to find the rule. That is a zoom_out (context) and readiness (single source of truth) problem.
- **Fix:** Before merge, fold the addendum into one current-rule section built from the diff-8 predicate, the accepted gaps and the tests. Keep the history in the review files.

### Nits

- **N1:** `factory/registry.py:117-123`. The unlocked decision, the `expect` fence and the retry-once are three mechanisms where a single locked compare-and-release would do. This was accepted in earlier reviews and is correct as written.
- **N2:** `factory/statement_round.py:103` and `:114` hash the collected ciphertext, and `replace_rejected` and `reserve` read it twice more. This is harmless at these file sizes.
- **N3:** `factory/statement_round.py:101-104`. The history path accepts rows that are dicts without `statement_sha256` (they yield `None`). This is safe because `old is not None` guards it, but it is undocumented.

## Explicit checks

### 1. Ciphertext preservation: PASS
- **No release, no change:** wherever head does not release, the stored entry and its objects are unchanged and match base (probe).
- **Objects are kept:** a release only changes the entry's status. No object is ever deleted.
- **Same bytes refused:** the same bytes under a new digest are refused (`previous["cipher_sha256"] != cipher`).
- **Other seals need a binding:** another seal of a rejected statement is released only with a card binding those exact bytes (`bound`). A history-path release always requires `bound`, because `rejected=[]` otherwise. A historical-only release requires `bound` on both paths (`test_history_release_needs_card_bound_to_collected_bytes` and `test_own_handoff_needs_bound_card_to_release_historical_only_entry`).
- **Promotion keeps stored ciphertext:** `test_promotion_keeps_stored_ciphertext` and `test_own_handoff_keeps_reselected_ciphertext_imported_as_history`.
- **Exports carry the right digest:** they carry the entry's `cipher_sha256` (asserted in `test_reselected_pending_candidate_survives_other_wave_and_own_handoff`).
- **Pre-existing hole is not worse:** the candidate path from the reserved state with a legacy own card is unchanged from base. Head adds the byte-identity condition, so it is strictly narrower. The probe matches base for c2 and c3 in that state.

### 2. Rejection authentication: PASS
- **Release needs the full diff-8 predicate:** the previous digest is non-None and differs from the offered one, the caller's list names it, the stored bytes differ, and the status is screening or building (complete entry) or completed and bound (historical-only entry).
- **These never authenticate:** a None digest, a missing or mismatched cipher binding, a malformed list (non-list, more than 3 rows, non-dict rows) on the history path, a `known_public` entry, and a released entry. This held in the probe and in `test_malformed_history_rejected_list_authenticates_nothing` and `test_known_public_historical_entry_is_never_released`.
- **Unauthenticated input gets base's answer:** on the history path, head is identical to base in every non-release input. On the candidate path it is identical except M1 and the safer early refusal of invalid input.

### 3. Reservation fencing: PASS
- **Fenced under the lock:** `transition(..., expect=...)` checks the token, the non-released status and the `(status, statement_sha256, cipher_sha256)` triple under the lock. Operator precedence is correct (`and` binds tighter than `or`).
- **Stale and same-token changes fail:** a same-token status change raises "stale reservation" (`test_release_is_fenced_on_status_changed_under_same_token`).
- **Retry-once is bounded:** it re-reads and re-evaluates the full predicate. A second stale fence raises, so there is no loop (`test_stale_reservation_is_retried_once`). After the retry, different content goes through `reserve`, which refuses it.
- **Callers without `expect` are unchanged:** `expect=None` short-circuits the new check.

### 4. Duplicate-screening visibility: PASS, with the documented gap
- **Only the named candidate leaves screening:** a release removes only content that the entry's own card names rejected, and `reserve` immediately re-adds the offered candidate. Pending and historical candidates of other cases are never touched.
- **Release-to-reserve gap (accepted):** the release and the reserve take the lock separately, so a reservation for another case landing in between omits this case. Pairwise screening still holds, because this case's own later reservation recomputes `earlier` from every live entry.
- **Resurrection inside the gap (accepted):** a stale wave can re-import an old digest into the released slot. That only over-screens, and the next authenticated import releases it again, as the diff-8 correction says. The gap is acceptable as documented.

### 5. Murphy register (`new-registry-pending-promotion-1`): NO
- **What the tests use:** the tests run on copies of the real retained registry and real ciphertext. The scorecards that drive the branch are hand-authored, with synthetic digests (`"1"*64`, `"2"*64`) that are not the plaintext digests of those ciphertexts.
- **Why that is not enough:** no retained real card carries `statement_sha256` or `rejected_candidates`, and no real run has shown the failure. Section 4 "Real artifacts" asks for real saved cards, so this does not meet section 2's closing bar.
- **Leaving the row open is correct:** a close would need a card produced by the real writer (`factory/run.py:reselect_candidate`) from an actual reselection, or a retained real-run state. This is not blocking, because the branch does not claim closure.

### 6. Other blocking issues (regressions, untested branches, design/code mismatch): PASS
- **No regression versus base** in the probe, apart from the intended, tested tightening in M1.
- **Every claimed branch has a test:**
  - history and reserved starting states;
  - own handoff from historical-only;
  - fence;
  - retry;
  - stale bytes;
  - legacy cards;
  - `known_public`;
  - malformed lists;
  - malformed input;
  - cipher skew with no release.
- **Previous blocking findings are resolved on both the history and the candidate path:** B1 (diff-5), G1 (diff-6), H1 (diff-7) and F1 (diff-8).
- **Design/code mismatch:** only the documentation issues in M1 and M2, which are non-blocking.

## Tests run

- `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py`: 19 tests, OK.
- `BENCH="$PWD" python3 -B tests/factory/test_statement_round.py`: 18 tests, OK.
- **Scratchpad probe:** 3,360 base-vs-head combinations on real registry copies and real ciphertext:
  - 3,136 identical;
  - 16 intended releases, all asserted correct;
  - 208 no-release differences: 200 are earlier, safer refusals of invalid input, and 8 are the M1 stale-bytes refusal.
- `git status`: clean.

---

## Dispositions (elephant)

PASS: no blocking finding is open, and nothing was rejected.

- **M1 and M2, fixed.** These are documentation only. `docs/designs/registry-pending-promotion.md` now opens the addendum with a "Current rule" subsection, which is authoritative and states both candidate-path exceptions to base. The earlier paragraphs are kept under "History".
- **N3: documented** in the Current rule (malformed or `statement_sha256`-less rows authenticate nothing).
- **N1 and N2: accepted as-is.**
- **Head after this review.** It differs from the reviewed 48b8e3c only in `docs/` (the design and this file). `factory/` and `tests/` are byte-identical to 48b8e3c.
- **Murphy row `new-registry-pending-promotion-1`: left open,** as the review recommends.
