# Goldfish review 3: docs/designs/status.md

Reviewer: fresh Claude Sonnet subagent, personas zoom_out + design_critic, Mode: REVIEW, read-only. Verbatim.

**Third pass: FAIL.** One BLOCKING finding, and the fix is one line. The first-pass and second-pass blockers (live source, field names, stuck-rule contradiction, card-versus-journal precedence) are resolved. The remaining design is simple enough and computable.

1. **BLOCKING: `gates.G12 == "pass"` does not mean a case passed.**
   - `factory/run.py` (around line 2619) sets `G12` to `"pass"` whenever the seal step succeeds, even if an earlier gate failed.
   - In the real cards, `G12` is `"pass"` on 86 cards, and several of those also have `failed_gate` set. Examples: `{'G1': 'fail', 'G12': 'pass'}` with `failed_gate: G1`, and `{'G1': 'pass', 'G2': 'fail', 'G12': 'pass'}` with `failed_gate: G2`.
   - "Sealed X / N" would therefore count rejected cases as sealed, and the founder's headline number would be too high.
   - Define sealed as `gates.G12 == "pass"` and `failed_gate` is null and the case is not stopped. The scorecard text code uses `card.get("sha256")` for G12 the same loose way, so don't borrow from it.
   - Show rejected cases (`failed_gate` set) as their own count, separate from sealed.
   - Confirm that the "known stops" list includes "rejected at G*".

2. **NIT: say which card field is the generation.**
   - `restore_ledger.authenticate` ties the generation to the card's `sha256` (`public_card.get("sha256") == generation`). Write "card `sha256` equals the journal's latest collected generation" so the check is exact.

3. **NIT: running cases show stale money and rounds.**
   - Spend, rounds and "near limit" come from the card, which exists only from the last collection. A running case is judged on old numbers.
   - The doc could say "as of the last card" next to the spend, or accept this as a known limit. The 5-hour rule still catches a stuck run.

4. **NIT: "waiting" is counted in the summary but never defined.**
   - Define it as a stopped case whose card has `terminal_stop: provider_wait`. The table already defers that field to stream A, so until then the count is zero. Say so.

5. **NIT: the dead-worker rule needs an explicit state for an unreachable Boat.**
   - If `boat-call list` fails, every launched case would read as "worker gone". Treat a failed list call as `unreadable` for the batch, with no per-case flags.

The two blockers from the second pass are closed: the journal-wins rule replaces the card-versus-progress ambiguity, and one 5-hour stuck rule replaces the contradictory pair.

FAIL until finding 1 is fixed.
