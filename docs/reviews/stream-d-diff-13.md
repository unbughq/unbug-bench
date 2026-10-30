# Stream D diff review 13: unwired legacy import

**Reviewer:** fresh goldfish (read-only), Mode REVIEW
**Personas:** `zoom_out`, `implementation_readiness`
**Standard:** `implementation-readiness-standard.md`

**Scope:** `7528c22..9111751`, one commit: "Add unwired legacy import dry-run and authenticated accounting validator". It touches:
- `factory/carry_over.py`: `legacy_import_dry_run`, `legacy_import_batch_dry_run`, `migrate_legacy_import`, and `legacy_import` added to `FACTS`;
- `factory/restore_ledger.py`: extracts `_authenticated_source` and adds the unwired `validate_legacy_import`;
- `tests/factory/test_stream_d_legacy_import.py`, which is new;
- doc nits in `docs/designs/interfaces.md` §8 and the implementation boundary appended to `docs/designs/stream-d.md`.

The untracked `.stream-d-next/` drafts are excluded.

**Checked against:**
- `interfaces.md` §8 "Legacy import record (proposed)";
- `docs/reviews/legacy-import-design-1.md` and `-2.md`, with their elephant resolutions;
- the stream-d implementation boundary;
- `factory/budget.py`: `_spending`, `usd`, `case_spending`;
- `carry_over.usage_facts` and `v0_to_v1`;
- the pre-change `restore_ledger.authenticate` at `7528c22`;
- Murphy D rows 8, 9, 10, 11, 12, 13, 15, 21, 35 and 39.

**Prior diff reviews of these helpers:** none. **Rejected findings:** none. **Row closures:** none.

## Verdict: PASS (0 blockers, 0 majors, 4 nits)

The code does what §8 specifies, and the design-2 nits N1–N5 are all in it. Nothing is wired into `job_config`, the manifest or the holder. Nothing grants money, launch, diagnosis or replacement authority. Every Murphy row named above is still `open`, and `docs/murphy-register.md` is not in the diff, which is correct.

## Independent checks

**Tests I ran (`python -B`, worktree at HEAD):**
- `test_stream_d_legacy_import`: 5 tests, OK.
- `test_restore_ledger` plus `test_carry_over`: 21 tests, OK.
- **Full suite:** the first line of `/tmp/stream-d-import-suite.log` is `91117512f25464dd3e1d7a7373be47112985550d`, which matches HEAD. The run was still going when I looked, so this review does not claim the full suite passed.

**Probe script (in memory only; nothing written to the repo):** I ran dry-run plus migration over every fixture that has a `case` and a `continuation_budget`.

| Fixture | Unresolved | Final total | `case_budget.total_spent_usd` | Terminal stop |
|---|---|---|---|---|
| canary6-collected | 1 | 60.072383602 | 60.072383602 | `retired_import_estimate` |
| c7d405-collected | 1 | 71.942747230 | 71.94274723 | `retired_import_estimate` |
| canary6-confirm-timeout | 0 | 43.091763729 | same | `retired_import_history_unknown` |
| c7d405-confirm-timeout | 0 | 59.241735101 | same | `retired_import_history_unknown` |
| canary6-last-legacy | 0 | 43.166938577 | same | `retired_import_history_unknown` |
| canary6-round8, e15450 ×3 | 0 | known total unchanged | same | `retired_import_history_unknown` |

**Accounting:**
- Two byte-identical markers produce two distinct invocation IDs and a total of $93.072383602. That is +$66, not folded into one $33.
- With top-level `list_cost_usd` absent, the code falls back to the sum of the events and still gives $60.072383602.
- An invalid waste record makes the unpriced count differ from the marker count, so the case refuses. It is not turned into a $33 invocation.
- The confirm-timeout cards keep their `{infrastructure_waste_id, original}` resolution entries, and those are correctly not refused.

**Bindings:**
- `import_id` changes when the generation changes.
- `migrate_legacy_import` requires the record's digest to equal the recomputed dry-run with authorization set to exactly the estimate. Wrong history, wrong amount, a bool `schema_version`, or a wrong generation each refuse, as the tests show.
- The validator binds `record_sha256`, then the case and generation through the shared helper. It then requires archived, public and retained ledger equality, plus no `legacy_import` or `job_money` and no `job-money.json` at the path `job_config` uses.

