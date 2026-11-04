# Goldfish diff review 2: `271f4a87..5cc9d9d1` (reselection between history snapshot and handoff)

Reviewer: fresh goldfish (agent a35e25798ee25f608, model opus), personas zoom_out and
implementation_readiness, Mode: REVIEW. Verbatim reply follows; dispositions at the end.

# Goldfish review (Mode: REVIEW): diff 271f4a87..5cc9d9d1, checked against the registry-pending-promotion Addendum and docs/ENGINEERING.md

**Verdict: PASS.** I found no blocking issues. The two Major findings below are follow-ups I recommend, not merge blockers.

**What I ran**
- `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py`: 8 tests, OK.
- `python3 -B tests/factory/test_statement_round.py`: 18 tests, OK.
- A read-only replay of the new decision logic over the real retained `sealed/` cards and `sealed/statement-registry/registry.json`. The registry is at revision 50 with 41 entries: 37 are historical-only with no digest, 3 are complete and screening, 1 is released.

## Truth table: `replace_rejected`, old vs new (factory/registry.py:104-115)

All rows assume the previous entry is not released and its digest differs from the new one. If the digests are equal, or the entry is released or absent, both versions go straight to `reserve`.

| Previous entry | Old (271f4a87) | New |
|---|---|---|
| complete, screening/building, old digest in rejected | release, then `reserve` | same |
| complete, screening/building, old digest not in rejected | raise | raise |
| complete, completed/known_public, any rejected list | raise | raise |
| historical-only, digest None | skip to `reserve` (promote by cipher, or raise) | same, because the `(complete or old is not None)` guard is false |
| historical-only, known digest, not in rejected | skip to `reserve`, which raises "different content" | raises earlier with the same message |
| historical-only, known digest, in rejected | skip to `reserve`, which raises | **release, then `reserve`** (the intended change) |

- A complete entry always has a 64-hex digest, because `reserve` rejects None unless `historical`. So the `old is None` part of the raise condition only matters for historical-only entries, and those cannot reach that branch.
- `rejected` can contain None (a row without `statement_sha256`), but a None old digest is excluded before the membership test. A None digest never authenticates a release.

## Silent acceptance and dropped screening

- **Mismatched content is still refused.** Every release requires the old digest to appear in the reselecting case's own card. Everything after the release goes through the locked `reserve`, which re-checks digest and cipher. I found no path that stores c2 without either a fresh reservation or a "different content" raise.
- **A candidate leaves screening only when its own card rejects it.** Release happens only when the old digest is in the card's `rejected_candidates`. That list is written only by `run.reselect_candidate` (factory/run.py:1713-1716), as dicts, with at most 3 rows (`MAX_CANDIDATES=3`).
- **The release cannot hit a running admission.**
  - The Y card that names c1 rejected only reaches the coordinator's sealed directory after a verified stop: `coordinator_inventory` checks `sealed/DONE`, that `run.py` is not running, and that `terminal_stop` is statement-ready. So Y is not screening c1 when another wave releases it.
  - The release is exactly what Y's own handoff would do.
  - Y's later handoff promotes the historical c2: same identity, fresh token, recomputed predecessors. That matches the outcome of the direct path.
- **Other workers' snapshots are unharmed.** Exports are copies and `objects/` is never pruned. Earlier snapshots keep c1 and are not retrofitted, which the Addendum states. Symmetry holds because Y's new reservation screens against them.

## Legacy digestless cards

- `statement_round.py:99-100` calls `import_historical(case, ct)` when the digest is None. That is the same call the parent made (`statement_sha256=None`).
- My replay over the real retained artifacts: every one of the 37 sealed `case-*.statement.age` files has a digestless card with no `rejected_candidates`. All 37 take the `import_historical` path, so their behaviour is unchanged.

## Findings

### Major 1 (non-blocking): the stated "own handoff from historical-only" fix has no test
- **Where:** tests/factory/test_registry_promotion.py:108-125, factory/registry.py:110-114.
- **What the Addendum claims:** "Y's own handoff fails the same way when c1 is historical-only". The fix is the candidate-path (`historical=False`) release of a historical-only entry with a known digest.
- **What the test actually does:** in the "history" subtest, X's wave (line 119) always runs before Y's handoff (line 121). So Y's handoff sees c2 already stored and takes the promotion path. The branch "Y's handoff directly sees c1 historical-only and releases it" never runs.
- **The code itself is correct.** `transition` accepts the completed historical entry's token, and `reserve` then makes a fresh complete reservation. Only the proof is missing.
- **Suggested fix:** add a third subtest that runs `wave1` with c1 as history, then Y's handoff `wave(..., c2, d2, [d1], y_candidate=True)`, with no X wave in between.

