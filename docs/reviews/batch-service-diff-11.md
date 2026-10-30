**FAIL.** There is one blocking finding, and it is in the tests only. The production change itself is correct. I edited nothing in the worktree, and `git status` there is clean.

What I ran:
- **Focused tests:** `tests.factory.test_batch_service` ran 11 tests and passed at HEAD. This is not the full suite.
- **Mutation checks:** I ran these on `git archive` copies in my scratchpad, at HEAD and at `c2d306d`.

Review text for `docs/reviews/batch-service-diff-11.md`:

---

# batch-service diff review 11

**Reviewer:** goldfish, read-only, fresh context. Personas: `zoom_out`, `implementation_readiness`. Mode: REVIEW. Standard: `implementation-readiness-standard.md`.
**Scope:** `c2d306d..HEAD` (175cba3, "Require an eligible pending projection before replacement derivation"), branch `t3/batch-service-control-vm`.
**Authority:** `docs/designs/batch-service.md` increment 2b.1, as amended in this diff, and the parent ruling of 2026-10-30. Under that ruling, the first child derivation requires a present `pending_projection` with `replacement_eligible:true`. A `None` projection never derives a child, whatever the predicates say. B does not duplicate D's stop predicates. The adapter stays False.
**Not reviewed:** D's draft contract (`1cc880a:docs/designs/interfaces.md`), which is not authority here. Earlier passes (diff 8 core, diffs 9 and 10 status) were not re-reviewed.
**Design round:** step 2 was skipped under the ENGINEERING small-fix exception. This diff is about 20 lines with an obvious cause, and it amends the design text in place.

## Verdict: FAIL (1 blocking)

## What is correct

- `factory/batch_service.py:246-249`: `_replacement` now requires `pending is not None and pending['replacement_eligible']`, together with both predicates. A `None` projection can no longer derive a child. This matches the ruling.
- `_facts` (lines 69-70) already refuses `replacement_eligible:true` when either predicate is false. So the predicate conjunction in `_replacement` is only the consistency check the design names. A mutant that removes it survives, as an equivalent mutant, and that is expected. B does not recompute D's stop predicates anywhere.
- `_load` re-validates each stored derivation with `_replacement` against its `eligible_generation` facts. A stored derivation that rests on a `None` projection now refuses. No production journal can hold one, because `DIAGNOSIS_ENABLED = False` (line 20, unchanged) means facts are never persisted in production. No migration is needed.
- **Unknown total with `None`:** the same-owner settlement resume is still queued, because `_enqueue` line 277 is unchanged. Covered by `test_unknown_absent_projection_priority_and_immutable_replay`, which expects queue `['settlement']` and empty `derivations`. Mutant M4, which drops the unknown-total clause, fails this test.
- **Known total with `None`:** no child and no request. Covered by the new `test_none_projection_never_derives_even_with_both_predicates_true` (empty queue, empty `derivations`) and by the `(False, None, 0)` row of `test_predicate_no_work_false_projection_and_disabled_replacements`.
- **Eligible projection present:** produces the deterministic `j → j-r1 → j-r2` chain. Covered by `test_two_child_chain_dedup_across_generations_and_restart`, which now supplies the eligible projection explicitly. The test checks two derivations, `eligible_generation` bound to the first generation, and that a tampered `child_job` refuses. The old rule fails this test (mutant M1: 2 failures).
- **A later `None` keeps the recorded child:** the same chain test plans a new generation of `j` with `self.answers()` (`None`). The derivation and the `j-r1` replacement row survive. `_enqueue` skips the derivation block and never deletes anything.
- **Replay cannot re-evaluate a changed D:** both the new test and the changed unknown-total test replan with a different API (eligible, and `SimpleNamespace()` respectively). Each gets an identical result, and the journal bytes are unchanged.
- **Design amendment** (`batch-service.md:920-925`): consistent with the code and with the unchanged unknown-total settlement paragraph.

## Findings

### B1 (blocking): the diff removed the only tests for two design rules that still apply

Design 2b.1 says: "Unknown-total parent: enqueue child but mark unknown_total; same-owner resume has settlement priority." Before this diff, the only test of both rules was the assertion `['settlement', 'unknown_total']` in `test_unknown_absent_projection_priority_and_immutable_replay`. That case came from a `None` projection, which no longer derives a child. The diff correctly changed the assertion to `['settlement']`. But no other test builds an eligible derivation with an unknown total: the chain test and the failed-write test use `total=0`, or check only `derivations`. The production code for both rules is unchanged, and both rules are now unverified.

Mutation evidence, tested at `c2d306d` and at HEAD:
- **M2:** replacement reason hard-coded to `'exhaustion'` (drops `unknown_total`). Caught at `c2d306d` (1 failure). Survives at HEAD (OK).
- **M3:** settlement ordering priority removed in `ordered_queue`. Caught at `c2d306d` (1 failure). Survives at HEAD (OK).

**Required fix (test only):** add an eligible-projection case with `total=None`. It should assert:
- `[r['reason'] for r in result['queue']] == ['settlement', 'unknown_total']`, which is ordered output from `ordered_queue` even though the replacement row has the lower sequence;
- one derivation.

This could be a second plan in the new None test, or a variant of the chain test.

### N1 (nit)

The test name `test_unknown_absent_projection_priority_and_immutable_replay` no longer tests any priority, because its queue has a single row. It could be renamed, or it could host the B1 case.

### N2 (note)

The Murphy register is untouched. That is appropriate: this is a rule correction inside an unmerged increment, and it does not close a row.

## Not claimed

- The full suite (`uv run --with numpy --with scipy python -B tests/run.py`) was not run by this reviewer. The focused module ran 11 tests and passed at HEAD.
- No spend, crypto, VM or cloud actions were taken.

---

The B1 fix is a three-line test addition. The mutant commands are reproducible from my scratchpad copies at `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/e66e1c1b-e3d8-4b04-9aba-e4523a762e78/scratchpad/mut` (HEAD) and `/private/tmp/claude-501/-Users-bugsincode-Developer-unbug-bench/e66e1c1b-e3d8-4b04-9aba-e4523a762e78/scratchpad/mut0` (`c2d306d`).

## Elephant resolution

B1 accepted. Add a separate unknown-total eligible-projection test asserting
settlement before the earlier-sequenced replacement, its unknown_total reason,
and exactly one derivation. N1 accepted: rename the absent-projection test to
describe settlement and replay. No production change or Murphy row closure.
Fresh diff review follows; this FAIL record remains intact.