**No mutation and idempotency:**
- The batch dry-run leaves its inputs unchanged.
- Repeating the migration gives identical output.
- A migrated card refuses whether it is re-presented with its marker, under a new generation, or with the marker popped.
- A ledger holding only a `legacy-import:` event, with no resolution entry, also refuses.
- A migrated card passes `v0_to_v1`, so the `FACTS` classification works.

**Extraction regression:** `_authenticated_source` is the old body of `authenticate`, line for line. The only change is that `founder_ruling is not None` became `allow_public_correction`. `authenticate` passes exactly that condition and re-binds `work = Path(work)` before its later uses. I found no change in behavior, and the 21 restore and carry-over tests pass.

**Fixture provenance:** all five cards the tests use were added in the initial commit, as real saved cards. The worker test authors the restore layout, with the real practice bundle checked against its own sha256 list. §8 and the stream-d boundary say this openly, and no row closes on it.

**Scope:**
- Lifetime history is always null.
- Anonymous late-receipt reconciliation, resumable imports, the remaining stale-cap migration, and extension/diagnosis runner integration are named as outstanding in both docs. None of them is quietly claimed.

## Nits

### N1: a non-JSON record raises a raw exception instead of `Refused`

**Where:** `carry_over.migrate_legacy_import` and `restore_ledger.validate_legacy_import`. Both call `digest(record)` before any `require`.

With `{'x': nan}` the call raises a bare `ValueError`, and with a set it raises a `TypeError`, not `Refused`. A caller that catches only `Refused` would crash, or would leak a raw error into a public report. Nothing calls these helpers yet, so this does not block. Fix it with a `try`/`except` around the digest, or flag it for B's adoption review.

### N2: a few refusal paths are proven only by my probes, not by tests

None of these has an isolated test:
- the refusal of a ledger that has only a `legacy-import:` event;
- the validator refusing an archived `scorecard.json` without an embedded ledger (`'legacy import requires the archived original ledger'`);
- the validator refusing an archived card that already has `legacy_import`.

The `active` refusal is tested only through the batch. Each would be a one-line `assertRaises` in the existing tests.

### N3: the $33 rate appears in four places

**Where:** `'33.000000000'` twice, `usd(33 * …)`, `list_cost_usd=33`, and `33 * len(markers)`.

One module constant would keep the dry-run, the batch totals and the migration from drifting apart. Today the nine-place equality check would catch a mismatch at runtime, so this is cosmetic.

### N4: one batch can hold several generations of one case

In the batch dry-run, two different real generations of one case are both refused as duplicates. That is correct, since it is the one-import-per-case rule. But it means a batch built from the full fixture inventory refuses canary6 entirely, because canary6 has several saved generations. B's adoption should state that the operator chooses the generation before the dry-run. The doc could say so in one line.

## Standard checklist

- **Zero decisions:** the entry points, signatures, event JSON, aggregate rule, terminal stops, refusal set and FACTS classification all match §8. I found no choice left open in the code.
- **Stable phases:** the code is unwired, `job_config.install` still refuses legacy checkpoints, and B's adoption gets its own review.
- **Zoom out:**
  - The code reuses the existing pieces: `_spending`, `usd`, `usage_facts`, `digest`, and the restore authentication through one shared helper rather than a second path.
  - It adds no new modules, configuration or speculative history schema.
- **Murphy:** no row closes, which is correct, because the restore-boundary exams use authored records.

**Pass condition met:** no blocking finding is open, and the nits are optional.

---

I worked read-only, so the review file is not saved. The text above is the full content for `docs/reviews/stream-d-diff-13.md`.

## Elephant resolution

PASS accepted for 7528c22..9111751. No blocking finding rejected. Optional N1–N4 are retained for B's adoption review: normalize non-JSON-record errors, add the probe-only refusal assertions, consolidate the estimate constant, and select one generation per case before batch dry-run. These helpers remain unwired. No Murphy row closes. Full-suite evidence is recorded separately when the pinned 9111751 run completes.

## Full-suite result

`uv run --with numpy --with scipy python -B tests/run.py`: **144 scripts, 0 failed**.
`/tmp/stream-d-import-suite.log` starts with 91117512f25464dd3e1d7a7373be47112985550d.
The reviewed implementation and tests stayed unchanged throughout the run; only
unrelated design/review documents and excluded drafts changed. No row closes.
