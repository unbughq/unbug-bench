My verdict is **FAIL**: one Blocker and two Nits. All earlier findings (diff-1 B1, M1–M4 and diff-2 B1, M1, N1–N3) are fixed. The Blocker is the case you asked me to inspect: a dead URL on a row flagged as a possible match still counts toward the G2 search minimums.

Full review text for you to save verbatim:

---

# Invalid-runs diff review 3: FAIL (1 Blocker, 0 Major, 2 Nit)

**Range:** `3f7521b..73b0f82` on `invalid-runs`. The implementation head is `c50e8d5`. The merge-base equals the `factory-simplify` tip `3f7521b`, so the branch is rebased. `73b0f82` touches only `docs/reviews/invalid-runs-validation.md`. `c50e8d5` touches only the design, the diff-2 response and `tests/factory/test_isolation_timeouts.py`.

**Mode:** REVIEW, against the Zoom-Out and Implementation-Readiness standards. Heilmeier was design context only.

**How I reviewed:** read-only. I read the design (including the diff-review-1 and diff-review-2 normative sections), all earlier review records, the validation, artifact and provenance records, the full code diff and the relevant test assertions. I ran no tests or workloads.

**Independent checks:**
- **Pins:** every `current_files` digest in `factory/invalid-runs-compat.json` matches the file at HEAD. Every `base_files` digest matches `6f17c5f`, which is an ancestor of `3f7521b`. That includes the new `factory/case_contract.py` pin and `bin/run_validity.py: null`.
- **Runner AST pins:** all seven `current_runner` entries (`calibrate`, `checkpoint`, `sh`, `time`, `tree_digest`, `verdicts`, and `signal` as null/absent) match `gate_state.source_inputs('calibrate','checkpoint','verdicts')` at HEAD.
- **Absent dependencies:** an absent target is popped (`if target is None: old.pop(...)`) rather than kept as `None`. Unknown digests still return `False`.

## Blocker

**B1. A row flagged as a possible public match, with a dead URL and no archive copy, still counts toward the G2 search minimums. The diff-2 B1 fix covers only unflagged rows. Row 24 is marked closed.**

- **Where:** `factory/run.py:1655-1656`. The `retrieved_from == 'none'` exclusion sits inside the `else:` (unflagged) branch. Flagged rows (`hit` or `ambiguous`) go through `retry(...)` at `:1646-1648` and are never added to `c.freshness_unfetched`.
- **Downstream:**
  - `freshness_counts` (`:1615`) excludes only `freshness_unfetched`, so the flagged row counts.
  - `checked_freshness_verdict` (`:1867-1873`) classifies the row as `unreachable` and `continue`s, so it is not blocked either.
  - G2 can therefore return `ok` with the row counted.
- **What happens:** a searcher logs an invented issue URL with `hit: true`. Models hallucinate issue URLs most readily exactly when they believe they found a match. The runner then:
  1. gets a 404 or DNS failure;
  2. gets an empty Wayback lookup, so the receipt says `retrieved_from='none'`;
  3. pays the reviewer, whose answer must agree with that receipt, so it clears the row as unreachable.

  The row then counts toward 3 web, 3 GitHub and 2 attacker searches.
- **Consequence:**
  - This is the same silent wrong result as diff-2 B1: freshness clears on a search that cannot be shown to have happened.
  - It contradicts the diff-review-2 normative rationale: "a runner receipt with retrieved_from=none … proves an unavailable page, not that a search happened". That rationale does not depend on the hit flag.
  - It is also inconsistent with the accepted contract. Step 4 lets a verified dead URL with no snapshot **clear a hit**, meaning it is not a public match. Nothing in the contract lets it **count as a search**.
  - Net effect: identical runner bytes are uncounted when unflagged and counted when flagged. Flagging a row is the more suspicious case, so this is backwards.
- **Archive-backed flagged rows are fine.** `retrieved_from='archive'` has retained snapshot bytes, so a page existed. Counting those is consistent.
- **Minimal fix:**
  - Move the `if any(receipt['retrieved_from'] == 'none' for receipt in result): c.freshness_unfetched.add(row['url'])` check out of the `else:` so it runs for flagged rows too. Clearance still goes through review, so the hit cannot become a public match.
  - Add a regression next to the unflagged one: replay a flagged row through the HTTP seam with a 404 and an empty `archived_snapshots`, with exactly minimum counts, and assert G2 is not `ok` and `counted` excludes that row.
  - I checked that the existing 17-row `test_seventeen_rows_dead_row_fourteen_no_archive_clears_and_receipts_reuse` would still pass. Row 14 is an attacker row; 7 attacker rows remain, against a minimum of 2.

## Nits

- **N1. `run_validity.runtime_revision` (`bin/run_validity.py:47-55`) hashes every `factory/*.py` file.**
  - Any plumbing edit, including A's or E's, gives every in-progress unit a fresh two-attempt allowance at the next checkpoint.
  - The design accepted this ("plumbing updates get a fresh allowance"), so it is not a defect. But the bound is "two per unchanged runtime", not "two total".
  - A one-line comment saying so would stop a later reader from treating the journal as a lifetime cap.
