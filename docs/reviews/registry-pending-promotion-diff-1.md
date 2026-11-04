# Goldfish diff review: registry pending promotion (`dd81ff8..7ead583`)

Reviewer: fresh goldfish (agent a8e7a44da7e0a06e9, model opus), personas zoom_out and
implementation_readiness. Verbatim reply follows; dispositions at the end.

Mode: REVIEW. Personas: zoom_out and implementation_readiness. Design: `docs/designs/registry-pending-promotion.md`. Test run: `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py` ran 3 tests, all OK.

## Summary of what I checked

- **Promotion logic (`factory/registry.py:62-66`) is correct.** Promotion needs all of these:
  - the call is non-historical;
  - the previous entry is not released;
  - the previous entry has `complete=false`;
  - either the statement digest matches the stored one, or the stored statement digest is None and the ciphertext digest matches.

  A None==None match can't happen, because line 49 requires a 64-hex digest whenever `historical=False`. Promotion then goes through the existing new-reservation path (lines 77-97). That path checks `expected_revision`, recomputes `earlier` from every non-released entry, issues a fresh token, and sets `complete=True` and status `screening`. This matches the design.
- **Ciphertext binding is kept.** Line 66 (`digest = previous["cipher_sha256"]`) keeps the stored object. Any candidate that reserved earlier recorded B's stored digest in its `statements`, and that stays consistent after B is promoted.
- **Duplicate screening is not weakened.** The promoted entry's `statements` covers every non-released entry, and B now sees candidates reserved after its history import. The test checks this: `assertIn("case-pa", entry["statements"])`. Screening against B by earlier candidates is unchanged, because B was already a non-released entry.
- **Refusals still hold:**
  - A mismatched statement, or an unknown digest with different ciphertext, falls to line 74 and raises.
  - A `historical=True` call never promotes.
  - A historical-only entry that nobody reserves still fails `export` (line 140).
  - A released entry behaves as before (re-reservable; export refuses).
  - A stale `expected_revision` now also refuses on the promotion path (line 77). That is new and correct.
- **Idempotence holds.** Once an entry is complete, a replay or a re-import goes through line 68 and returns the same entry unchanged.
- **Locking: `replace_rejected` reading state outside the lock does not matter.** The promotion decision is made inside `reserve`, under the exclusive lock, on state it re-reads there. The unlocked read only decides whether to release a *complete* previous entry. Every race I could find fails closed rather than wrongly accepting:
  - If the entry became complete in between with a different digest, the release is skipped and `reserve` raises.
  - If the token went stale, `transition` re-checks the reservation under the lock and raises "stale reservation".
  - If the entry became complete with the same digest, `reserve` returns it.

  The release and reserve steps are also not atomic, but that predates this branch.
- **Parent behaviour (by reasoning, not run).** The parent was not run, because I was limited to the one command. On the parent, `replace_rejected("case-pb", same digest)` skips the release branch, and `reserve` returns the entry with `complete=False` at the old lines 60-62. `export` then raises "historical-only". So the main test fails on the parent, as the design says.

## Findings

### Major (non-blocking for this merge; blocking if row 7 is closed with this test)

**M1. The test does not use the code path the row names.**
- Scope: `tests/factory/test_registry_promotion.py:32-34`; Murphy register row 7, which cites `factory/statement_round.py:80`, `:91`, `:103`.
- The row describes a failure in `statement_round.prepare`. The test never calls `prepare`. It re-implements `prepare`'s history loop in a helper (`history()`, with the comment "what statement_round.prepare does for non-candidates") and calls `replace_rejected` directly.
- The registry state and the ciphertext are real (a copy of `sealed/statement-registry`, which has 41 entries, 37 of them historical with `statement_sha256=None`, plus real `sealed/case-*.statement.age` files). That is enough to prove the registry half.
- It does not prove the row end to end. For example, a change to how `prepare` picks the history digest from `history/<case>.scorecard.json`, or to its candidate/non-candidate split, would not be caught.
- ENGINEERING section 2 says "the diff goldfish checks that the test really proves the row". Before row 7 is set to `closed`, add a test that drives `statement_round.prepare` twice with `history_sealed`: handoff A with candidate pa, which imports pb as history, then handoff B with candidate pb. Use the real registry copy and real `.age` files, and give pb a scorecard carrying `statement_sha256` the way real pending cards do.

**M2. The design is unclear about whether row 7 closes.**
- Scope: design, "Murphy rows" paragraph (lines 31-32); commit subject "(Murphy 7)".
- The design says "implemented and tested here; not live-proven. The register is not edited by this branch (root owns it)."
- ENGINEERING section 2 says a row closes with a real-artifact test, and that the elephant sets `closed` and `Closed by` *in the same commit as the fix*. Live proof is not the bar.
- As written, nobody knows whether to close row 7 at merge. The elephant or root should decide explicitly: either the row stays open, with a stated reason such as "needs a `prepare`-level test", or it closes with a named test after M1 is fixed.

