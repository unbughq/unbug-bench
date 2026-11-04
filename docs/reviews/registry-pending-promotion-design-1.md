# Design review: `docs/designs/registry-pending-promotion.md` (Mode: REVIEW)

Reviewer: fresh goldfish (agent a6519228c88c05e85, model opus), personas zoom_out, design_critic,
implementation_readiness; standards heilmeier + implementation-readiness. Reviewed commit 7ead583.
Verbatim reply follows; dispositions at the end.

I reviewed the design as the zoom_out, design_critic and implementation_readiness goldfish, against `docs/ENGINEERING.md`, Murphy row 7, `heilmeier-standard.md`, `implementation-readiness-standard.md` and `zoom-out-standard.md`. Code read: `factory/registry.py` at 7ead583 and its diff from dd81ff8, `factory/statement_round.py` (`prepare`, `prepare_restore`, `same_worker_handoff`), `factory/admission.py:registry_snapshot`, `factory/run.py:reselect_candidate`, `tests/factory/test_registry_promotion.py`, and the retained `sealed/statement-registry/registry.json`. I ran no test suites.

## What holds

- **Problem is real.** The design's account (lines 3–10) matches the code. `prepare` imports every non-candidate statement as history (`statement_round.py:91-96`). A later `reserve` on that case hits the early-return branch (`registry.py:67-76`), so `complete` stays `false` and `export` refuses it (`registry.py:140-141`). The retained registry has 41 entries; 37 are `complete=false`, status `completed`, `statement_sha256=None`. That matches "37 historical-only entries".
- **Placement and size are right.** The fix is about 10 lines in the one shared function every caller goes through, under the existing lock. It adds no status, file or caller change. Nothing is over-engineered and no YAGNI issue.
- **Readiness.** The change section (lines 12–19) states the promotion condition, which ciphertext is kept, what is recomputed and the `replace_rejected` adjustment precisely enough to implement without design choices. The code matches it.
- **Required sections.** `ENGINEERING.md` §1 asks for problem, change, deletes, tests and Murphy rows. All five are present.

## Blocking findings

**B1. The design drops half of row 7's prescribed fix without saying why, and leaves a sibling failure in the same import path.**
- **Affected scope:** design lines 12–19 and 31–32; `docs/murphy-register.md:19`; `factory/statement_round.py:91-96`.
- **Finding:** Row 7's Fix has two parts: "Import only genuinely historical cases. Promote a pending candidate through one locked reservation operation…". The design does only the second part. It accepts the root cause — `prepare` still imports every pending candidate as history — and patches `reserve` to tolerate it. Line 31 still says "Row 7: implemented".
- **Why it matters:** Keeping pending candidates in history may be deliberate. Two things need it today:
  - the registry docstring says "Later workers must consider earlier pending candidates too" (`registry.py:3-4`);
  - `same_worker_handoff` requires every history statement to be in the attestation (`statement_round.py:300`).

  The design never says this, so a fresh reader cannot tell whether the deviation is intended.
- **Sibling failure, same root cause, left as is:** suppose case Y reserved c1 (complete, `screening`). Y then rejects c1 and reselects c2 (`run.py:1710-1740`), and stops `statement-ready` with `sealed/Y.statement.age` = c2. Before Y's own handoff runs, another wave X calls `prepare`. That call does `import_historical(Y, c2, digest=c2)`. The previous entry is not released, its digest c1 ≠ c2, and the ciphertext differs, so it raises "case already reserved with different content" (`registry.py:74-75`). The whole of X's wave fails. Here an "import as history" of a pending candidate stops another case's admission. It is the same mechanism as row 7, and the design neither covers it nor files it as a `new-<topic>-<n>` row (`ENGINEERING.md` §2).
- **Recommendation:** Either:
  - add a short rationale for keeping pending candidates in history, and state that row 7's "import only genuinely historical" part is superseded; or
  - make `import_historical` a no-op when the existing entry is a non-released `complete` reservation.

  In either case, cover the reselected-candidate import collision with a test or name it as a new row.

**B2. Promotion creates mutual predecessors. The design's "screening is untouched" claim is unbacked, and the test locks the cycle in.**
- **Affected scope:** design lines 15–17 and 22–23; `registry.py:79-80`; `tests/factory/test_registry_promotion.py:41,58`.
- **Finding:** The registry's invariant is one-way: "each worker screens against all earlier reservations" (`registry.py:3`). Under this design it breaks:
  - Wave X imports pending Y as history, so X's `statements` contain Y (`registry.py:79-80` includes historical entries).
  - When Y is promoted, its predecessors are "recomputed from all non-released entries", so Y's `statements` contain X.
  - X and Y now screen against each other. The test confirms it: `case-pa ∈ pb.statements` (`test_registry_promotion.py:41`) while pa's `statements` already hold pb and pc (line 38). The pb/pc check uses a weak `or` (line 58) and actually passes with both directions present.
