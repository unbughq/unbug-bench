# Stream B: retain infrastructure holds after uncertain creation

## Problem and this increment

Base: factory-simplify 0c4eb3a, merged into t3/batch-service-control-vm.
The next planned work is delayed-creation cleanup/cost proof and legacy ownership.
Design review 1 identified a safe prerequisite to implement now: boat-spend
releases expired holds after one complete idle inventory page, even though a
creation reply can be lost and a worker can appear later. This discards ownership
of money without authoritative creation or deletion evidence.

Delete that release path. This increment does not implement the cleanup supervisor,
prove the cumulative USD 5 bound, dispose of the legacy launch, or enable either
activation gate. It makes progress on cleanup safety without inventing a provider
contract. No workers, paid factory calls, VM mutation, secret inspection, push or
main changes. Runtime behaviour changes only on future execution of this code;
the disabled holder gate does not gate all non-batch boat-spend callers.

## Change and what it deletes

In bin/boat-spend, remove the expired-hold inventory query and the transition
from reserved to reconciled_expired. Every reserved hold remains in admission's
sum regardless of expires_at. Keep expiry as historical metadata, existing lock,
ledger schema, same-record idempotency and ordinary --finish unchanged. A restarted
admission cannot release the hold by clock or fleet observation. This may block
capacity indefinitely after an ambiguous create; that is intentional until the
later authoritative reconciliation increment. Do not add a manual release switch.

Existing historical reconciled_expired entries are not reclassified by admission:
the deletion prevents new releases, not repair of previously released holdings.
Before deployment, inventory any such entries and qualify their disposition;
unknown historical exposure still blocks activation. Also inventory every reserved
hold, its expiry and pending-creation markers before deployment: permanently
retained holds can reduce non-batch admission capacity. No live ledger is migrated.
The --finish caller protocol remains unchanged: the guard skips finish while
new.N.pending exists. This is not a claim that direct --finish is an authenticated
cleanup API, nor that this ledger enforces cumulative batch money.

Update docs/designs/isolation-timeouts.md to supersede its expired-hold release
rule in item 6, its ledger-status schema, the TTL-backstop sentence and the
implementation-clarifications inventory paragraph. Test the changed behaviour against its retained billing/creation artifacts:
one admitted reservation, a concurrent refusal, expired hold, empty complete
inventory, repeated refusal after process restart, unchanged full hold, and then
normal finish. Historical reconciled_expired compatibility must assert that admission excludes
the entry from reserved totals, same-record re-check refuses reuse, and ordinary
--finish changes it to finished while retaining reconciled_at. This existing finish
transition is intentional under the caller's verified-deletion protocol, not an
admission-time reclassification or proof supplied by this test.
No new provider adapter, scheduler, credential path or journal schema.

## Provider evidence and residual qualification

Verbatim public pages fetched 2026-10-31 are retained in
 docs/reports/stream-b-provider-contract-20261031/{create,billing,auto-stop}.md,
with URLs, UTC fetch time and SHA256 in sources.json. Sources:
https://docs.boat.dev/api/reference/sandboxes/create-sandbox.md
https://docs.boat.dev/billing.md
https://docs.boat.dev/long-running-tasks/auto-stop.md

The provider documents auto-stop from creation/resume, independent of activity
and of the control VM. Running Boat prompts can extend it; the factory launches
commands rather than Boat prompts and does not extend or provider-resume workers.
Stopped time is not compute-billed. The stop normally starts shortly after expiry.
This is stronger than the CLI's cleanup-eligibility wording. A relative per-worker
bound, if its exceptional behaviour is qualified, can support a dollar bound even
for late creation. An absolute deadline is still useful for local cleanup policy,
not a mathematical necessity for that dollar inequality.

Remaining provider questions for the next qualification increment:

- What is charged while stop is pending/failing, and what maximum charge applies
  if archival keeps retrying? Normal stop timing is not an exceptional-case bound.
- What is the maximum paid-start charge and how is it constrained in this scope?
- What are egress and retained-storage ceilings for this no-snapshot workload?
- Can pinned CLI 1.0.85 retry a create internally, creating multiple workers?
  Qualify the CLI or use one direct API request with count=1 and a durable key.
