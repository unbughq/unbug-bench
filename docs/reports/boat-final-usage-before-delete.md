# Boat retirement and historical budget debit — offline handoff

Owner branch: t3/pilot-admission-cleanup-settlement. Merged e62a5c4 then d3bf433
by fast-forward in the existing prepared worktree. Included cc78673's exact founder
decision as 7d4917b. No other checkout, factory-simplify merge, main/push, live
provider/control-VM/model action, worker allocation, secret access, deploy, unlock
or activation. README/EXAM, old archives and root scoreboard files were not edited.

## Runtime correction

The existing bounded practice/pilot path now collects, fences, observes completed
non-force stop, durably captures exact stopped lifetime usage, verifies deletion,
and settles. Nonbounded/Hetzner paths retain existing behavior; no new launcher,
ledger, money authority, dependency, nonce or token protocol.

boat-call enforces the existing worker lock/fence for entering/mutating commands.
Inherited normal-owner authority requires a matching regular read-write lock FD
and actual Linux /proc/self/fdinfo WRITE/FLOCK evidence; it never upgrades SH.
At the recomputed started+2700 deadline only exact canonical DELETE may bypass
busy EX after independently validating active policy/operation, ownership,
creation, spend envelope, immutable marker and deadline. Version check precedes
O_EXCL claim. The wrapper's unique intent winner alone calls DELETE and records
metering-bypassed for an emergency. The fenced lifecycle never preclaims.
No-ID uncertainty never submits another request; a saved request only polls its ID.

Retirement generation, source/config/launch/creation hashes, boot and original
monotonic/UTC windows survive restart. Meter budget remains <=120s before D-180;
query deadlines/cancellation allowance are bounded, lock acquisition is NB, and
unused meter allowance cannot enlarge the existing 60s delete query budget.
At/after D the safety path skips meter/inventory work, with its unique 5s command
budget plus existing cancellation bound. Emergency bypass prevents exact settlement.
A safety-deleted worker without verified collection returns failure, including replay.
Controller resumption is fenced; collected markers are not cleared after retirement.

Schema1 accepted settlements/no_creation remain valid. Any new retiring marker
requires complete schema2 stopped_usage_then_deleted authority: raw public meter,
stop/status/info projections, atomic proof-last hashes/bindings, completed exact
deletion and full inventory absence. There is no deleted-ID usage fallback for
new evidence. Ledger-first debit/mirror replay remains permanent and idempotent.

## Explicit historical disposition

The founder's exact bx_z4wktrbn decision is included, not applied live. The command
`bin/boat-spend --record-approved-legacy-debit` accepts no caller-defined scope or
amount. It verifies the pinned decision and exact historical canonical spend SHA,
unique creation/monitor binding and completed deletion before changing only that
one unbound finished row. It retains the entire original row snapshot, all spend
and provider files, actual_spend_usd=null and actual_charge_status=unknown.

status=budget_debited is distinct from exact provider settlement. Its permanent
$0.036 budget debit consumes the original $5 ceiling, leaving $4.964 BEFORE other
liabilities. A larger later caller cap cannot replenish it. finish/settle/record
replays validate then return without evidence reads, provider calls or writes.
Other unknown liabilities remain blocking. No payment/top-up, increased allowance,
generic writeoff, balance-delta settlement or fabricated actual charge is added.

The initial-application test uses AUTHORED filesystem/digest transport with real
retained metadata/deletion observations. Exact raw historical spend bytes are not
available locally, so no recreated metadata JSON is claimed to hash to the approved
SHA. The real tool requires those actual bytes; root handles live application.

## Review and test evidence

Original provider design reviews1/2/3 passed before implementation and were not
repeated. Historical delta design reviews1/2 accepted/resolved both findings.
Verbatim records:
- docs/reviews/boat-final-usage-before-delete-legacy-design-1.md
- docs/reviews/boat-final-usage-before-delete-legacy-design-2.md
- docs/reviews/boat-final-usage-before-delete-diff-1.md (main implementation PASS;
  initial-application/deletion-evidence test nit accepted and implemented)
- docs/reviews/boat-final-usage-before-delete-diff-2.md (uncollected safety replay PASS)
- docs/reviews/boat-final-usage-before-delete-diff-3.md (delete budget clamp PASS)
- docs/reviews/boat-final-usage-before-delete-diff-4.md (retained-meter fresh-recheck refusal PASS)
- docs/reviews/boat-final-usage-before-delete-diff-5.md (runtime packaging preservation PASS)
No finding was rejected. No accepted review was rerun.

Focused checks: retirement 15 on Mac (2 explicit Linux-only skips), historical debit
5, settlement14, practice15, holder60, control-resume24, inventory10, worker-release9,
wrapper2, launch-manifest2 and isolation26 pass. Launch-guards passed in445.0s with
no real Boat calls. Red tests preceded the provider seam changes, including missing
retirement support and the179.999s-vs60s delete-budget regression. The temporary
legacy /var alias regression was corrected and isolation26 passed afterward.

