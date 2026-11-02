# Practice fresh admission — offline small fix

Parent approved the small-fix exception, with no design doc, on 2026-11-02.
The old practice operation is terminal after preflight refusal. Rename the sole
permitted practice batch and case to b-plumbing-practice-2 and
case-b-plumbing-practice-2-practice. The job label remains practice. Update the
exact validator, manifest, generated holder drop-in, cleanup unit and run plan.
No new admission/reset mechanism, migration or ledger is added.

The former manifest path is removed from this source release. Even if an old
manifest remains deployed, its policy cannot activate the holder under either
old or new environment selection; legacy authorize refuses practice_admission.
Retain the old failed operation, money journal, router ledger and Boat ledger.
There is no live deployment or state mutation in this increment.

The report practice-run-20261102.md records zero old model/infrastructure spend,
zero creation records and a complete empty fleet. That specific zero-spend fact
supports the parent's cumulative $19.99 model / $5 infrastructure authority for
the replacement attempt. This is not a general cross-batch budget transfer:
nonzero or uncertain prior spend would require another disposition before launch.
The new manifest keeps the same caps, baseline zero, one worker and one-hour TTL;
the shared paid and infrastructure ledgers are unchanged. No Murphy rows closed.

Validation: test_practice_readiness exercises authenticated old-policy rejection
through holder reserve and legacy authorize under both environment IDs, unchanged
state bytes, exact ceilings, and agreement of the activation configurations.
Full-suite and fresh review records follow after the source commit.