**M3. The kept-ciphertext line is not tested.**
- Scope: `factory/registry.py:66`; test lines 29 and 57.
- `self.ct[c]` is the same file for both the history import and the promotion, so the stored digest equals `sha256(data)`. If line 66 were deleted, which would bind the entry to the new bytes, every test would still pass.
- In real use, age re-seals produce fresh bytes (see the comment at lines 69-70). This is exactly the "exact ciphertext binding" property.
- Fix: promote pb with a different real `.age` file and the same statement digest. Then assert that `entry["cipher_sha256"]` is still the historical digest and that the exported `case-pb` bytes are unchanged in pa's snapshot and on the board.

### Nits

- **N1. One assertion is always true.** At test line 60, `"case-pc" in seen[0] or "case-pb" in seen[1]` cannot fail. pb and pc are both non-released historical entries before either is promoted, so each is in the other's `statements` whatever the thread order. The comment "the later promotion sees the earlier" claims an ordering it doesn't check. Delete the assertion or make it meaningful.
- **N2. The re-import after promotion is not tested.** The comment at line 40 says "must not demote or change B", but that call runs while B is still historical. The case worth testing is `import_historical(pb)` after promotion: the entry should stay `complete=True` with the same `reservation`. The code is correct here (line 68), but the test doesn't check it. Also nothing asserts that the history-import token is stale after promotion, i.e. that `transition(pb, old_token, ...)` raises.
- **N3. The promotion path can write mismatched bytes into the object store.** At `factory/registry.py:86-93`, after line 66 swaps `digest`, a missing object would be written from `data` (the new bytes) under the old digest's name. `export` and `export_board` would detect it later, so it fails closed. It is also unreachable on the real handoff path, because `statement_round.py` checks that every non-released entry's object exists and verifies. Still, an `assert` or a raise on `promote and not obj.exists()` would be cleaner than poisoning the store.
- **N4. The status guard is looser than needed.** Line 62 promotes any non-released incomplete entry. Incomplete entries only come from `import_historical`, which sets status `completed`. If one were moved by the CLI to `known_public` or `building`, it would be revived as `screening`. `previous["status"] == "completed"` would state the intent exactly. No in-repo caller transitions historical entries, so this is low risk.
- **N5. The design doesn't explain why it skips half of the row's fix (zoom_out, root problem).** Row 7's suggested fix also says "Import only genuinely historical cases." The design takes only the promotion half. That is the right call: the module docstring at `registry.py:3-4` needs pending candidates in the registry so later workers screen against them, and promotion is the smaller fix that keeps that. One sentence in the design saying so would stop a later reader from "fixing" the import side.
- **N6. A remaining gap, not a regression.** Suppose a pending candidate was imported as history under an *old* statement digest and has since re-selected (a rejected candidate). It still raises "different content" in `reserve`, and may also break the history import itself. The parent raised in this case too, and the design states it ("historical-only mismatches still raise"). Record it as an open sub-case of row 7, or as a new `new-registry-pending-promotion-1` row, if it is plausible in real runs.

### Zoom-out and readiness

- The fix is the right size, in the right place, adds nothing new, and puts nothing in the wrong layer. One flag inside the existing locked operation is the simplest fix that addresses the root cause, and it reuses the new-reservation path rather than adding a second one.
- The design is actionable and leaves no design choices open for the code. Its one gap is the row-status decision in M2.

## Verdict

**PASS** for merging the code. No blocking finding is open: the promotion logic, the ciphertext binding, the duplicate screening, the refusals, idempotence and locking are all sound.

Condition: row 7 must **not** be set to `closed` with `tests/factory/test_registry_promotion.py` as it stands. Before the row closes, M1 (a `prepare`-driven real-artifact test) and M3 (a test that the stored ciphertext is kept) need fixing, and M2 needs an explicit decision. Recording this test as `Closed by` without those changes would be a blocking finding under ENGINEERING section 2.

---

## Dispositions (elephant, commit 99386c5)

No blocking finding; nothing rejected.
- M1 fixed: `test_prepare_promotes_other_waves_pending_candidate` drives `statement_round.prepare` for two waves.
- M2 decided: design says root may close row 7 citing the test file at merge; this branch leaves the register alone.
- M3 fixed: `test_promotion_keeps_stored_ciphertext` promotes with different real age bytes.
- N1 fixed (explicit both-direction assertions). N2 fixed (post-promotion re-import keeps reservation).
- N3 fixed (missing stored object refuses). N4 fixed (`status == "completed"`). N5 fixed (design rationale).
- N6 recorded as `new-registry-pending-promotion-1` in the design, not fixed.
