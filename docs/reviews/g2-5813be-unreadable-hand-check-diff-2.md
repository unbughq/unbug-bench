# Diff review 2: g2-5813be-unreadable-hand-check (goldfish)

**Reviewer:** a fresh goldfish (Claude general-purpose subagent, no prior context, read-only), personas `zoom_out` and
`implementation_readiness` in `Mode: REVIEW` (read from the main checkout's untracked `tools/egm/`), given the diff
48e1263b..2b338bf1, the design, the founder's ruling as relayed and the G2 reviewer's real findings for both rows.

## Verbatim

VERDICT: PASS

No blocking findings. The change does what the founder approved and nothing wider. Three NITs below, all optional.

**What I checked**
- **Scope:** I read `g2_source_ruling` at `factory/run.py:2108-2136`. The new path only fires when all of these hold:
  - the receipt shows a live page (`retrieved_from: live`), which `retrieve()` only records for an HTTP 200;
  - the reviewer's answer is a dict with `resolved` false and `same_bug` not true;
  - the answer names the row's URL and agrees with the receipt;
  - the ruling is a `hand_checked` entry.

  So it never settles a `not_needed` ruling on a fetched page, a confirmed row, a resolved row, a `retrieved_from: none` receipt, an archive copy, another URL or a disagreeing answer. Cases with no matching ruling behave exactly as before.
- **Untouched files:** the diff touches only `factory/run.py`, `tools/check-g2-rulings.py` (docstring only), the test, the fixture, the design and the review record. `factory/calibration.py`, `factory/gate_state.py` and `bin/claims.py` are untouched. `test_only_g2_identity_reads_the_rulings` passes.
- **Crash paths:** none new.
  - `receipt.get` and `access_failure(receipt)` already ran on every flagged row.
  - The new `agrees()` call only runs for a dict answer on a live receipt. The existing check at `run.py:2331` already called `agrees()` on every dict answer with the same receipt.
  - The statement is now hashed for unreadable rows too. That is cheap, and the code still guards a missing `case`.
- **Tests:**
  - `tests/factory/test_g2_blocked_source.py` ran 14 tests, all OK.
  - I loaded the old `g2_source_ruling` from 48e1263b in memory and ran the new 5813be test against it: it fails, as the test claims.
  - It uses the real fixture rows and answers for both pages, and asserts the shipped entries match the fixture's statement sha256 and URL.
  - From reading the code, each guard (resolved, URL, agrees, live only, `same_bug` not a bool, dict) has a negative case that would fail if that guard were removed.
- **Interactions:** none. `ordinary_freshness.ruled()` and `stalled()` only look at access-failure receipts, and these pages are not one. `metadata()` only treats a ruled row as "no search evidence" if it was never fetched, so G2's search counts don't change for these live rows. `keep_mixed_receipt` passes `case` through as before.
- **Leaks:** the fixture answers are the reviewer's verbatim text about a loading shell. Neither ruling names a defect or fix.

**Findings**

1. NIT, `factory/run.py:2116`: `answer.get('same_bug') in (None, False)` also accepts `0`, `0.0` and a missing `same_bug` key, because `0 == False` in Python. I confirmed with a probe that each of these settles both 5813be rows. The design (section 2) says "`same_bug` null or false". The engine's answer schema rejects these values, but the non-engine opencode path does not check them. No confirmed row can get through, so this is a design-accuracy nit.
   - Fix: `'same_bug' in answer and (answer['same_bug'] is None or answer['same_bug'] is False)`.
   - Add `0` and a missing key to the "same_bug not a bool" negative cases.

2. NIT, `tools/check-g2-rulings.py:40` and `:90`: the pre-release check pairs the first flagged row that has the ruled URL with one answer per URL. Because `answers` is keyed by URL, the last answer for that URL wins. Case h1 has 4 flagged rows on `api/admin/orders/create-fulfillment`, so the tool checks one answer and can print OK while another of the four still holds G2. That would cost a resume. The fixture has only the first of the four rows (`g2-blocked-source.json` `_source`), so the tests also prove one of h1's four rows.
   - Fix: in the tool, pair each flagged row with its own answer by index, and print OK only if every flagged row with the ruled URL settles.
   - Or, before releasing h1, confirm on the VM that all four answers are `resolved: false` and `same_bug` null or false.

3. NIT, `factory/run.py:2088`: h3's `page_says` includes "a note that each fulfilled managed-inventory item needs a reservation". The rule at design lines 125-126 asks `page_says` to describe the page without restating the bug. That clause is not needed to identify the page, and it is the one detail close to an inventory case's subject. I could not read 5813be's sealed statement to tell whether it restates the bug.
   - Fix: drop the clause, for example "its steps, an example, its input and output schema and its events."

## What the elephant did

- **Nit 1, taken:** the guard is now `same_bug is None or same_bug is False`, so `0`/`0.0`/strings no longer pass; an absent
  key still counts as not confirmed (the reviewer did not confirm), and the design says so. New negative case
  "same_bug zero"; the previous `in (None, False)` guard fails it.
- **Nit 2, verified instead of changed:** h1 is retired and is not released; G2 reruns its searches on h4. On the VM I
  replayed `run.checked_freshness_verdict` with this branch's run.py over every retained answer of h3 and h1, row by row
  (in memory): h3 blocked [] ruled [8] (all 3 retained answers); h1 ruled [2, 7, 18, 19, 25] (all four create-fulfillment
  rows plus the workflow row), with only rows 4, 12, 16, 26 (#15327 / mith.tech, already ruled in the r1j disclosure)
  still confirmed. The tool's per-URL pairing is left as is.
- **Nit 3, taken:** the reservation clause is gone from `page_says`.
