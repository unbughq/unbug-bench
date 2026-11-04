# Goldfish diff review 11: `7de75d9...80558b2` (authenticated bytes, diff-10 Codex follow-up)

Reviewer: fresh goldfish with no history, run as a separate local `claude -p` process (model
claude-opus-5-5, the same model family as the writer, because no other family was available
to this job). It had read-only tools: Read, Grep, Glob, and git show/diff/log. Personas: zoom_out and
implementation_readiness. Standard: implementation-readiness-standard.md. Mode: REVIEW. Scope:
the diff `claude/registry-stale-history-final...HEAD` (7de75d9...80558b2) against the design's
"Authenticated bytes (diff-10, Codex)" paragraph. It was asked to check that the external finding
is closed, the four invariants (ciphertext preservation, rejection authentication, reservation
fencing, duplicate-screening visibility), the regressions' fail-before and pass-after, the
carve-out and the Murphy row. Its reply is reproduced verbatim below. The elephant's dispositions
follow it.

---

Static verification is done; writing the verdict. I couldn't run the tests here because execution needs approval in this session.

## Verdict: PASS

No blocking findings. I checked everything by reading the code, because the test runs (`python3 -B tests/factory/test_registry_promotion.py`) needed approval. Fail-before and pass-after are worked out by hand, not observed. The elephant still owes the full-suite run on HEAD (ENGINEERING.md §1 step 4).

### Check 1 — the external finding is closed
- **History path.** `factory/statement_round.py:94` reads the ciphertext once. `bound` is computed from those bytes (`:104`). The same bytes then go to `import_historical` (`:99`) and `replace_rejected` (`:108`).
- **Candidate path.** `:115` reads the bytes once. `:117-118` computes `bound` from them. `:119` passes them on.
- **Inside the registry.** `ciphertext_bytes` (`factory/registry.py:35-37`) passes `bytes` through unchanged. `replace_rejected` hands `data` to `reserve` on both exits (`registry.py:118`, `:138`).
- After authentication, no code reads the ciphertext path again. `search_receipt` reads only `*.search.age`, and `export` reads only digest-named objects.
- The bytes the release decision uses (`cipher`, `:119`), the bytes stored (`:98`) and the bytes the card bound are now the same object.
- **Candidate card.** It is still read once per decision. `bound` now also requires the card to name `digest` (`:117`), which closes the design-2 B1 double card read.

### Check 2 — the four invariants versus 7de75d9
- **Ciphertext preservation:** unchanged. Promotion still sets `digest = previous["cipher_sha256"]` (`registry.py:70-71`), and the same-digest return is unchanged (`:73-76`).
- **Rejection authentication:** the predicate at `registry.py:126-130` is unchanged. The only new condition is the candidate digest check at `statement_round.py:117`.
- **Reservation fencing:** the `transition(..., expect=(status, old, cipher_sha256))` call at `:133-134` is unchanged.
- **Duplicate screening:** the `earlier` predecessors (`:84-85`) are unchanged, and history imports still run for every non-candidate.
- **Other base behaviour:**
  - The CLI (`statement_round.py:384`) and `coordinator_inventory.py:156` still pass directories and paths.
  - `import_historical` still takes no digest when the card has none (`:98-99`).
  - Invalid input is still refused through `reserve` before any release (`registry.py:116-118`). Base also read the bytes first.
  - In every production caller, the candidate `digest` comes from the same card's `statement_sha256`:
    - `prepare_restore` (`:49`, `:75`);
    - `coordinator_inventory.py:147`;
    - the CLI's worker card (`:375`).
  - So the new condition changes nothing when no swap happens.

### Check 3 — fail-before / pass-after
- **`test_release_and_reserve_consume_the_authenticated_bytes`** (`tests/factory/test_registry_promotion.py:249`):
  - On 7de75d9, `bound` comes from the c2 read. Then the hook swaps in c3:
    - at entry to `replace_rejected`, the base `replace_rejected` reads c3, releases d1, and `reserve` stores c3;
    - at entry to `reserve`, the decision was made on c2 but `reserve` reads c3.
  - Either way the entry is d2/sha(c3), so the assertion `(d2, sha(c2))` fails in all 4 subtests.
  - The snapshot assertions also tell the cases apart: export resolves `case-py` through the entry's digest.
  - On HEAD the swap has no effect, so the test passes.
  - `assertEqual(swapped, ["case-py"])` proves the hook fired.
