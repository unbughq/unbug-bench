**Verdict: REQUEST CHANGES — four Major findings block implementation readiness.** The lifecycle correction is justified by the saved evidence and fits the existing architecture.

1. **Major — Stop completion remains an unresolved provider interface.**
   [Design line 44](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:44) defers the actual stop contract until implementation. Retained provider schema already distinguishes `pending`, `failing`, `completed` and `superseded`; completed means archived. Define the pinned command, response envelope, polling interface, identity binding and exact completion predicate before coding. Explicitly test refused/failing stops with `running=false`, superseded stops and forced-stop behavior. Reusing deletion-operation fields would be incorrect.

2. **Major — The claimed exclusive ownership does not specify an enforceable retirement fence.**
   [Design line 56](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:56) requires exclusion of resume/resize, but the existing worker deletion lock serializes deletion callers; the controller uses a separate lock, and independent cleanup does not acquire it. Specify which existing lock covers stop through deletion, how restart observes durable retirement intent, and which restart/mutation paths refuse it. Add an interleaving test proving a concurrent controller or cleanup replay cannot invalidate the captured meter.

3. **Major — Deadline precedence lacks an executable time allocation.**
   [Design line 64](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:64) says cleanup wins, but existing independent cleanup starts deletion **at** the deletion deadline, while `_delete` creates a fresh 60-second budget after an unbounded lock wait and allows subprocess cancellation overhead. Define the metering cutoff, deletion time reserve, bounded lock acquisition and immediate bypass when already overdue. Test hung stop/usage and lock contention with a controlled clock; assert deletion is attempted within the specified bound and liability remains held.

4. **Major — Durable proof and crash replay are insufficiently specified.**
   [Design line 47](/Users/bugsincode/Developer/unbug-bench/docs/designs/boat-final-usage-before-delete.md:47) leaves receipt fields, hash coverage, generation binding and the new settlement schema undecided. Define these alongside strict legacy/new-basis dispatch, atomic commit ordering and rejection of stale or mismatched evidence. Also distinguish deletion acceptance **with** a persisted operation ID from acceptance followed by a crash **before** that ID is saved: current code deliberately preserves uncertainty in the latter case. Tests must cover both without promising unavailable recovery or issuing another delete.

The proposal correctly preserves cumulative debits, the unknown historical `$0.036` reservation, old settlement replay and collection-before-retirement. The preflight evidence shows preparation passed; it does not establish deployment or live lifecycle qualification. Authored stop/usage doubles should remain explicitly distinguished from real provider evidence.

Read-only review completed; no edits, tests, network, credentials or worker/model actions performed.

## Parent disposition

All four Majors accepted. No rejected finding.

1. Resolved the pinned CLI help and real read-only info/by-ID stop/lifetime meter envelopes using the existing stopped sandbox bx_sk2p68qq, without mutating it. Exact commands/status predicates, refusal/supersession/force behavior are specified.
2. Existing per-worker deletion lock becomes shared for managed entering/mutating commands and exclusive for retirement. A durable generation-bound fence survives restart; inherited-FD validation avoids an environment boolean bypass. Controller restart/worker entry and race tests are specified.
3. Specifies original absoluteD,120s meter cap, M=D-180, boundedNB acquisition,70s cancellation allowance, remaining-time propagation, original boot/monotonic deadline, and unique5s emergency delete attempt at/afterD. No preemption of uncollected work before its existing grace. Busy-meter safety invalidates its proof. Existing uncertain-delete intent is never replayed.
4. Exact marker/proof fields, hash coverage, lifecycle/source/config binding, schema1 compatibility/schema2-only new basis, atomic commit order and all deletion request crash cuts are specified. Historical legacy liability remains unknown.

No implementation, new qualification worker or model call. Revised design goes to fresh round-two review.