Local Linux positive evidence uses an existing image, read-only source mount,
--network none, and disposable tmp files; no control-VM access. It exercises actual
WRITE FD proof, no SH upgrade, busy EX/two real wrapper contenders/one provider
invocation, normal stop/meter/delete/settlement without deleted usage, and negative
proof/authority/replay controls. The provider executable and lifecycle layouts are
AUTHORED; saved public Boat DTOs and kernel locks are real. Early python-slim attempts
lacked ps; the final local image contains the existing process helper prerequisites.
Final candidate Linux record/log: /tmp/boat-final-usage-linux-candidate-20261104T004847Z.{json,log}.
Earlier records remain preserved at /tmp/boat-final-usage-linux-20261104.{json,log}.

One uncached exact-head full suite follows the commit containing this report, using
shared TEST_SLOTS with no lockf and UNBUG_LOCAL_DOCKER_SMOKE unset. Authoritative
HEAD/tree, command, exit, times and output:
/tmp/boat-final-usage-suite-20261104T004847Z.{json,log}.
The final handback states its result; this report does not substitute for that run.

## Precise remaining live gates

Root must integrate, re-cut reviewed runtime pins (prepared e62a5c4 pins are stale
and intentionally not deployed), then apply the exact approved historical tool to
retained live evidence. Missing/mismatched evidence refuses; no alternate row/cap
is authorized. Existing cleanup/ownership/unlock, credit/top-up, containment,
snapshot/proxy, collection and absolute timing prerequisites remain.

The new runtime still requires the authorized no-model normal lifecycle proof on
the deployed control VM: verified collection, real completed non-force stop,
stopped lifetime meter with same stop after recheck, durable bytes/hashes, actual
exact deletion/absence inventory and schema2 cumulative settlement. Deadline safety
must retain unknown liability when metering is bypassed. Local Linux tests are
kernel/transport evidence, not live provider qualification. Practice follows the
required passing smoke; no fleet authority is implied. Murphy17/49/51 remain open.


## Canceled non-final attempt and resolved replay blocker

The first full attempt tested c1b2106 until an independent final audit found that
an existing committed meter's failed fresh stop recheck was swallowed before an
ordinary DELETE. That could let old receipt bytes settle after an observed resume.
A red regression demonstrated it. The corrected helper propagates the error and
refuses ordinary deletion, preserving the proof; recovery needs a successful
recheck in the original window, or deadline deletion's winner invalidates billing
proof and retains the hold. The real Linux crash-after-proof/before-DELETE exam
now observes resumed-state refusal and unchanged-proof recovery. Fresh scoped
review4 passes without reopening accepted scopes.

That non-final suite was interrupted (exit130,206.530s); it is NOT a pass or the
qualifying final suite. Preserved provenance:
/tmp/boat-final-usage-suite-20261104T001228Z.{json,log}.
Its already-passing Linux14 record is also retained:
/tmp/boat-final-usage-linux-candidate-20261104T001228Z.{json,log}.
The corrected final candidate's Linux15 and full run use the001745Z paths above.
No live worker/evidence or historical ledger was changed during this repair.


## Full-run packaging feedback and corrected final candidate

36fd6f8's uncached full attempt completed195 scripts with5 failures (exit1,
1055.019s), retained at /tmp/boat-final-usage-suite-20261104T001745Z.{json,log}.
This attempt is NOT a pass. Failures were exam-round/transfer/outer-callers copied
standalone wrappers missing the new lifecycle import; batch-launch's unchanged
adapter refusing a newly introduced docs source root; and preflight's stale
retained-host package plus outdated missing-founder-decision assumptions.

Runtime correction preserves the standalone interface through lazy loading;
managed state never gains an import-error fallback. An identical approval copy
under factory/ carries the same4e5caa... pinned bytes through the already-owned
factory source root and host trust inventory. The original report, raw hash,
historical scope and old artifacts are unchanged. No adapter ownership expansion
or new installer/launcher was added.

Historical preflight archives are verified intact and refused against changed
runtime, not repinned. The positive dispatch matrix uses the existing builder on
the current committed public source with an explicitly AUTHORED test policy;
these are contract tests, not a claim of deployed evidence. Missing-decision tests
use an absent isolated file. Focused reruns: preflight28, outer-callers8, transfer5,
batch-launch8, exam-round pass, wrapper2, historical debit5, launch-manifest2;
real local Linux retirement15 also passes after the packaging change.
Fresh scoped review5 passes. No new full run began before these repairs/tests.

The final qualifying Linux/full records use004847Z paths above. The001745Z Linux15
record remains valid earlier kernel evidence but belongs to36fd6f8; it is preserved.
All partial/failed logs remain available. Root still must recut real deployment
pins; the test package is never deployed or used to unlock a live holder.
