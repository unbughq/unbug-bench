> Renumbering note (2026-11-04, merge of factory-simplify into the follow-up branch): this file was
> published on `fix/registry-stale-history` (ecb31df) as `registry-pending-promotion-diff-3.md`. That name
> collides with factory-simplify's final review of the original row-7 fix, so it is renumbered here.
> The review text below is unchanged.

# Goldfish diff review 3: `271f4a87..a754adcb` (final reselection change as a whole)

Reviewer: fresh goldfish (agent a52cf92c4c2f50c4f, model opus), Mode: REVIEW. Verbatim reply follows.

I found no blocking issues in the final change (`271f4a87..a754adcb`). Two tests, the late validation and the history-path race are addressed. Five nits remain, none of which blocks.

**Verdict: PASS**

**Tests I ran**
- `BENCH="$PWD" python3 -B tests/factory/test_registry_promotion.py`: 10 tests, OK.
- `python3 -B tests/factory/test_statement_round.py`: 18 tests, OK.
- I did not run the full suite. ENGINEERING.md §1 step 4 requires it on the exact head handed back, so the elephant should confirm it has a run on `a754adcb`.

## The early validation (`factory/registry.py:106-108`)

It only adds a refusal before any release; it never lets through anything that used to be refused. There are only two production callers: `statement_round.py:102` (history, `historical=True`) and `:109` (candidate). No code reads the error messages; a grep for "different content", "invalid statement digest" and "stale reservation" finds no consumers outside `registry.py`.

| Input | Before (`271f4a87`) | Now |
|---|---|---|
| Candidate path, ciphertext without an age header | could release c1 and then fail in `reserve` | `reserve` raises "statement must be age ciphertext", nothing released |
| Malformed digest (not None) | could release c1 and then fail in `reserve` | "invalid statement digest", nothing released |
| Ciphertext file missing or unreadable | `FileNotFoundError` from `reserve` | `FileNotFoundError` from line 106, same type, nothing released |
| Digest None, `historical=False` | "different content" (or release, then "invalid digest") | "invalid statement digest", still a `ValueError`; only the message changes, and no caller passes this |
| Digest None, `historical=True` | not reachable from `prepare` | treated exactly like `import_historical` |

On the last row: under `5cc9d9d1` a None digest could have released a screening entry whose old digest was listed as rejected. The new branch closes that, so it is strictly safer.

## The retry loop (`factory/registry.py:109-123`)

The loop is correct and always ends:
- Every pass ends in `return`, `raise`, or `continue`.
- `continue` is possible only on attempt 0. On attempt 1, `if attempt or ...` re-raises, so the function never falls off the loop and returns None.
- Only "stale reservation" is retried; any other `ValueError` is re-raised.
- After a stale transition, the state is read again:
  - If the entry has been released, `reserve` runs.
  - If c2 is now stored (`old == statement_sha256`), `reserve` returns the existing entry or promotes it.
  - If an unlisted digest has taken its place, it raises "different content", which is the correct refusal.
- One retry is enough. Once c2 is stored, no other caller transitions the entry again, so a third change inside the window would need inconsistent cards.

I traced the concurrent cases and each ends in success or a refusal:
- Two waves X1 and X2 both importing Y's c2.
- Y's own handoff racing an X history import.
- The same race in the other order.

## Regressions versus `271f4a87`

None found. History imports with a digest now go through `replace_rejected(..., historical=True)`.
- With no previous entry, or with the digest unchanged, the result is the same as `import_historical(case, ct, digest)`.
- A legacy historical entry with no digest still goes straight to `reserve`, so cipher-match returns or refusals are unchanged.
- Complete entries with status `completed` or `known_public` still raise.

The register row 7 promotion path is untouched.

## Nits (none blocking)

1. **The comment at `registry.py:108` is inaccurate for one input.** "refuses before any release" is wrong for digest None with `historical=True` and a valid age file: that call succeeds as a history import. No caller does this, so only the wording needs fixing.
2. **The retry has no test.** None of the 10 tests makes `transition` raise "stale reservation" on attempt 0. A small test that patches `Registry.transition` to raise once and checks the reselection then succeeds would prove the branch and its single-attempt limit.
3. **The age-header check is repeated.** The same tuple appears at `registry.py:52`, `:107` and `:129`, and in `statement_round.py`. A shared module constant would keep them from drifting. This is optional.
4. **A race exists that is older than this change.** The unlocked decision does not re-check the status when `transition` runs. If the same token moved from screening to completed in between, it would be released. Reaching that needs Y to complete c1 while its own card lists c1 as rejected, which is contradictory, so it is not reachable in practice. The history path now runs this code for every wave, so it is worth a sentence in the design.
5. **The Murphy row is not in the register.** `new-registry-pending-promotion-1` is named in the addendum but missing from `docs/murphy-register.md`. That matches "register untouched / root owns it", but root needs to add the row (and close it with `tests/factory/test_registry_promotion.py`) at merge. The card digests in that test are hand-written; the registry and ciphertext are real.

## Zoom-out

The change is small and goes through the one shared function both callers use, so it fixes the cause rather than the symptom. It adds no new abstractions. The design addendum (`docs/designs/registry-pending-promotion.md:58-91`) matches the code and states the limits honestly: not deployed, not live-proven, and legacy entries without a digest cannot be replaced.

---

## Dispositions (elephant)

Nothing rejected. Nit 1 fixed (comment reworded). Nit 2 fixed (`test_stale_reservation_is_retried_once`: one
retry succeeds, a second stale failure surfaces after exactly two attempts). Nit 3 skipped (optional, existing
pattern). Nit 4 accepted: unreachable with consistent cards, pre-existing pattern. Nit 5: root owns the register.
The final head (this commit) differs from the reviewed a754adcb only by the comment, the retry test and this file.
