# Retain the writer's failed contract check

## Problem and bounded slice

When an extra writer round produces an invalid case, keep the actual contract
failure so a restart cannot lose it or evaluate it again after publication.
Today write_and_attack stores only validation_problems in its mutable writer
receipt. The extension's Records collector begins after stress, which this case
never reaches. That leaves no bound G1 evidence for terminal outcome completion.
Re-running G1 only at terminal completion would use current settings/version and
could contradict the earlier rejection; retain the observation that rejected the
writer, including failures caused by run settings rather than case content.

This is the first, independently testable increment of rejected-writer outcomes:
durable failed G1 observations only. It does not complete the history, infer a
stress result, retire a case, or claim to remove the existing terminal hold.
Next increments cover early gates/saved cheats, then terminal outcome publication
and the progress decision. Partial/legacy reconstruction remains separate.
Lane 1 owns public-match, scored stress and post-extension factory-bug resume.
No activation, limits, attribution, schema or scientific-version change.

## Change and deletion

Add an optional writer_g1 keyword callback to write_and_attack. At its two
post-writer G1 checks (fresh completion and completed/done-writer recovery), call
(writer_g1 or g1)(c). No prototype or ordinary gate check changes. The default
retains precisely the existing ordinary behavior. The package passes a callback
bound to its already-created Records object; no context attribute or global
monkeypatch is installed. This removes the gap between the package collector and
the validation it owns, without adding another validation or retry loop.
The binding is `lambda c: records.writer_g1(c, lambda: r.g1(c))`, resolving r.g1
at invocation time. The extension path does not set precheck_problems today;
the callback nevertheless preserves G1's existing shortcut behavior unchanged.

Add Records.writer_g1(c, invoke), scoped solely to these checks. First load G1
using the existing digest/support/case/version validation. A present record must
be a scientific failure (ok is False); otherwise refuse extension_snapshot_changed.
Restore its card/context using existing Records.restore and return its tuple,
without invoke. The callback is never used once a stress record exists, because
the package already skips write_and_attack then. An earlier failed G1 cannot
reach stress; pass results deliberately are not saved here, so this slice cannot
replay a pre-stress card projection during final gate traversal.

For a missing record, take the existing inventory/card/case baseline, call
invoke once, and preserve its exceptions. Only a False result accepted by
comparison._pending is saved with Records.save('G1', ...). True and pending-shaped
returned results are returned unchanged without a record. Check case_hash is
unchanged before saving, as Records.capture does. A capture-side failure
propagates without adding retries; ordinary G1 owns its existing contract retry.
There is no new money/model call. The result is published atomically before
write_and_attack writes phase=validated, so a kill after publication resumes from
the durable failure. A kill before publication may repeat the deterministic G1
check, as today. No scored failure is silently deleted or replaced.

Records already bind writer_operation_id, round, case_hash, scientific_version,
actual info, supporting case bytes and inputs. G1 does not consume freshness.jsonl;
this is the existing G1 identity, not a new identity rule. Direct writer_g1 version
drift refuses with extension_comparison_pending. Through package.run that label
is caught by the existing handoff, then stress refuses extension_execution_pending
because the receipt is still a writer. Test these labels at their respective
layers; this slice does not resolve that already-deferred route.
Missing/tampered/symlink support refuses through the
existing Records validator. Do not reconstruct legacy G1 observations from
validation_problems: an already validated/exhausted receipt with no record keeps
its current stop, for the later reconstruction/terminal slices.

The existing package stress adapter and terminal labels remain unchanged. On a
fresh G1 rejection the writer receipt is still validated/exhausted and history
is still open. This increment supplies authenticated science for the next
terminal producer, rather than assigning a result to an unperformed stress stage.

## Exams and delivery

Tests live in tests/factory/test_stream_d_writer_g1.py. Reuse saved practice bytes
and the 5813be ledger from test_stream_d_execution/runtime, real extension
admission, reservation and complete_writer, and REAL_G1 from execution. The saved
practice case has the real G1 failure `case.json source differs from the run argument`;
assert that exact problem list, without calling it a case-content defect. The
authored writer changes draft.txt
so it is not the unchanged-writer terminal case. Set manifest0 from the real bench
manifest. Author only external writer completion, as existing execution tests do;
no stress, gate model, Docker worker or network call is permitted.

- Fresh writer: actual package.run and write_and_attack reach real G1 failure.
  Assert one builder, no attacker/early gate, validated/exhausted writer receipt,
  one G1 record with the real problems and case/support bytes, no stress record,
  no outcome. Preserve the existing stress adapter refusal rather than replacing
  it with extension_incomplete in this slice.
- Completed-writer and done-writer recovery: change the draft before completion
  or the authored writer_call_done acknowledgement; real completion and G1 run.
  Assert no builder/attacker, retained real failure and unchanged terminal hold.
- Kill immediately after the record rename (wrap save, then raise Killed before
  the writer receipt changes). Resume with g1 set to forbidden. Assert the same
  record bytes, real validated/exhausted receipt, no second writer or G1 call.
- Kill before record publication: no record; resume runs real G1 once and saves.
- Existing validated/exhausted receipt without a record: no inferred record and
  no G1 invocation. This is explicitly deferred legacy reconstruction.
- Authored pass control: no record, ordinary early/stress handoff preserved.
  Authored pending-shaped return and raised InvalidInfra/BudgetError controls:
  no record and exact returned tuple/exception; no new retry.
- Tampered/missing/symlink support, wrong case and changed G1 version refuse
  before invoke. A pass-shaped existing record refuses rather than being reused.
- Existing unchanged-writer, freshness-only, execution, retry and ordinary runtime
  tests retain their assertions. Verify both callback sites, and default calls
  never use the collector. No gate_state cache/version change.

Midterm: real failed G1 and the after-publication restart exam. Final: exact full
suite with unique committed log/record, then fresh diff review. At most two rounds
per design or diff; a round-2 blocker goes to the parent. Merge land9 into this
branch before implementation, and newest factory-simplify before handback.

Risk: accidentally retaining a pass and later restoring a stale pre-stress card;
the failure-only rule and pass-control test prevent it. Payoff: later terminal
completion can consume evidence without rerunning a rejected writer or contract.
Engineering estimate: 2–3 hours including one suite/reviews, within the larger
rejected-writer effort estimate. Runtime cost: one local evidence copy per failed
contract, no new model spend or allowance. Supports Murphy 9/13, closes none.
No real-run failure or new Murphy closure is claimed by this static code finding.
