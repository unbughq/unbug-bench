# Diff review 1: g2-5813be-h6-hand-check (goldfish)

**Reviewer:** a fresh goldfish (Claude), read-only. Personas `zoom_out` and `implementation_readiness`, Mode REVIEW, standard implementation-readiness. I read `docs/designs/g2-blocked-source.md` and the commit message. `docs/ENGINEERING.md` does not exist in this worktree (`docs/` holds only `designs/` and `reviews/`), so I could not read sections 1, 2 and 4. See finding 1. I used `docs/reviews/g2-18681d-hand-check-diff-1.md` for format.

**Scope:** branch `fix/g2-ruling-5813be-answeroverflow`, `12da453d..e171998d`, 3 files, +83/-1:
- `factory/run.py` (+17): one new `G2_SOURCE_RULINGS` entry.
- `tests/factory/fixtures/g2-blocked-source.json`: one new case and an extended `_source` note.
- `tests/factory/test_g2_blocked_source.py` (+12): one new test.

Spec: on 2026-11-21 10:10 UTC the founder handed case decisions to Claude, who hand-checked the one held G2 row of `case-import-5813be-h6-1`. The entry must settle that row via `g2_source_ruling` and nothing else.

**What I ran:**
- `test_g2_blocked_source.py`: 15 tests OK.
- `test_sealed_audit.py`: 5 tests OK.
- I did not run the full suite.
- I did not re-run the elephant's identity proof (it needs the VM snapshot and a baseline archive). I checked it by reading the code, as noted below.

## Checked, no finding

- **Validity against `g2_source_ruling` (`run.py:2171-2199`).**
  - Keys are exactly the allowed set.
  - `gate` is "G2" and `by` is "founder".
  - `at` and `checked_at` are `YYYY-MM-DD`.
  - `ruling`, `checked_by` and `page_says` are non-empty.
  - `reports_this_bug` is a real bool (`False`).
  - `hand_check` has exactly its four keys, and `kind` is `hand_checked`.
  - `test_every_shipped_ruling_is_valid_and_keyed_to_a_held_case` passes, so every shipped entry has exactly one fixture match.
- **Keying and collisions.**
  - The entry's sha `6bef1af4…` and url `…/m/1468225994971418839` equal the new fixture case's byte for byte.
  - The h1 and h3 5813be entries share the sha but have different URLs, so the (sha, url) match stays unique.
  - The new URL appears in no other fixture case.
- **Fixture shape.**
  - The case has the same top-level keys as the neighbours (`answer`, `answer_file`, `case`, `flagged_index`, `flagged_rows`, `receipt`, `row`, `snapshot`, `statement_sha256`).
  - `snapshot` is a 12-hex digest prefix (`b9751bd6c09f`), as the others are.
  - `answer_file` has the `ordinary-retries/<sha>/answer-0.json` form.
  - `flagged_index` 3 of 16 fits the range. No test reads it, so I could not independently confirm the 1-based convention.
  - The receipt shows `http_429`, `retrieved_from: none`, `archive_available: false` and a Wayback 200 with an empty lookup. That is the unreadable/no-archive shape the code's `access_failure` branch needs.
  - The answer has `resolved: false`, `same_bug: null` and the matching URL, so `g2_source_ruling`'s same_bug-true guard does not fire.
  - Provenance is stated in `_source`. I cannot verify that the snapshot was read in memory on the VM or that the statement hash matches h6's `case/statement.md`. I take both on the commit's word.
- **New test.**
  - It asserts the receipt is 429/none/no-archive and that the ruling's kind, URL, sha and `reports_this_bug: False` match the fixture.
  - It runs the real `checked_freshness_verdict` with the shipped tuple and asserts no blocked rows, 0 confirmed hits and no transport pending. It also asserts `ruled_rows` carries the whole ruling.
  - Without the entry, `shipped(H6)` fails its `len(found) == 1` assert. A flip to `reports_this_bug: True` fails both the ruling assertion and the verdict (a confirmed hit). So it fails if the entry goes missing and if the ruling flips.
  - Existing tests are untouched. The helper re-keys every same-sha ruling to the authored statement, but the URL still disambiguates, so the other tests stay meaningful.
- **Identity and pins.**
  - The design says the rulings constant is hashed into `runner_inputs('G2')` only. This diff touches only that constant, a test and a fixture, so the elephant's "only G2's digest changed" claim is plausible.
  - `test_sealed_audit.py` passes, and its pinned delivery_contract is unchanged.
  - Section 1 of the design says adding a ruling changes G2 identity for every batch that receives the release. That is expected, as the design says, but see finding 2.
- **`by: "founder"` honesty.**
  - The code accepts only "founder".
  - The comment, the ruling text and `checked_by` ("Claude (founder delegation 2026-11-21)") all say Claude decided under the delegation, so nothing is concealed.
  - The delegation quote is carried in the code comment and commit message, not in the record fields beyond the ruling text. That is adequate.

## Findings

1. **nit:** `docs/ENGINEERING.md` is not in this worktree, so the requested sections 1, 2 and 4 could not be read. The review judged the change against the design doc and the code instead.
   - Section 4 ("no one-off rulings") is the one the design records as an explicit founder exception, so I do not expect it to change the verdict.
   - Fix: confirm the file exists on the integration branch.
2. **nit:** the entry skipped the design step and is per case, per URL, and G2-identity-changing. Under the design's operator step it is mechanically correct, but the saved record should state two things:
   - it is a data entry under the existing design (no code path changed);
   - applying it means a plumbing release plus a controller restart. Per the Murphy memory, "release breaks calibration identity" says never release between G10 and G11, so confirm h6's gate position before releasing.
   - No code change is needed.
3. **nit:** `page_says` summarises the thread's topic in detail. It is not a bug restatement, so it complies with the design's redaction rule (section 3). It is worth a glance only to confirm that no case-bug wording slipped in. I saw none.

## Verdict: PASS

The entry is valid, keyed uniquely to the new fixture case, and settles only the 429/no-archive row. The test fails without the entry and on a flipped ruling, and both suites I ran pass. The nits are record-keeping only.

## Elephant's response

- **Finding 1:** taken. `docs/ENGINEERING.md` lives on the working branch `work/murphy-parallel-20261104`, not on `origin/main`. The elephant read it there before starting. No change.
- **Finding 2:** taken. This is a data entry under `docs/designs/g2-blocked-source.md`, with no code path changed. The identity proof (origin/main 12da453d vs e171998d) shows exactly one changed line: runner G2's `G2_SOURCE_RULINGS` digest. `delivery_contract` and the verdict codes are identical. The release timing (h6's gate position, and never between G10 and G11) is the releaser's check. This PR does not release.
- **Finding 3:** checked. `page_says` describes the thread only. It names what the thread does not mention, and it does not state the case's bug.
