**Verdict: PASS.** No blocking finding is left open. I checked the B1 fix myself and it holds: the new test does move a case across two releases, and each assertion fails at the rule it is meant to test. One Major is left: the transfer refusal list misses some retirement labels. It doesn't block, because no money can be regranted and the extension retirements retire again on relaunch. Below that are three Minors and some Nits.

---

# Diff review 2: batch carry-over (`56b4c13..018e1a1`)

**Reviewer:** fresh goldfish. Mode: REVIEW. Read-only, no subagents, no workers, no paid or model calls, no pushes. The working tree stayed clean. I read the `zoom_out` and `implementation_readiness` personas first. I applied the zoom-out, implementation-readiness and Heilmeier standards.

**What I read:**
- `docs/ENGINEERING.md`
- `docs/designs/batch-carry-over.md`, in full, including the new "Diff-review integration clarifications"
- `docs/reviews/batch-carry-over-diff-1.md`: the findings and the implementation disposition
- `docs/reviews/batch-carry-over-design-4.md`
- the interfaces and stream-d addenda
- the whole increment diff, with close reading of `19f1c94..f55c8e0`: `batch_transfer.py`, `batch_holder.py`, `diagnosis.py`, both test files
- the surrounding code: `diagnosis_dispatch._dispatch` and `dispatch`, the `run.py:3297-3335` stop handler, `diagnosis._trigger`, `_resume_bindings`, `extensions.propose`, and `batch_service._load`

## Suite record

- `docs/reports/batch-carry-over-suite-20261031T150728Z-9561445c.json` records 159 scripts, exit 0, on code commit `f55c8e0`.
- I recomputed the log's SHA-256 as `eda6e72f…`, which matches the record. The log ends "159 test scripts run; 0 failed."
- `git diff f55c8e0 018e1a1` touches only those two report files, so the tested code is the code under review.
- As an extra check, I re-ran `test_batch_transfer.py` (14 OK) and `test_stream_d_held.py` (19 OK).

## B1: checked myself, resolved

The test is `test_two_release_successor_carries_debit_latch_and_queued_owner` (`tests/factory/test_batch_transfer.py:128-172`). I traced it, and I ran a probe that wraps `batch_transfer.require` to record which line refuses.

| What diff-1 asked for | Where | Checked |
|---|---|---|
| S → T1, then a local successor collected in T1, then T1 → T2 | `:131-150` | T1 runs a real `reserve` → `started` → `output` (a different saved ciphertext) → `publish`/`retirement`/`reconcile` cycle; `fixed-again` then imports from `fixed`. |
| Inherited debit carried and not counted twice | `:152-153`, `:172` | T2's aggregate equals S's aggregate, and the debit is 1000. The assertion catches both mistakes: dropping T1's carried debit gives a T2 total of 2000; counting it twice gives 4000. |
| T2 still holds the S parent's one-child latch | `:156-163` | `imported_derivations[...]['source_batch'] == 'practice'`, so the latch crossed two hops through `prior_import`. A later `_enqueue` on the successor adds no replacement row and changes no latch. |
| A queued null-generation child moves again | `:131`, `:149`, `:169-171` | `j-r1` stays `None` across both hops with no operation in T1. T2's `reserve('j-r1', None)` succeeds, repeats give the same result, and the total is unchanged. |
| An imported checkpoint with no local successor refuses (D3-M3) | `:135-137` | The probe shows the only refusal is at `batch_transfer.py:219` (`generation in row['acks']`), which is the intended rule. `export.json` is absent afterwards. |
| Second-hop source and worker install | `:164-167` | `source_directory` resolves to T1's directory and returns the successor card. Real `restore_ledger.install` and `job_config.install` then run against T1's authority, and T1's manifest has its own `carry_from`. |

## M1 and m1–m6: checked

- **Refusals fire at the intended lines** (from the probe):
  - `args` and `max_calls` at `batch_transfer.py:208`;
  - `replacement_disabled` at `predecessor:41`;
  - `commitment` at `:212` (the m2 fix);
  - `deadline` as `MoneyWait('retired_batch_bound')` (the m1 fix);
  - schema-1 refused by `load_locked`;
  - sealed, `retired_not_converging` and `retired_factory_bug_limit` at `:221`;
  - a queued child with an operation at `:215`.
