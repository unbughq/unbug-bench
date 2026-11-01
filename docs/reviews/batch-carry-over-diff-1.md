**Verdict: BLOCKED.** One blocking finding is open: the design requires a test that moves a case across two releases, and that test does not exist. The code for that path looks correct when I trace it by hand, but nothing runs it. Everything else matches design 4. That includes design-review-4's two non-blocking findings, F1 and F2: both are fixed in the design and in the code.

---

# Diff review 1: batch carry-over (`56b4c13..19f1c94`)

**Reviewer:** fresh goldfish. Mode: REVIEW. I read the `zoom_out` and `implementation_readiness` personas first and applied the zoom-out, implementation-readiness and Heilmeier standards. The review was read-only. I made no repo writes, started no workers or subagents, and made no paid or model calls.

**What I read:**
- `docs/ENGINEERING.md`.
- The design, `docs/designs/batch-carry-over.md`, in full, including "Design 4 exact integration decisions", the review-4 clarifications and the implementation clarification.
- `docs/reviews/batch-carry-over-design-4.md`.
- The carry-over addenda in `interfaces.md` and `stream-d.md`.
- The Murphy row `new-batch-service-4`.
- The whole implementation diff, not just the last commit:
  - `batch_transfer.py`, `batch_money.py`, `batch_service.py`, `batch_holder.py`, `batch.py`;
  - `job_config.py`, `restore_ledger.py`, `launch.sh`, `run.py`;
  - `diagnosis.py`, `diagnosis_dispatch.py`;
  - `key_holder.py`, `account_handoff.py`, `coordinator_inventory.py`, `batch_status.py`, `launch_manifest.py`;
  - all the test changes.
- The surrounding code these touch: `_source`, `_post`, `reserve`, `_load`, `_enqueue`, `load_locked`, `advance_locked`, the run.py stop handler, `record_exhaustion` and `_trigger`.

**Suite record:**
- `docs/reports/batch-carry-over-suite-20261031T143330Z-19188390.json` records 159 scripts, exit code 0, on code commit `99007fb`.
- The log's SHA-256 matches the record (`4dee55a9…`), and the log ends "159 test scripts run; 0 failed."
- `git diff 99007fb 19f1c94` touches only `docs/reports/`, so the tested code is the code under review.
- Of the earlier runs, `140808Z` (hash matches) and `143000Z` are both marked superseded; `143000Z` is marked aborted.
- As an extra check only, I re-ran `test_batch_transfer.py` (9 OK) and `test_stream_d_held.py` (19 OK). The working tree stayed clean.

## Requirements against the code

