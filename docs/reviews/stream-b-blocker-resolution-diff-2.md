**PASS: 0 blockers, 0 majors, 3 nits.**

B1 is fixed by `d38499a`, and the fix is the right size. The legacy check is gone from the holder resume path. Planning now retires a card only when it has no `diagnosis_state` **and** the real `diagnosis.exhaustion(card)` says it is exhausted. The new tests fail if either half of the fix is reverted. The suite record matches the source commit. The four dispositions are unchanged and no Murphy rows were closed.

---

# Goldfish diff review: `stream-b-blocker-resolution` (diff 2)

Mode: REVIEW. Personas: `zoom_out`, `implementation_readiness`. Standard: `implementation-readiness-standard.md`. Worktree `t3-ded79ec5`, range `9b9e5e0..76cfa6b`, reviewed against `docs/designs/stream-b-blocker-resolution.md`. The focus is the accepted blocker B1 from `docs/reviews/stream-b-blocker-resolution-diff-1.md`.

What I read:
- the full range diff, plus `d38499a` and `76cfa6b` in detail;
- `factory/batch_holder.py` `_source`;
- `factory/batch_service.py` `retire_legacy` and `plan`;
- `factory/diagnosis.py`: `exhaustion`, `_trigger`, `_state`, `record_exhaustion`, and where `factory_bug_held` gets set;
- `factory/run.py` around line 3093, where final accounting calls the producer;
- the changed holder and D tests and their fixtures (`output`, `card`, `waiting`);
- the design and report changes, the attempts record, and the new suite JSON and log.

## Verdict: PASS

## B1: fixed

**The holder no longer retires anything.**
- The `service.retire_legacy(...)` / `legacy_retire` lines are deleted from `_source` (`batch_holder.py:138-158`). Its docstring says read-only again.
- A grep finds `retire_legacy` called only from `plan()`, at `batch_service.py:326`. No holder, reserve, dispatch or provider-wait scan path reaches it.
- So the B1 failure is gone on every route: checkpoint reserve (`key_holder` → `reserve`), the provider-wait scan, and `_post`/dispatch preflight.
- N5 (the capacity check running before `_source`) is moot now that the check is gone.

**Planning retirement is limited to the scope the design set.**
- `retire_legacy` returns False when the card has a dict `diagnosis_state`. It also returns False when `diagnosis.exhaustion(card)` is False. Only then does it write the record. This is the pure D predicate itself, not a copy of its stop rules inside B, which is what the design asked for.
- `exhaustion()` returns False for `provider_wait`, `paused`, `ttl_retired`, `retired*`, sealed or retired status, G12 pass, malformed history, an open extension, and a present-but-invalid `diagnosis_state`. None of those cards can retire any more.
- The retire check still runs before the `DIAGNOSIS_ENABLED` gate, before stored facts and before `_project`.
- The existing exhausted-legacy D tests still retire: `test_legacy_retirement_precedes_stored_facts` and the unbound known/null precollected tests.

**The new tests discriminate.** I mentally reverted each half of the fix and checked that a test would catch it.
- *Holder* (`check_unexhausted_source`, run with `provider_wait`, `paused` and `ttl_retired`):
  - It starts from the retained e15450 continuation budget, with batch bindings authored by the test.
  - It removes `diagnosis_state`, sets the stop and runs the real `diagnosis.record_exhaustion`. It then asserts the state is still absent and `exhaustion` is False.
  - It publishes, records worker retirement, reconciles, then calls `reserve(source=...)` twice. It gets revision 2 and an idempotent replay.
  - It runs `holder._post` under `money.locked` and asserts no `retirements/` directory exists.
  - **Revert check:** putting back the old holder check would raise `legacy_retire` and create `retirements/`, so all three tests would fail.
- *Provider-wait scan* (`WaitSchedulingTests.waiting`):
  - The authored `diagnosis_state={}` is now removed, and the real producer is called.
  - `test_tick_future_due_restart_and_single_successor` asserts the state is absent. It covers `schedule_waits` running to a revision-2 successor and asserts no `retirements/`.
  - This removes the "fixture authored to suit the code" problem named in B1.
- *Planning* (`check_unexhausted_plan`, run with the same three stops):
  - The card is built with `provenance=False` and passed through the real producer.
  - It checks that `diagnosis_unavailable` with diagnosis off leaves the journal byte-identical.
  - It then checks `planned` with `exhaustion: False`, an empty queue, an idempotent replay, and no `retirements/`.
  - **Revert check:** dropping the `exhaustion()` half of the fix would return `retired`, so these tests would fail.
- **My own run:** I re-ran `tests/factory/test_batch_holder.py` (59 tests, OK) and `tests/factory/test_batch_service_d.py` (15 tests, OK) at the tip. All seven new or changed tests ran by name and none were skipped. `git status` stayed clean.

