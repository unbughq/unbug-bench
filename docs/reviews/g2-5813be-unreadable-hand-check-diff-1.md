# Diff review 1: g2-5813be-unreadable-hand-check (goldfish)

**Reviewer:** a fresh goldfish (Claude Sonnet general-purpose subagent), read-only, given the diff 48e1263b..d71d375a,
the design (`docs/designs/g2-blocked-source.md`), the founder's ruling as relayed by the coordinator and the G2
reviewer's real findings for both 5813be rows. It was not given the elephant's conclusion.
The persona files were not in the worktree (`tools/egm/agents/` is untracked in the main checkout), so this round is a
direct read, not a persona run.

## Verbatim

VERDICT: PASS

I could not read the persona or standard files. `tools/egm/` does not exist in `/Users/bugsincode/Developer/unbug-bench-wt-5813be-g2`. Copies of the standard exist elsewhere on disk, but I did not use them. This review is a direct read of the diff and code, not a run under the zoom_out and implementation_readiness personas.

I ran `tests/factory/test_g2_blocked_source.py` with the command you gave: 14 tests, OK. The diff touches only `factory/run.py`, the design note, the test and the fixture. `factory/calibration.py`, `factory/gate_state.py` and `bin/claims.py` are untouched.

**Scope.** The code matches the approved ruling. In `g2_source_ruling` (`factory/run.py:2108-2136`) the new "unreadable" path needs all of these:
- The receipt is not an access failure and `retrieved_from` is `live` or `archive`.
- The answer is a dict with `resolved is False`, the row's URL, and fields that agree with the receipt.
- `same_bug is True` returns None before any ruling lookup, so a confirmed row can never be settled.
- A `not_needed` ruling is excluded by the final `(blocked or kind == 'hand_checked')` clause.
- A `resolved: true` answer, an answer for another URL, a disagreeing answer, and no answer all fail the `unreadable` test. A receipt with `retrieved_from: none` does too.
- The caller (`factory/run.py:2323`) already requires one unique matching ruling and sets `freshness_transport_pending` only when the receipt shows an access failure. A ruled row never sets it.

**Crashes.** I found no new crash path.
- `receipt.get` and `access_failure(receipt)` already ran on every flagged row before this change. A None receipt crashed before as well, and the caller guards the receipt count.
- The new `agrees()` call only runs once `receipt.get('retrieved_from')` is `live` or `archive` and the answer is a dict.
- `agrees()` indexes the receipt keys directly. The existing valid-answer path at `factory/run.py:2331` does the same, and runner receipts are always complete.

**Tests.** They prove it on the real rows. They load the real fixture entries for both 5813be rows and require the shipped rulings to clear them. They check `reports_this_bug: true` still confirms a match. They cover nine negative cases per row. The positive assertion would fail on the old predicate, because the receipt shows no access failure.

**Leak check.** The `page_says`, `ruling` and fixture text name no defect or fix. The fixture answers are verbatim reviewer text and carry no bug description.

**Interactions.** `factory/ordinary_freshness.py` `ruled()` and `stalled()` only treat `ruled_rows` as unread or unwalled, which is harmless for a 200 page. `tools/check-g2-rulings.py` passes the answer and receipt straight in and works unchanged.

Findings, all NIT:

1. NIT, `docs/designs/g2-blocked-source.md` (amendment, top paragraph and section 2): it says "left unresolved because it could not read it", but the code cannot tell why. Any `resolved: false` answer on a fetched page, matching URL and agreeing receipt qualifies. This includes an unresolved reason such as version applicability on a readable page. That is bounded by the per-URL, per-statement ruling and it fits what the founder approved. Fix: reword to "left unresolved (`resolved: false`)" and add "the code cannot distinguish unreadable from other unresolved reasons; the person who hand checked the URL is the safeguard".

2. NIT, `factory/run.py:2114`: `retrieved_from == 'archive'` is also accepted. A dead live page (404/410) with an archive copy that the reviewer left unresolved can be settled by a `hand_checked` ruling. The design says a dead page "keeps its existing unreachable rule", and the test only covers `retrieved_from: none`. Either state in the design that an archive-read page counts, or add a test for the archive case.

3. NIT, `factory/run.py:2115-2116`: the exclusion tests `same_bug is True` only. An unresolved answer with a non-bool `same_bug` such as `"true"` would pass as unconfirmed. This is the same as the existing access-failure path. Optional fix: require `answer.get('same_bug') in (None, False)` on the unreadable branch.

4. NIT, `tools/check-g2-rulings.py:7-9`: the docstring says MISMATCH means "the page was read". That is now only true for `not_needed` rulings and for a reviewer who read the page. Update the wording.

## What the elephant did

- **Nit 1, taken:** the design now says "left unresolved (`resolved: false`)" and that the hand check is the safeguard.
- **Nit 2, taken the narrow way:** the unreadable path now needs `retrieved_from: live`; an archive copy of a dead page keeps
  the unreachable rule. New negative case "dead page, archive copy"; widening the guard back to archive fails the test.
- **Nit 3, taken:** the unreadable path needs `same_bug` null or false; new negative case "same_bug not a bool"; removing
  the guard fails the test.
- **Nit 4, taken:** the tool docstring's MISMATCH wording updated (tools/ is not gate identity).