- **Positive admissions tested:**
  - a deadline-stop (`retired_batch_bound`) card goes through restore and install (`:284-292`);
  - an unrelated fresh root gets ordinary admission (`:213-220`).
- **m5:**
  - `resume_factory_bug` now builds the cleared card separately and changes `c.card` only after the write is durable (`diagnosis.py:495-500`). An `OSError` after validation becomes `factory_bug_resume_io_wait` (`:503-506`).
  - Through the real `dispatch` this is not turned into `invalid` (`diagnosis_dispatch.py:383-389`). `run.py:3302` records it as `terminal_stop`.
  - `_trigger` (`diagnosis.py:45-57`) does not count it as an exhaustion, so no new diagnosis starts. It is not in `INVALID`, so relaunch and transfer can repair it.
  - The test now goes through `diagnosis_dispatch.dispatch` (`test_stream_d_held.py:335-349`).
- **m4 and m6:** the design now matches the code's looser rules (design `:433-445`); m4 has a gap, see Major A.
- **Template-root prefix:** fixed with `re.fullmatch(re.escape(name) + r'-r[1-9][0-9]*', child)` (`batch_holder.py:191`).

## Findings

**Major A (not blocking): the transfer refusal list misses some retirement labels the design says must refuse.**
- **Where:**
  - `factory/batch_transfer.py:221-223` refuses only these four `terminal_stop` labels: `retired_not_converging`, `retired_factory_bug_limit`, `factory_bug_history_invalid` and `diagnosis_input_invalid`.
  - The design (`batch-carry-over.md:435-436`) says "Sealed cards and scientific retirement … refuse".
- **What gets through:** stopped cards with any of these labels still transfer and resume:
  - `retired_no_progress` (`extensions.py:392`, `:399`);
  - `retired_extension_limit` (`extensions.py:387`);
  - `retired_diagnosis_malformed` (`diagnosis_dispatch.py:323`, `:355`).

  ENGINEERING §3 says "No progress means the case retires."
- **Why it doesn't block:**
  - The commitment is carried and nothing is regranted.
  - `extensions.propose` re-derives both extension retirements from the carried history, so the case retires again.
  - The real cost is one wasted worker launch.
  - One exception: `retired_diagnosis_malformed` is computed from closed routes. In a new release the route set may differ, which could reopen diagnosis spending within the case's existing commitment.
- **Fix:** replace the list with a rule. Refuse any `retired_*` except `retired_batch_bound` (the deadline stop that must resume), plus the two invalid labels. Add one subtest to `test_sealed_and_retired_cards_refuse_before_export`.

**Minor B: no test reaches the m3 fix, but the disposition says it has "regression coverage".**
- **Where:**
  - The new check is at `batch_transfer.py:103-104`.
  - The test is `test_batch_transfer.py:145-147`.
  - The disposition says "with regression coverage" (`diff-1.md:177-178`).
- **What happens:** the test does refuse, but the refusal comes from `batch_service._load` (`batch_service.py:156`, "invalid batch journal"). That's because the imported `j-r1` queue row loses its derivation when `imported_derivations` is removed. Line 104 never runs. Deleting lines 103-104 would leave the suite green.
- **Fix:** use a carried target whose `import.json` has inherited latches but no queued imported child. For example, import only `j` after `derive`. With no queue row, `_load` accepts the journal without `imported_derivations`, so line 104 is what refuses. Also correct the disposition text.

**Minor C: `factory_bug_resume_io_wait` is a new public `terminal_stop` that nothing else documents.**
- **Where:** it appears only in design `:447-450`. The interfaces §8 and stream-d addenda don't mention it, although the design asked that the parallel literal `retired_factory_bug_limit` be documented there. `batch_status.py:23-26` has no mapping for it.
- **Effect:** status shows it as a raw, unmapped stop rather than as a wait.
- **Fix:** add one line to each addendum and one status mapping.

**Minor D: a deadline refusal can still report the wrong reason.**
- **Where:** `batch_transfer.py:181` (`frozen_manifest`) runs before the deadline check at `:188`.
- **Effect:** if the target is past its deadline and the old release directory is gone or fails to verify, the caller gets `ValueError('batch transfer refused')` instead of `MoneyWait('retired_batch_bound')`. This is a narrower version of m1.
- **Fix:** none needed now; note it next to the release-directory dependency in the design (`:452-454`).