- **N2. Unflagged unfetched rows are re-fetched on every G2 call (`:1650-1654`).**
  - The fetch is not journalled, so repeated G2 evaluations retry slow 30-second timeouts each time. This costs time only and is bounded by the number of rows.
  - No change is needed unless G2 latency becomes a problem.

## Are earlier findings resolved?

| Finding | Status | Evidence |
|---|---|---|
| Diff-1 B1 (G16/G17 evidence) | Resolved | `fairness.py` binds every review row's actual workspace as `try-N`, including early-probe and replacement workspaces. It copies `strong-calibrator-{folder,early_probe,replacement}-*.jsonl`. `validate` refuses a missing guard or `execution.json`. `independent_review.review` checks digests before and after the call. |
| Diff-1 M1 (missing-fix replacement) | Resolved | A one-try series per missing try, reviewed in the same invocation. A completed no-fix replacement is never bought again. Valid later tries and the original G10 rows are kept, and seeds reproduce `seed + try`. |
| Diff-1 M2 (blocked unflagged URL) | Resolved for unflagged rows, including dead ones | The flagged dead-URL hole is new B1. |
| Diff-1 M3 (row 36 wording) | Resolved | — |
| Diff-1 M4 (retry allowance after success) | Resolved | — |
| Diff-2 B1 (dead unflagged URL) | Resolved for the unflagged path | `retrieved_from='none'` is uncounted and the seam replay asserts no count. Incomplete for flagged rows; see B1. |
| Diff-2 M1 (missing promised observation) | Resolved | See notes below. |
| Diff-2 N1 (cheat-pass ordering) | Resolved | `verify-negative` evaluates a validity-checked cheat-pass before the workflow diagnostic. |
| Diff-2 N2 (replacement key) | Resolved | The key is `{try, relative workspace, artifacts}`. `completed_attempts` rewrites only `identity`, so a migration does not change it. |
| Diff-2 N3 (first gate stop) | Resolved | `stop_infrastructure` returns early if a stop is already recorded. The `finally` join adds G10's stop only when no `failed_gate` exists. |

**Diff-2 M1 notes:**
- `verdicts` calls `require_valid` first, so an invalid batch raises `InvalidInfra` before any contract inspection. Only a valid batch with missing keys raises `CaseProblem`. That is not a third execution label.
- `CaseProblem` is caught in each place it can reach:
  - `GatePipeline.check`, before reuse is saved, covering G4/G5/G6/G7/G10/G11/G16/G17 including the overlapped G10 future;
  - `admission.prototype`'s `invoke`;
  - `early_cheat_check`, ahead of the `RuntimeError` handler. `CaseProblem` is a `ValueError`, so the order is correct.
  - `early_probe`'s broad `except` turns it into a skipped label, which is acceptable.
- No `ValueError` handler on a `verdicts` path swallows it. `completed_attempts` and `independent_review.validate` never call `verdicts`.

**E rebase:**
- `GatePipeline.check` keeps `processes.deadline` for G13–G15.
- E's `sh`, `processes.py` and lifecycle are unchanged in this diff.
- The `test_isolation_timeouts` fixture now asserts `infrastructure_exhausted`/`invalid-infra`, no `failed_gate`, and no writer callback. That is consistent with this workstream.

## Checked and found sound

- **Shared validity check:** `run_validity.classify`/`require_valid` is the only predicate. It is used by `read_completed` (on by default), `verdicts`, G14, strategy silent windows, calibration receipts, G11 rerun batches and `verify-negative`.
- **Row 22:** all-invalid G6/G7 cheats raise. G6 negative controls raise when nothing passed and the probe exited nonzero, logged `invalid-probe`, or ran zero probes.
- **Row 23:** no exception becomes a failed attempt. `execution.json` is written only after valid execution. `pending-<try>.json` prevents buying the solver again.
- **Row 25:** exact archive names and digests; probe and startup exceptions only.
- **Row 40:** G11 requires a single report bound to each guard, valid reruns, and independent adjudication of every flag.
- **Row 41:** reviewer families are chosen in configured order. A running receipt survives provider waits and its stale output is removed before retry.
- **Recovery:** all recovery entry points refuse exhausted cards.
- **Corpus projection:** only `case-20261017T125556Z-18681d` changes, and no card is rewritten.
- **Row 14:** correctly left open.

## Not judged

- Live S11 qualification, because launches are prohibited.
- Whether the suite passes; I relied on the saved record (131/0).
- Remote VM card provenance.
- Model quality of the adjudication prompts.

**Not PASS:** B1 is open. It is a one-line move plus one seam regression test.


## Elephant response

B1 accepted and fixed: the no-page exclusion now runs after both flagged and
unflagged retrieval. A real practice-log regression at exact search minima exercises
404/no-snapshot HTTP receipts and actual confirmation validation, proving the hit
can clear while the search count remains short. No finding rejected. N1's existing
per-runtime allowance is clarified in the design; N2 latency remains accepted as
requested. Another full suite and a fresh goldfish review follow.


Before review 4, factory-simplify advanced with its single-path increment. The
branch was rebased onto ac33267 and the worker inventory conflict resolved by
retaining both batch.py and all C helpers. No single-path contract was changed.
The pre-rebase full run was superseded by a new full run after this rebase.