- **Consequence:** If X and Y are near-duplicates, each worker's dedup rejects its own candidate against the other, so both lose the slot. Each pays a reselection writer round and spends a candidate attempt against the per-case limit (`run.py:1714-1719`). This can exhaust a case. Under the old one-way ordering, one of the two would have survived.
- **The design can't just recompute predecessors as "earlier entries only".** `same_worker_handoff` requires Y's attestation to contain all collected history, including X (`statement_round.py:300`).
- **Recommendation:** The design must take a position:
  - **Accept it:** argue that over-rejection is the safe direction for secrecy, and that the candidate-attempt cost is acceptable. Then fix the test to assert both directions explicitly, not with `or`.
  - **Or break the tie deterministically:** for example, entries that already screened against Y keep precedence, and Y's dedup is told that X screened against Y first, or only one side of a mutual pair rejects. If the tie is broken, name the component that enforces it.

## Nits

**N1. A missing stored object during promotion writes mismatched bytes.**
`registry.py:66` sets `digest = previous["cipher_sha256"]`. If that object file is missing, lines 89–93 then write the caller's freshly sealed `data` under the stored digest's name. When promotion matched on statement digest only, those bytes hash differently, which leaves a corrupt object for every later export. The design says "keeps the stored ciphertext" (line 15) but does not say what happens when it is absent. It should require a refusal (raise "registry object corrupted/missing") rather than a write. The likelihood is low, since `import_historical` always writes the object.

**N2. The tests do not go through the real caller.**
The test simulates `prepare` with a `history()` helper (`test_registry_promotion.py:32-34`), using authored case IDs and digests over real ciphertext. Row 7's evidence cites `statement_round.py:80`, `:91`, `:103`. Driving `statement_round.prepare` (or `prepare_restore`) for two interleaved candidate waves would prove the row end to end, and would also exercise the `same_worker_handoff` superset check at `statement_round.py:300`. The design also does not list cases for the B1 sibling or for a resealed ciphertext with a known digest.

**N3. Heilmeier gaps.**
- No risks section. B2 belongs there.
- No note on the existing live registry. All 37 retained historical entries have `statement_sha256=None`, so any of them can only be promoted if the candidate's ciphertext is byte-identical to the imported one. A reseal by age (fresh randomness) would still raise "different content". The design should say whether that matters for real pending candidates. New imports from `statement-ready` cards always carry a digest, so it may be moot.
- Cost and timeline: trivially small, but unstated.

**N4. Murphy row wording.**
Lines 31–32 say "implemented and tested here; not live-proven", while `ENGINEERING.md` §2 expects the elephant to close a row in the fix commit once a real-artifact test proves it. The design should state plainly "closes: none", and name the test or live evidence that would close row 7.

**N5. Pre-existing, optional.**
`replace_rejected` reads `registry.json` without the lock (`registry.py:104-105`) and then calls `reserve`. The promotion change does not make this worse. It is noted only because the design leans on that function's "complete" check.

## Verdict

**FAIL.** Two blocking findings are open:
- **B1:** the design departs from row 7's prescribed fix without a rationale, and leaves the reselected-candidate import collision unaddressed.
- **B2:** the mutual-predecessor cycle and its double-rejection consequence are not acknowledged or resolved.

The change itself is small, well placed and readable. Both blockers can be resolved with design text plus a test, and B2 may not need any extra code.

---

## Dispositions (elephant, commit 99386c5)

Nothing rejected; both blockers resolved by the reviewer's own stated options.
- B1: fixed by design text: rationale for keeping the import side, row 7 first sentence superseded, the
  reselected-candidate import collision named as `new-registry-pending-promotion-1` (not fixed here).
- B2: fixed by taking the "accept" position in the design (over-rejection is the safe direction; B could not
  be admitted at all before); the weak `or` assertion replaced by explicit both-direction assertions.
- N1: fixed (`promote and not obj.exists()` raises "registry object corrupted"; test added).
- N2: fixed (`test_prepare_promotes_other_waves_pending_candidate` drives `statement_round.prepare` twice).
  Resealed-with-known-digest case covered by `test_promotion_keeps_stored_ciphertext`.
- N3: the legacy None-digest entries need byte-identical ciphertext; documented behaviour, unchanged
  (new imports from cards carry a digest). N4: design now states what closes the row. N5: pre-existing, untouched.