**Leftover empty `diagnosis_state={}` fixtures are legitimate.**
- `test_batch_service.py:79` is still contract-only ServiceTests, and the design now says so explicitly.
- `test_batch_service_d.py:183` (`check_malformed`) deliberately tests an invalid state, where `exhaustion` must be False. It does not use the field as provenance, so it is fine.

## Regression and scope check

- **Holder admission order is unchanged.** It still runs `_entry` authentication, then the manifest and `job_money` binding checks. The rest of the range (boat-spend liability, the frozen disposition JSON, integration and launch-guard tests) is untouched by `d38499a`.
- **The four dispositions are unchanged in substance.**
  - Cleanup guarantees: deferred to live practice, after the provider-contract or re-approval prerequisite.
  - Cumulative accounting: deferred to live practice, after Boat attributed settlement.
  - Deployment qualification: deferred to live practice, after B2 and B3.
  - Saved legacy cases: retire-only. The Legacy row's wording changed to drop the over-reaching runtime-guard claim. That is a correct narrowing.
- **Live cloud is not claimed.** The report says offline tests do not qualify deployed state.
- **N4 is documented** in both the design and the report: scanner `reserved_usd` is reserved estimates only, and finished or `reconciled_expired` rows remain unknown liability.
- **Optional nits N1, N2, N3 and N6 are untouched,** as stated.
- **No Murphy rows were closed.** `docs/murphy-register.md` is not in the range diff, and both docs say "No row closed".
- **Nothing speculative was added.** The fix is +3/−3 source lines.

## Suite record

- `…T172742Z-2a0a1b93.json`: `source_commit` is `d38499a0f1c577ac07266e130d5d0756376423f4`. `source_tree` is `aea4de08…`, which matches `git rev-parse d38499a^{tree}`. Exit code 0, 162 scripts, 0 failed.
- The compressed log sha256 matches the record (`bb4412e1…`), and so does the uncompressed one (`13613b1f…`). The log ends with "162 test scripts run; 0 failed." Its holder section shows 59 tests OK and its D section 15 tests OK, matching the new counts.
- **Correction to the brief:** the tip commit `76cfa6b` does not only add the JSON and log. It also appends a 10-line validation paragraph to `docs/reports/stream-b-blocker-resolution.md`. That paragraph is docs only and its contents are accurate. No source or test file changes after `d38499a`.

## Nits

- **N7.** The planning predicate still assumes that "exhausted + no `diagnosis_state`" can only mean legacy. For current-runner output this should be unreachable:
  - `record_exhaustion` writes a state whenever `exhaustion` and `_trigger` hold.
  - Its `factory_bug_held` early return is reachable only after a state already exists (`diagnosis.py:313`, `diagnosis_dispatch.py:271`).
  - The remaining gap is a run where `run.py:3091` skips the producer (`factory_job` false, or not stopped). That gap is moot because `plan()` has no production caller.
  - No test asserts this invariant directly. Before `plan()` gains a caller, consider one test where a current-runner exhausted stop goes through the producer and gets a state rather than retiring.
- **N8.** The new holder and planning regressions mutate `terminal_stop` on a retained card. They do not use a saved real provider-wait or paused card. The producer call is a no-op by construction for these stops, because `exhaustion()` excludes them early. That is adequate as proof, and the brief's "retained cards/usage with authored batch bindings" describes it accurately. A saved real interrupted card would still be stronger evidence, if one exists.
- **N9.** One edited design line in the verification paragraph (around line 110) runs over the wrap width: "…Planning must also preserve those cases. Verify retirement disposition…". It is cosmetic.

## Scope honesty

- B1 is fixed at the root and is not exempted.
- The four dispositions are unchanged; only the over-claim in the Legacy row was removed.
- N4 is documented, N5 is moot, and N1, N2, N3 and N6 are deliberately not implemented.
- Both gates stay off: `HOLDER_ENABLED` and `DIAGNOSIS_ENABLED` are False.
- There were no workers, paid calls, pushes, Murphy closures or claims about live cloud.

The branch is merge-ready from this reviewer's side. The parent's reviewer order still applies: free OpenCode next, then a fresh codex/gpt-6.1-sol.

## Elephant disposition

PASS accepted: zero blockers and zero majors. B1 independently verified fixed.
N7/N8 are optional future qualification improvements; N9 wrapping corrected.
No source or tests changed after d38499a. The full suite remains 162 scripts,
0 failed, exit 0. No Murphy rows closed; both activation gates stay off.
Claude completed this review, so no further fallback reviewer is needed.
Reviewer order for any future review is Claude, free OpenCode, then fresh
codex/gpt-6.1-sol; paid OpenRouter is forbidden. No blocker was rejected or
self-verified. This record closes the pending diff review, not the deferred live
practice prerequisites described in the report.