- Verify current rates/billing granularity rather than the 2026-10-18 static table.
- Confirm no-env/direct model calls avoid AI-proxy charges for this workload.
- Can organization per-member caps supply a hard bound covering these terms?
  The docs mention such controls but this task has not qualified them.

The wallet is not a hard cap: documented grace permits negative balance. No
account-balance delta can be attributed to this batch under concurrent activity.
The current --check compares per-launch estimate with max-spend and balance minus
holds. It does NOT enforce settled + holds + new <= USD 5 across successors.
That cumulative ledger and its justified worst-case hold formula remain future
work. No missing term may be assumed zero.

The create API has account-scoped identical-body idempotency, 24-hour retention,
and early key release following pre-creation failure. A replay can create again
after those conditions. Do not replay create after the local deadline merely to
query its outcome. Label filtering can help bind workers. Read-only resolution
improves cleanup and availability; money safety can instead retain the entire
justified worst-case hold indefinitely. Neither mechanism is implemented here.

## Legacy launch: local-evidence route, not assumed provider dependency

Historical docs/reports/stream-b-preparation-preflight-20261031.json reports
b275ffccd6134a33833853ad1d31ed16 with only launch.json and controller.lock, the
lock free, no complete marker and empty inventory. Do not mark it resolved from
that historical observation. Its activation block is a review/policy requirement;
there is no batch admission scan over all non-journal legacy launches.

The current launcher writes launch.json before exec, guard_init writes ids before
creation, and guard_new opens new.N before invoking the provider. The existing
batch_holder._reconcile_one uses that local no-submission invariant under both
locks. Resume scans skip missing monitor.sh; explicit resume refuses it. This
provides a possible definitive non-creation proof without provider support.

The parent must obtain fresh read-only VM evidence: file names and mtimes, free
controller/operation ownership where applicable, public allowlisted launch
argv/environment (never dump arbitrary values), and provenance/hashes of the
launcher actually deployed when this record arose. Establish that the directory
has not been pruned/replaced and that the relevant ordering invariant applied;
mtime comparison alone is insufficient provenance. Record disposition through the
existing ownership protocol and retain all files. If provenance cannot establish
no submission, keep ownership unresolved and seek authoritative provider evidence.
No fresh VM inspection or disposition is claimed by this increment.

## Later implementation direction, not an implementation-ready plan

The eventual ordinary launch path needs a durable pre-submit intent binding
operation/launch/provider scope/request key/body digest/expiry/infrastructure hold.
An independent control-VM supervisor must reconcile and delete positively matched
late workers after holder restart, keeping deletion receipts and complete inventory
checks without manufacturing collection ACKs. Unknown requests retain ownership.
Adapter choice, exact schema/location, unit interval, lock order, hold formula and
stop-state polling contract still require a subsequent reviewed design. Do not
implement dormant speculative machinery from this outline.

## Tests, cost, acceptance and Murphy rows

Invert the expired-hold expectation in tests/factory/test_isolation_timeouts.py;
repeat checks in fresh processes and require unchanged reserved amount/status,
no new hold after refusal, and preserved normal finish. The existing unknown-create
regression continues proving pending creation never calls finish. Tests use saved
billing/created events plus authored crash timing; they prove local accounting,
not live provider cleanup or the USD 5 bound. Run the full suite to a unique
committed log/result: `uv run --with numpy --with scipy python -B tests/run.py`.
Fresh design review must recheck B1–B3 from design review 1; fresh diff review must
verify the deletion and tests. The author does not self-verify blocker fixes.

Cost is one offline implementation/suite/review cycle, no incremental cloud/model
probe spend. Next provider qualification belongs to stream B/parent: one read-only
docs/provenance pass, with provider clarification requiring separate messaging
authorization if docs cannot answer it. External response time is unknown; no
launch date is promised. Rough remaining increments: provider/legacy qualification
and cleanup/cumulative ledger, router/profile integration, final policy/release
and deployment/account-2 qualification; split further if contracts demand it.

No Murphy rows close: rows 6, 27, 28, 35, 51 and open batch-service rows retain
status. No new live failure was observed. Follow-up register candidate from review
N3: the collection-failure message in boat-launch-guards.sh recommends Hetzner
cleanup even on Boat; correct that provider-specific guidance separately. No
cleanup or legacy blocker is closed merely by documenting it.