### Major 2 (non-blocking): the unlocked read adds a new spurious-failure race on the history path
- **Where:** factory/registry.py:106-114.
- **Problem:** `replace_rejected` decides outside the lock, then runs `transition` and `reserve` under two separate lock acquisitions.
- **Example:** X reads c1 as screening. Concurrently, Y's handoff (or another wave) releases c1 and reserves c2. X's `transition(R1)` then raises "stale reservation" and X's whole wave fails.
- **Before:** the parent history path was a single locked `reserve(historical, d2)` and would have succeeded here.
- **Every outcome is still safe:** the result is a stale-reservation or "different content" error, never silent acceptance.
- **Why it matters:** it is a new pit stop on the history path, which now runs for every wave. ENGINEERING.md expects 24 waves in parallel, and its design rules ask for fewer pit stops.
- **Context:** the same pattern already existed on the candidate path.
- **Suggested fix:** move the decision under the registry lock, or retry once on "stale reservation".

### Nit 1: validation runs after the release
- **Where:** registry.py:114 then `reserve` at :49-53.
- **Problem:** the digest regex and the age-header check run only after `transition(..., "released")`.
- **Example:** a history card with a malformed `statement_sha256`, or a corrupt/non-age `case-py.statement.age`, releases c1 and then raises. Y then has nothing visible in the registry.
- **Impact:** small. The failing wave raises, and every later wave with that history raises too. But it is a durable side effect from a refused operation.
- **Fix:** validate the digest and ciphertext header before releasing.

### Nit 2: card parsing now applies to all history cards (statement_round.py:97-98)
- Every history card's `rejected_candidates` is now parsed, digestless ones included.
- A card with `rejected_candidates: null`, non-dict rows, or more than 3 rows now fails other waves. The parent ignored these.
- The writer never produces such cards, and no real retained card has the field, so this is a theoretical fragility only.

### Nit 3: slightly stricter refusal when ciphertext bytes match
- **Parent behaviour:** `reserve(historical)` returned the previous entry when the cipher bytes matched, even if the card's digest disagreed (registry.py:72).
- **Now:** a known, differing, unlisted previous digest raises first.
- **Impact:** this only matters for internally inconsistent cards (same bytes, different plaintext digest). Refusing is arguably more correct.

### Nit 4: legacy None-digest entries still cannot be replaced
- **Where:** registry.py:109 comment.
- **Problem:** a legacy None-digest historical entry whose case later reselects with new bytes still raises for every wave.
- **Why this is acceptable:** it is by design ("a None digest never matches").
- **Real data:** all 37 such entries are finished legacy cases, so the risk is theoretical. A one-line mention in the Addendum would help.

### Nit 5: real-artifacts coverage
- **What is real:** the tests use the real retained registry copy and real age ciphertext.
- **What is synthetic:** the Y cards and digests (`"1"*64`, `"2"*64`). No retained card has `statement_sha256` or `rejected_candidates`, so no real card exercises the new branch.
- **Real legacy cards:** no test runs `prepare` over the 37 retained legacy cards. My replay shows they take the unchanged path, but that is analysis, not a test.
- **Rule status:** ENGINEERING.md §4 forbids fixtures generated by the code under test. These cards are hand-authored, not generated by the code under test, so the rule is met in letter. Real-data proof is still pending, and the Addendum honestly says "not deployed or live-proven".

### Nit 6: Addendum test list is incomplete
- The test list leaves out the untested direct-handoff branch (see Major 1) and does not mention the history-path concurrency trade-off (see Major 2).

## Zoom-out
- The change is minimal and reuses `replace_rejected`. It adds no new helpers or abstractions, and it fixes the root cause in the shared registry rule instead of patching only the caller.
- The parent claim "fails on 271f4a87" is consistent with my reading: the parent's `wave2` calls `import_historical(case-py, c2, d2)`, sees previous d1, and raises. I did not check out the parent to confirm.

**Verdict: PASS.** I recommend the direct-handoff test from Major 1 before closing the Murphy row, plus a decision on the lock/retry in Major 2.

---

## Dispositions (elephant)

Nothing rejected. Fixed in the final head: Major 1 (`test_own_handoff_releases_reselected_historical_only_entry`),
Major 2 (retry once on "stale reservation"; decision stays unlocked), Nit 1 (digest and age-header validated
before any release; `test_malformed_input_refuses_before_releasing`), Nit 4 and Nit 6 (design follow-up
paragraph). Nit 2, 3: accepted as-is (writer never produces such cards; refusing inconsistent cards is intended).
Nit 5: card digests are authored because no retained card carries `statement_sha256`/`rejected_candidates`;
registry and ciphertext are real. The fix was tested only locally. Not deployed or live-proven.
