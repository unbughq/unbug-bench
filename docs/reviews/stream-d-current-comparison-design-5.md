**Verdict: PASS.** The round-4 blocker (B1) is fixed, and so are M1–M4. Nothing blocking is left. One major finding remains: it should be fixed, but it doesn't block.

This was a read-only goldfish review of `t3/stream-d-gates` at HEAD `17460ea`, in Mode REVIEW. I read `docs/ENGINEERING.md`, the `zoom_out`, `design_critic` and `implementation_readiness` personas, and both standards (`heilmeier-standard.md`, `implementation-readiness-standard.md`). I then read the design and review 4, and checked them against `factory_waste.py`, `exam_responder.py`, `budget.reconcile_reservations`, `model_runtime._call`, `gate_attempt.py`, `gate_pipeline.py`, `diagnosis.py`, `diagnosis_dispatch.apply`, `extension_package.entry`/`run`, `extensions.read`, and `test_stream_d_entry.py`. I made no edits, model calls or git changes, and started no subagents.

## Round-4 fixes, checked against the code

**B1: the child could lose the "do not publish as waste" signal. Fixed.**
- **What the code needs from the child's scope.** Only `exam_responder.owner_server` reads the scope:
  - `scope is not None` picks the joined, drain-checking server;
  - `scope.mark_unpublishable('owner_drain_timeout')` is called when the drain is incomplete (`exam_responder.py:98-99, 208, 225-247`).
  - The only other user is `record_reservation`, which `model_runtime.py:399-400` calls.
- **Why the proxy covers it.** A non-None proxy that only supports `mark_unpublishable`, and for which `record_reservation` does nothing, keeps the drain safety check and its `InvalidInfra`. It also stops `record_reservation` from reading `scope.c`.
- **No stale first-stage scope.** The proxy is entered again for each stage request and bound to the parent's current `attempt_id`. The owner handler threads use `owner_context = copy_context()`, captured when `owner_server` starts, so they inherit that stage's proxy.
- **Signal ordering.** The mark is written to disk and fsynced, then acknowledged by the parent, then replayed from the file in the parent's `finally` before the scope exits. That ordering holds because `Attempt.publish` runs only when the scope exits (`factory_waste.py:83-96`).
- **Retry granularity matches today.** The scope wraps each stage invoke, the same as `gate_pipeline.py:52-58`. Each retry therefore gets a fresh `Attempt`.
- **Pipe lock.** One child-side lock serialises every request and its reply. This covers the real case of a G10 owner handler thread making a model call, which then sends a checkpoint request.

**M1: superseded entry test. Fixed.**
- The test at `test_stream_d_entry.py:291-295` mocks `extensions.read` with a malformed row.
- With a real malformed `extension-history.json`, `extensions.read` raises `extension_history_invalid` (`extensions.py:98-138`). That happens before any snapshot or evaluator is built, so the no-work assertion can be kept and made stronger.

**M2: exact status restore. Fixed.**
- `apply` sets `status='stopped'` and `terminal_stop='extension_comparison_pending'` before returning 0 (`diagnosis_dispatch.py:231-232`).
- Saving those values, and whether each key was absent, then restoring them exactly hands the writer the same card that first entry gives it (`extension_package.py:322-324`).
- Lines 651-656 make it clear that failure fields stay in the immutable diagnosis-input card only.

**M3: reconciling a dead child's reservations. Fixed.**
- `reconcile_reservations(c.work, c.ledger)` on the live owner settles from the root usage receipts. Where usage is unknown it keeps the conservative charge (`budget.py:409-426`).
- It runs only after the child's descendants are fully stopped. That matches the function's rule that it may only run under exclusive ownership.
- This partly overlaps the reconciliation already at the start of `model_runtime._call` (lines 331-334). The explicit call still covers reservation admission before `_call`, so it is harmless.

**M4: pair identity and pair failures. Fixed.**
- The pair journal's version vector comes from `_versions` on the owner's unchanged inputs. This works because `scientific_version` ignores case content.
- Pair `publish` sends operational events only.
- Any non-`BudgetError` exception that escapes compare counts as a pair attempt.
- The diagnostic index records `scope='pair'` or `scope='stage'`.

**Scope holds.**
- Only comparison, subsequent entry and routing change.
- Activation stays false, and extension limits and validators are unchanged.
- No Murphy row is closed. `new-stream-d-current-comparison-1`, the deferred factory-bug return target, is opened as a static row.

## Major (should fix; not blocking)

**M1. The "child lost" rule is broader than needed, and it contradicts a test in §8.** *(design_critic and readiness; lines 619-622 against lines 443-445)*
- **The contradiction.**
  - Round 4 says: if the child dies or IPC is lost "where no complete effects acknowledgement is available", mark the attempt `unpublishable('comparison_child_lost')`.
  - §8 asks for a killed-child test asserting "factory-failure proof still eligible".
  - Both can't hold.
- **"Complete" is undefined.** No end-of-effects message exists, so on a plain reading every child death is unpublishable.
- **Why it matters.** `factory-failures` proofs are the only way `factory_waste.eligible` lets a factory-bug diagnosis move spend onto the infra-waste line (`diagnosis.py:224-230`, `factory_waste.py:163-192`). Under this rule, every comparison child crash (OOM, broken pipe) is charged to the case and can never be claimed as infra waste. That runs against the §3 target property.
- **Where the risk actually is.** The real hazard behind `owner_drain_timeout` is work still running after the attempt ends. Once the parent has proved every descendant is gone and reconciled the ledger, attribution is complete.
- **Recommended fix.** Define "complete" as having received a stage reply (a result or a typed stop). Apply `comparison_child_lost` only when no reply arrived and the descendant check could not prove everything stopped. Otherwise publish the ordinary invalid-infra proof. Then align the line 445 test with whichever rule is chosen.
- **Why it isn't blocking.** Under either reading, no false waste is published. The round-4 section is marked binding, so an implementer would default to the conservative rule. The cost is lost attribution, not unsafe attribution.

## Nits

- **Non-factory jobs.** When `factory_job(c)` is false, the parent's `attempt()` yields None (`factory_waste.py:84-89`). The design doesn't say what the child installs in that case. It should install None rather than a proxy, so offline and non-factory runs behave as today.
- **Phrasing.** "Factory-failure proof still eligible" at line 445 also needs rewording once M1 is settled.

## Heilmeier, readiness and zoom-out

- **Heilmeier:** still fully answered. Objective at lines 475-477; current state at 17-22; risks at 24-28; cost and timeline at 459-470; midterm and final exams at 469-471.
- **Readiness:** phases, file list, exact durable effect schema, lock rule, reconciliation point and test dispositions are explicit. The only choice left to the implementer is the M1 ambiguity, and its conservative default is safe.
- **Zoom-out:** the forwarding proxy is the smallest addition that keeps the existing `exam_responder` safety branch. It reuses `Attempt`, `gate_attempt` and `reconcile_reservations`, and adds no new subsystem.

**Result: PASS.** No blocking finding is open. M1 should be fixed before implementation, or carried as a disposition in the review record.

## Writer disposition

PASS accepted. M1 resolved with the recommended narrower rule: a complete reply means a stage result or typed stop; missing reply suppresses waste only if cleanup/reconciliation cannot prove quiescence. Explicit forwarded owner_drain_timeout always suppresses publication. Non-factory scopes install None. Implementation proceeds under this clarification.