- **`test_candidate_card_must_name_the_offered_digest`** (`:283`):
  - On base, `bound` is true (G3 binds c3), d1 is in the rejected list and the entry is historical-only, so the entry is released and c3 is stored under d2. No error is raised, so the test fails.
  - On HEAD, `bound` is false (d3 ≠ d2). `reserve` sees d1 ≠ d2 and no promotion applies, so it raises "different content" and the entry is unchanged. The test passes.
- **Determinism:** both tests use a `mock.patch` hook or pre-built state. There are no threads and no sleeps.
- **Labels:** both carry the AUTHORED label and say they are not real-writer evidence and don't close the row (`:252-254`, `:285`).

### Check 4 — the carve-out and the Murphy row
- The "Left as is" bullet is accurate. With the ciphertext swapped alone after `prepare_restore`'s own check (`statement_round.py:71-73`), `bound` is false, so only a complete screening or building entry can be released. That entry takes the release base already had.
- With the card and ciphertext swapped together, the same base release happens, because `rejected` at `:113` is not gated on `bound`. The remaining check is the worker's own verification (`:69-70`).
- The bullet also says why the window is not closed: it would add a refusal for `coordinator_inventory.prepare_admission`, which is a base-behaviour decision. That scoping is right.
- `docs/murphy-register.md:93` (new-registry-pending-promotion-1) is not touched by the diff and stays `open`. That is correct, since there is no real-artifact test.

### Check 5 — existing pinned behaviours
- No existing candidate-path test uses a card whose `statement_sha256` differs from the offered digest while expecting a release:
  - `:210` (legacy card) still names d2 and still lacks a binding;
  - `test_statement_round.py` candidates have no card, so `bound` is false on both base and HEAD.
- Direct path-based calls still work through `ciphertext_bytes`, for example `test_registry_promotion.py:177`.
- The design's test count (21) matches the file.

### Findings
1. **NIT** — `factory/statement_round.py:113`: the candidate `rejected` list is still built from an unvalidated `card.get('rejected_candidates', [])`. The history path is stricter (`:105-106`: a list, at most 3 rows, all dicts). A non-dict row raises `AttributeError` rather than a refusal. This was in base too and is outside this diff's scope, but it is the same seam the carve-out names.
2. **NIT** — `tests/factory/test_registry_promotion.py:259-260`: on HEAD, the `replace_rejected` hook and the `reserve` hook both fire after the only read, so the two subtests behave the same on HEAD. Both still tell base apart, so this is fine. A comment saying they exist to pin the two base reopen points would help readers.
3. **NIT** — `factory/registry.py:142`: `search_receipt` still reads its path itself. The design says this is outside the finding. It is safe because `metadata.cipher_sha256 == digest` is checked on the same bytes, but a one-line comment there would stop a future reader from re-raising it.
4. **NIT (process)** — this review did not run the tests. ENGINEERING.md §1 step 4 still needs the full-suite run on the exact HEAD.

---

## Elephant dispositions

PASS, with no blocking finding open. The code at 80558b2 is the reviewed code, and only this record
was added after it.

- **The reviewer did not run the tests.** The elephant ran them, and observed fail-before and
  pass-after. On 7de75d9 code, the two new tests produce 5 failures: all 4 subtests of
  `test_release_and_reserve_consume_the_authenticated_bytes` store c3
  (`808a6a13…62cc`) under d2 where c2 (`fda346dc…ff3c`) was expected, and
  `test_candidate_card_must_name_the_offered_digest` fails with "ValueError not raised". On
  80558b2, both pass, and the whole file passes (21 tests). The full suite result is in the PR
  body.
- **N1, not taken (base, out of scope).** The candidate `rejected` list is unvalidated on base too.
  This record notes it for a later change. Changing it here would change base behaviour on the
  candidate path.
- **N2, not taken.** The two hook subtests pin the two separate reopen points on 7de75d9
  (`registry.py:109` and `:51`). They are meant to behave the same on HEAD.
- **N3, not taken.** `search_receipt` is out of scope, as the design says. It authenticates and
  stores the same read.
- **N4.** Addressed: the full suite was run on the final head.