| Requirement | Status | Where |
|---|---|---|
| Same continuing owner and case across releases; new reservation, revision 1 | Met | `batch_transfer.py:218-221`, `read_import:132-135`, `job_config.py:100-108` |
| Cumulative spend; omitted owners still charged; no new allocation | Met | `carried_debit` at `batch_transfer.py:226-229` and `:137-138`; `batch_money.aggregate`; imported names cannot get fresh money (`batch_money.authorize_locked`); a root kept only as a template for an imported child refuses launch (`batch_holder.py:190-192`) |
| Generation, history and one-child latch for derived jobs are authenticated | Met in code | snapshot digest pin; `latches()`; `_load` checks equality; `_enqueue` refuses to derive again from an imported parent |
| A queued child transfers only if it already has money reserved; any operation refuses (F1) | Met and tested | `batch_transfer.py:209-210`; `test_queued_child_with_any_operation_refuses` |
| One checkpoint launch path | Met | `reserve` → `prepare` → ordinary `authorize_locked`, `_post`, `source_directory` and `bind`; no new launcher |
| D: at most 3 lifetime admissions, the 4th retires | Met and tested | `diagnosis.py:478-484`; `test_three_distinct_resumes_then_fourth_retires_before_work`; the producer does not treat `retired_factory_bug_limit` as an exhaustion (`_trigger`) |
| Legacy paths refuse carry-over and derived names before touching money | Met and tested | `batch_money.py` `authorize`; `batch.py:146-147`; the same-release check is kept |
| Schema-1 source money refuses | Met in code (load_locked's schema-2 header check), **not tested** | see M1 |
| Freeze source after export | Met | `money.locked(read_export=False)` refuses after export; `_post` guards the shared-lock path |
| Holder and diagnosis activation unchanged | Met | `HOLDER_ENABLED = False` (`batch_holder.py:26`); no flag changes in the diff |
| Murphy row stays open | Met | `murphy-register.md:67` is unchanged and still `open` |

**Design-4 non-blocking findings:**
- **F1 (rule for moving a queued child again):** resolved. The design's review-4 clarifications say any operation refuses. The code (`batch_transfer.py:209`) and a test match.
- **F2 (derived import needs `replacement_policy.enabled`):** resolved in the design (review-4 clarifications) and in the code (`batch_transfer.py:40-41`). There is no test; see M1.
- **Review-4 nits:** all fixed in the design text.

## Blocker

**B1. The design's test plan requires a two-release transfer, and there is no test for it.**
- **Where:** `tests/factory/test_batch_transfer.py`. Every test there does a single source → `fixed` transfer.
- **What the design requires:** lines 323-326 list "one-child latch after two releases" in the mid-term exam.
- **Code that no test runs:** a second transfer goes through all of this:
  - checking the chain of earlier manifests (`check()`, `batch_transfer.py:45-58`, and the recursion in `predecessor`);
  - the `prior_import` pin and the merge of inherited and local derivations (`latches()`);
  - charging an inherited debit through `aggregate(snap['money'])`;
  - the D3-M3 refusal to re-export an imported checkpoint that never ran (`batch_transfer.py:212-213`);
  - `source()` → `snapshot()` reading the import receipt of a source that was itself an import;
  - `job_config.install` with saved money from an intermediate batch.

  The worker-side D tests do author a second hop (`fixed` → `fixed-again`). The host transfer has no second hop at all.
- **What I checked by hand:** I traced S → T1 → T2 through `prepare`, `snapshot`, `read_import`, `load_locked`, `_source` and `source`. I found no defect. A hand trace is not a test, and these are money and latch rules.
- **Fix:** add one host test using the existing fixtures. It should:
  - transfer S → T1, run and collect one local successor in T1, then transfer T1 → T2;
  - assert that T2's aggregate equals S's aggregate, so the inherited debit is carried and not counted twice;
  - assert that T2 still holds the S parent's latch, so the imported parent cannot derive another child in T2;
  - assert that T1 → T2 refuses when the imported checkpoint has no local acknowledged successor (D3-M3);
  - assert that a queued null-generation child with no operation can move again.

## Majors

**M1. Refusals the design asks for are not tested.**
- **Where:** `tests/factory/test_batch_transfer.py`.
- **What the code does:** each of these refusals exists in the code, but no test covers it:
  - changed non-money job fields or args between source and target (design line 324; code at `batch_transfer.py:203-205`);
  - schema-1 source money (D3-B1, line 365);
  - a derived import when the target has `replacement_policy.enabled=false` (F2, line 420);
  - a sealed or retired source card, i.e. one whose status is not `stopped` or whose `terminal_stop` is on the refusal list (lines 158-161; `:215-217`);
  - a source stopped by `retired_batch_bound` being admitted through install's import exemption (`job_config.py:87-90`);
  - a fresh, unrelated root in a carried target still getting ordinary admission (implementation clarification).
- **Fix:** add a small table-driven test. Each case refuses before export, and the test asserts that `export.json` is absent.

## Minors

**m1. A carried target past its deadline returns the wrong error.**
- **Where:** `batch_transfer.py:185`, which runs before `batch_holder.py:195`.
- **What happens:** `prepare` runs first and raises `ValueError('batch transfer refused')`. The caller never sees `MoneyWait('retired_batch_bound')`.
- **Effect:** on a carried target, the key-holder reply reports a transfer refusal rather than retirement by the batch bound. `schedule_waits` swallows both, so nothing hangs. But the reason is misleading.
- **Fix:** check the deadline before `prepare`, or raise the same `MoneyWait` from `prepare`.

**m2. The target manifest's own `requested_total_usd` for an imported root is never checked.**
- **Where:** `batch_service.resolve_job`, which overrides `requested_total_usd` with the pinned commitment, and `batch_transfer.py:203-206`.
- **What happens:** because of the override, the check at `:206` only compares the pinned value with itself, so it always passes. The raw value in the manifest's `jobs[root]` can differ from the source authority's commitment, although design lines 102-104 require them to match.
- **Effect:** none on money, because imported names can never get fresh money. But the published manifest can be wrong without anything noticing.
- **Fix:** compare `record['jobs'][name]['requested_total_usd']` itself for imported roots.

**m3. The snapshot does not check that a source with an import receipt also has its inherited latches.**
- **Where:** `batch_transfer.py:105-106`.
- **What happens:**
  - Design line 124 says `imported_derivations` must equal the latches projected from `prior_import`.
  - `_load` checks this only when the key is present.
  - So a source with `import.json` but no `imported_derivations` key in its journal would snapshot `{}`.
- **Why it doesn't bite today:** every way to make an exportable successor goes through `reserve` → `prepare`, which repairs the journal first. Also, `_lineage` would refuse to move an orphaned child.
- **Fix:** add a direct check that if `prior_import` is set, the journal's `imported_derivations` equals `latches(prior_import)`.

**m4. Which source cards may transfer is a deny-list, but the design describes an allow-list.**
- **Where:** `batch_transfer.py:215-217`.
- **What happens:** the design (lines 158-160) names deadline stops and factory-bug holds as resumable. The code refuses four retired or invalid labels and accepts every other `stopped` card, including `budget_exhausted`, `paused`, `provider_wait` and `seal_error:*`.
- **Effect:** this is safe for money and lifetime limits. Exhaustion and the ledger travel with the case, so the case re-exhausts.
- **Fix:** either amend the design to say this, or switch to an allow-list.

**m5. The crash test does not go through dispatch, and through dispatch the result is worse.**
- **Where:** `test_append_ahead_collected_checkpoint_repairs_through_money_transition`, `diagnosis.py:499-500` and `diagnosis_dispatch.py:338-339`.
- **What happens:**
  - The test fakes "death after the history append, before the card is written" by raising `OSError` while calling `resume_factory_bug` directly.
  - Through the real `dispatch`, that same `OSError` becomes `diagnosis_finding_invalid`, then `invalid(c)`, then the permanent stop `diagnosis_input_invalid`.
  - By then one admission is already recorded, and the case can never be transferred again.
- **Effect:** a real SIGKILL is handled correctly. A disk error on the scorecard write strands the case permanently.
- **Fix:** let an I/O error on the scorecard write after a durable append propagate as an operational failure, not as invalid input. At least say this in the test's docstring.

**m6. Replaying an existing admission matches more loosely than the design says.**
- **Where:** `diagnosis.py:470-477` and `:276`.
- **Design:** lines 296-305 say the row may run one ahead only if its `source_generation` equals the current source or the `old.source_generation` of the latest verified transition.
- **Code:** it accepts a match against any binding anywhere in the verified chain. The one-row-ahead count limit and the requirement that the replayed row is the last row still hold, so the risk is low.
- **Fix:** tighten the check to the design's rule, or amend the design.

## Nits

- `batch_status.py:216-218`: on a carried target, status lists two kinds of rows as "not collected" forever: roots kept only as templates, and children of imported parents that were left behind. Neither can ever launch. Imported cards also don't appear until their first local collection.
- `batch_holder.py:191`: the template-only check matches by string prefix, so a fresh root named `a` is wrongly refused if another root has a name like `a-rx` (allowed root grammar).
- `batch_money.py:53` and `resolve_job`: if `carry_from` (or its `jobs`) is not a dict, `.get` raises `AttributeError`, which `check_manifest`'s handler does not catch. It still fails closed, just with the wrong error type.
- Three tiny helpers could go:
  - `batch_transfer._usd` is a new formatter for nine-place amounts; `batch_accounting` already formats amounts that way;
  - `money.resolved` and `batch_transfer._local_source` are one-line wrappers that add only an indirection.
- Running `prepare` on every reserve (verifying the old release, reading the tar member, re-taking the snapshot) is intended by the design. The cost: the target can only admit work, including unrelated fresh roots, while the old release directory stays on the control VM. That operational dependency should be written down.

## Scope assessment (honest)

- The tests use saved real card, ledger and ciphertext bytes from the 5813be/practice fixtures. Batch transitions, held findings and lifecycle fields are authored on top, and the test docstrings say so.
- No test proves a real publication, deletion, live diagnosis or real held transition, and the code does not claim it.
- Keeping `new-batch-service-4` open until a separately authorized Item 8 scenario 5 run and a deadline-stop artifact exist is correct. Closing it on authored overlays would break ENGINEERING §2.
- **Heilmeier:** the design states the objective, the existing contract, the approach, the $0 cost, a session estimate, the exams and the risks. That is enough.
- **Zoom-out:** the transfer is kept in one 254-line module, with narrow calls into the existing seams, and there is no second launch path. Whole-batch freeze avoids exporting owners one at a time. Apart from the nits above, I found no wheel reinvented and no speculative abstraction.

## Behaviour declined as out of scope

- **Murphy closure and real held or deadline-stop qualification.** The design explicitly defers these to separately authorized paid work.
- **Who triggers `reserve(name, g0)` for an imported checkpoint that was not queued.** No coordinator auto-launch is specified. Operator- or activation-time work, behind `HOLDER_ENABLED`.
- **Item 8 scenarios 5 and 6, and causal waste attribution.** The design explicitly excludes them; findings keep their empty eligible and failure sets.
- **A founder-approved target that adds a fresh root identical to an omitted source root.** It gets a new case ID and is charged against the same cumulative envelope, with the old debit kept. It is money-safe and comes from manifest authority, not from this code.
- **Restore-key rotation and host-side ABA checks across the import chain.** Rotation is excluded by the design. ABA is covered by content-addressed generations and the worker transition-history check (`job_config.py:136-138`).

## What is needed to pass

1. Fix B1: add the two-release host transfer test described above.
2. M1 is strongly recommended: one table-driven refusal test.
3. Minors and nits are optional. m1 and m5 are cheap and worth doing.
4. Re-run the full suite on the new code commit and record it. Then request a fresh diff review, as ENGINEERING §1 requires after every blocker fix.


## Implementation disposition

B1: added a two-transfer host test using saved card, ledger and ciphertext bytes.
It collects an intermediate successor, carries inherited debit/latches and a
never-launched queued child, checks unlaunched checkpoint refusal, and runs the
real restore-ledger/worker-config install for the second hop. Awaiting fresh
review; this is not self-verification of the blocker.

M1: added table-driven changed-args/metadata/replacement-disabled refusals,
schema-1 and sealed/retired source refusals, deadline-stop worker admission and
unrelated fresh-root admission. The last two are positive tests: the contract
requires admission, not the blanket refusal suggested in M1's final sentence.

m1–m3: fixed deadline reason, raw root commitment validation and missing inherited
latch validation, with regression coverage. m4 and m6: clarified the design to
match ordinary stopped-card transfer and authenticated ancestral admission replay.
m5: operational admission-write failures retain held markers and propagate as
factory_bug_resume_io_wait; the append-ahead test now goes through real dispatch.

The template-root prefix nit is fixed using the derived-name grammar. The old
release-directory dependency is documented. Remaining status presentation,
malformed-manifest error-type and tiny-wrapper nits are deferred to keep this
increment focused. Accepted all explicit scope exclusions in the review: no
activation, paid qualification, causal attribution, key rotation or Murphy-row
closure is claimed here.
