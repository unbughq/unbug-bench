**PASS.** No findings. I edited and saved nothing. The worktree status is clean.

One scope note: branch HEAD is now `0f10038` ("Record green read-only status suite"), one commit past `165a0fd`. That commit only adds `docs/reports/batch-service-status.md`. I did not review it, and nothing below relies on it.

Review text for `docs/reviews/batch-service-diff-12.md`:

---

# batch-service diff review 12

**Reviewer:** goldfish, read-only, fresh context. Personas: `zoom_out`, `implementation_readiness`. Mode: REVIEW. Standard: `implementation-readiness-standard.md`.
**Scope:** `c2d306d..165a0fd` on branch `t3/batch-service-control-vm`:
- 175cba3: the one-line `_replacement` fix, regression tests and the design amendment.
- 165a0fd: the resolution of diff-11 B1 and N1.

**Authority:** `docs/designs/batch-service.md` increment 2b.1, as amended in this diff, and the parent ruling of 2026-10-30. Under that ruling, the first derivation requires a present `pending_projection` with `replacement_eligible:true`. A `None` projection never derives a child, whatever the predicates say. B does not duplicate D's stop predicates. The adapter stays False.
**Not reviewed:** D's draft contract (`1cc880a`), which is not authority or activation evidence. Commit `0f10038`, which is past scope. Earlier increments.
**Design round:** a separate design round was skipped under the ENGINEERING small-fix exception. The cause is obvious, the production change is one line, and the design text is amended in place.

## Verdict: PASS

## Production change

- `factory/batch_service.py:246-249`: `_replacement` now requires `exhaustion and actual_model_work and pending is not None and pending['replacement_eligible']`. A `None` projection cannot derive a child.
- The predicate conjunction is only the contract consistency check. `_facts` (lines 69-70) already refuses `replacement_eligible:true` when either predicate is false. B does not recompute D's stop predicates anywhere.
- `_load` (line 122) re-validates stored derivations through the same `_replacement`, so a stored derivation that rests on `None` now refuses.
- No production journal can hold facts, because `DIAGNOSIS_ENABLED` is still False. No migration is needed.
- `_enqueue` and `ordered_queue` are unchanged.

## Design amendment

`batch-service.md:920-925` states the ruling exactly:
- The first derivation needs a present, eligible projection.
- Both predicates must be true, as a consistency check.
- `None` never creates a child.
- B does not copy D's stop predicates.

This is consistent with the unchanged paragraph below it. An exhausted unknown-total parent still gets the same-owner settlement resume, even when the projection is `None`. That is a resume, not a derivation.

## Diff-11 resolution

**B1 is resolved.** The new `test_unknown_eligible_projection_settlement_precedes_replacement` runs with an unknown total (the default card has no total) and an eligible projection. It asserts:
- the ordered reasons are `['settlement', 'unknown_total']`;
- the settlement row's sequence is greater than the replacement row's sequence, so the ordering comes from priority and not from insertion order;
- exactly one derivation exists.

Together these restore checks of both the `unknown_total` replacement reason and settlement-before-replacement priority.

**N1 is resolved.** The test is renamed to `test_unknown_absent_projection_settlement_and_immutable_replay`.

The diff-11 record is intact and includes its Elephant resolution. No findings were rejected.

## Behaviors preserved, each with its test

| Behavior | Test |
|---|---|
| `None` with unknown total gives a settlement resume only, with no derivation | `test_unknown_absent_projection_settlement_and_immutable_replay` |
| `None` with known total and both predicates true gives an empty queue and no derivation | `test_none_projection_never_derives_even_with_both_predicates_true` |
| `None` without model work gives no rows | the `(False, None, 0)` row of `test_predicate_no_work_false_projection_and_disabled_replacements` |
| Replay with a changed D gives an identical result and identical journal bytes, without calling D | the `SimpleNamespace()` replan in the absent-projection test, and the eligible-API replan in the `None`-never-derives test |
| An eligible projection derives the `j → j-r1 → j-r2` chain, with `eligible_generation` bound to the first generation and a tampered `child_job` refused | `test_two_child_chain_dedup_across_generations_and_restart` |
| A later `None` generation of `j` keeps the recorded child | same chain test, which plans that generation with `self.answers()`; derivations stay at 2 and the replacement rows stay `['j-r1', 'j-r2']` |
| An eligible `replacement_eligible:false` projection gives a resume and no derivation | `test_predicate_no_work_false_projection_and_disabled_replacements` |
| A failed write leaves the journal unchanged, and replay rebuilds once | `test_failed_plan_write_is_atomic_and_replay_rebuilds_once`, which now supplies the eligible projection explicitly so its 2-row expectation still holds |

## Mutation evidence

All mutants ran on `git archive 165a0fd` copies in the reviewer scratchpad. The base runs 12 focused tests and passes.

| Mutant | Change | Result |
|---|---|---|
| M1 | old rule `pending is None or …` | 2 failures: the `None`-never-derives test and the absent-projection test |
| M2 | replacement reason hard-coded to `'exhaustion'` | 1 failure: the new unknown-eligible test (survived at diff 11) |
| M3 | settlement priority removed from `ordered_queue` | 1 failure: the new unknown-eligible test (survived at diff 11) |
| M4 | unknown-total settlement clause dropped | 1 failure |
| M5 | `replacement_eligible` ignored (`pending is not None` only) | 1 failure |

## Findings

None.

## Notes

- **N1:** the Murphy register is untouched. That is appropriate: this is a rule correction inside an unmerged increment, and it closes no row.

## Not claimed

- The full suite was not run by this reviewer. Only the focused module ran: 12 tests, OK. The full-suite result must come from the separate run.
- No spend, crypto, cloud, model or VM actions were taken.

---

The mutant copies are in `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/cad820b8-f90d-409b-b370-6f29f93bd68d/scratchpad/` (`base`, `m1` to `m5`) if you want to reproduce them.

## Elephant resolution

PASS accepted; no findings remain. Full suite for this correction is running
separately in /tmp/unbug-b-projection-rule-tests.log. No enablement or row closure.
