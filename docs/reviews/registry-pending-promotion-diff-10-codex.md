# External diff review 10 (Codex): `fbca505...7de75d9` (stale-history/reselection, PR #3)

Reviewer: a fresh, independent reviewer from a different model family (Codex), relayed by the
parent agent. It reviewed `7de75d9a50f35b203cf2dff4d5d484e0a993c2e1` against
`fbca505894bda2b5ac6042994ed46a507e678925` read-only and ran no tests. Its reply is reproduced
verbatim below. The elephant's response follows it.

---

> FAIL — reviewed `7de75d9a50f35b203cf2dff4d5d484e0a993c2e1` against `fbca505894bda2b5ac6042994ed46a507e678925`.
>
> Blocking finding: `factory/statement_round.py:103` authenticates one read of the ciphertext, but `factory/registry.py:109` and `:132` reopen its mutable path. Concurrent collection can replace that file (`factory/transfer.py:98`) between reads, causing the new history path to release d1 and store c3 under d2 although the card authenticated c2. Registry transition fencing does not protect the input file. Preserve and reserve the authenticated bytes, or use an immutable verified snapshot throughout.
>
> The existing candidate-path limitation is preexisting; extending this exposure to historical-only releases is introduced here. Other reviewed fencing, preservation and non-release behavior showed no blocking defect. Authored cards over retained ciphertext do not establish real writer reselection evidence; leaving the Murphy row open is appropriate.
>
> Read-only review; no tests run.

---

## Elephant response

**Blocking finding: accepted and fixed** on `claude/registry-authenticated-bytes`, a dependent
branch whose base is `claude/registry-stale-history-final`. Nothing was rejected.

**Confirmed interleaving (at 7de75d9).**
- **Setup.** Y's card binds c2 under d2 and lists d1 as rejected. The registry holds d1/c1 as
  historical-only, status `completed`.
- **Step 1.** `statement_round.prepare` hashes one read of `case-py.statement.age` (c2)
  (`statement_round.py:103`, or `:114` on the candidate path), so `bound=True`.
- **Step 2.** Collection's `os.replace(partial, destination)` (`transfer.py:98`) swaps in c3.
- **Step 3.** `Registry.replace_rejected` reopens the path (`registry.py:109`) and reads c3. Since
  c3 differs from c1, `authenticated` is true and d1 is released.
- **Step 4.** `reserve` (called at `registry.py:132`) reopens the path again (`registry.py:51`) and
  stores c3 under d2.

A swap between steps 3 and 4 has the same result. The candidate path reaches the same release,
because diff-7 made `bound` release a historical-only entry there too.

**Fix.**
- `prepare` reads each ciphertext once per case and computes `bound` from those bytes. It passes
  the bytes on to `import_historical`, `replace_rejected` and `reserve`.
- The shared helper `registry.ciphertext_bytes` passes bytes through unchanged and reads a path
  exactly once. `replace_rejected` hands its bytes on to `reserve`.
- Design-2 found that the candidate card is also read twice. Candidate `bound` therefore also
  requires the card that `prepare` read to name the offered digest.

**Regression.**
- `test_release_and_reserve_consume_the_authenticated_bytes` (AUTHORED hook) covers the history
  and candidate paths, swapping the file with `os.replace` at the entry to `replace_rejected` and
  to `reserve`.
- `test_candidate_card_must_name_the_offered_digest` (AUTHORED state) covers the swapped card.
- Both fail on 7de75d9 and pass after the fix.

**Preexisting, left as is.** A complete screening or building candidate entry still takes base's
unbound release when the ciphertext (or the card and ciphertext together) is swapped after
`prepare_restore`'s own check. See the design's "Left as is" bullet.

**Murphy.** new-registry-pending-promotion-1 stays open, as the reviewer said. Authored cards over
retained ciphertext are not real-writer reselection evidence.