**Nits:**
- `diagnosis.py:463-468`: an `OSError` while reading `factory-bug-resumes.json` (for example a transient EIO) is treated the same as a missing file. Both become the permanent `factory_bug_history_invalid`. This was already the behaviour before m5, which was about writes; I note it only because m5 split read and write failures elsewhere.
- `diagnosis.py:485-488`: if the scorecard write fails on the fourth-admission retirement, the result is `io_wait`, not the retirement. Relaunch retires it correctly, so no change is needed.
- The template-prefix fix (`batch_holder.py:191`) has no test for a root `a` alongside an unrelated root `a-rx`.
- The nits diff-1 listed and the disposition deferred (status presentation, malformed-manifest `AttributeError`, tiny wrappers): agreed, not blocking.

## Requirements against the code

| Requirement | Status |
|---|---|
| Same continuing case and owner, with a new reservation | Met and tested over two hops (`read_import:135-138`, test `:110`, `:164-171`) |
| Cumulative money, no regrant | Met; inherited debit equality tested (`:152`, `:172`); omitted owner charged (`:120-126`) |
| Authenticated history, generation and derived latch | Met; the two-hop latch is tested. The m3 direct check is not tested (Minor B) |
| One launch path | Met; `reserve` → `prepare` → ordinary `authorize_locked`, `_post`, `bind` and `install`; no new launcher |
| 3 lifetime factory-bug admissions, then retirement | Met and tested (unchanged since diff-1); io-wait now repairs without using up an admission |
| Holder and diagnosis activation off | Met; no flag changes in `19f1c94..018e1a1` |
| Murphy row `new-batch-service-4` stays open | Met; no closure claimed |

**Zoom-out:** the fixes are small and placed correctly: +8 lines in transfer, +12 in diagnosis, a one-line holder change. No new module, wrapper or launch path. Major A's fix would replace the label list with a rule, which is shorter than the list. **Implementation readiness:** the design clarifications remove the m4 and m6 ambiguity. Major A is a place where the code drifted from the design, not a gap in the design. **Heilmeier:** unchanged from diff-1; adequate.

## Behaviour declined as out of scope

- A real held transition, a real deadline-stop artifact, and Murphy row closure. These are saved artifacts with authored lifecycle overlays, and closing on them would break ENGINEERING §2.
- Item 8 scenarios 5 and 6, causal waste attribution, and filling the eligible and failure sets.
- Who triggers relaunch of a `factory_bug_resume_io_wait` checkpoint, and who triggers `reserve(name, g0)` for an imported checkpoint that was never queued. Both depend on coordinator activation behind `HOLDER_ENABLED`.
- Restore-key rotation, and keeping the old release directory on the control VM (now documented).
- Live diagnosis, publication or deletion, and any paid qualification.

## Disposition guidance

PASS: merge is allowed under ENGINEERING §1, subject to founder and branch rules (no push, no `main`). Major A is recommended before the first real carried batch. Minor B and Minor C are cheap. No further fresh diff review is required unless Major A's fix is made, since it changes the transfer refusal path.

## Implementation disposition

Accepted PASS; no blocking finding remains. No production changes follow this
review. Per the task's stop condition, the remaining non-blocking findings are
recorded for follow-up before live carry-over activation.

Major A: accepted. Before the first real carried batch, replace the retirement
deny-list with rejection of retired_* except retired_batch_bound, add coverage,
and obtain the fresh review required for that change. This increment does not
enable the holder or diagnosis or claim real carry-over qualification.

Minor B: accepted. The existing missing-latch test is intercepted by journal
validation; it does not directly cover the added snapshot check. This corrects
diff-1's disposition claim of regression coverage for that particular check.
Follow-up should use an imported parent without a queued child.

Minor C: accepted for follow-up: document factory_bug_resume_io_wait in both
interface addenda and map it to wait in status. Minor D: accepted: predecessor
verification can precede deadline refusal, so a missing old release may mask
the deadline reason. The old release must remain available as already documented.

Remaining nits are accepted as non-blocking and deferred. All stated scope
exclusions remain in force. No Murphy row is closed, and no merge or push is
performed.
