# Batch input qualification

## Goal and problem
Before a practice batch starts, establish which input can start a case and whether
migration output exists and is intact. Legacy archives are not authenticated batch
checkpoints. The 2026-10-31 SSH inspection found no migrated store on Mac or VM and
no VM batch directories. Missing migration is a blocker, never a passing skip.

## Admission design
Keep one launch path. Extract the admission portion of holder.reserve into
_admit(directory, record, policy, root, ops, state, name, source, provider_wait).
It performs the existing name/digest/deadline, replay, incident/concurrency,
_source, provider wait, advance_locked, sources[-2], authorize_locked sequence in
that order. It mutates only the supplied in-memory money state. Reserve holds its
existing lock and persists the result as before; replay still repairs the journal.
The qualifier calls the same function on loaded private state without persisting
it. This removes duplicate decisions rather than approximating checkpoint proof.

Checkpoint proof remains same-job/batch retired predecessor, matching authority,
publication ACK/outbox/current pointer and verified immutable snapshot. No legacy
import, renamed case or fabricated authentication is allowed.

For a NEW empty reservation, after the existing-operation replay branch and before
money authorization, call empty_input(root, directory, case). Check the exact
launch_manifest.collection_files(case) names under root/sealed and the canonical
Git common checkout sealed directory (deduplicated). Factor that directory lookup
out of batch.restore_inventory. Also check sealed/generations/<case> in both
sealed directories, and directory/generations/<case> and directory/current/<case>.json.
Use lstat: any object, including empty directories and dangling symlinks, refuses.
Permission and I/O errors also refuse. No prefix glob (job1 must not match job10).

Existing-operation replay is a lookup, not new admission: it remains allowed even
after output publication, with the existing chain-authority check. In dispatch,
after _post and the existing state/dispatch_started/incident early return, check
empty_input for source=None at BOTH locked checks before preflight and before
marking dispatch_started. Do not change _post or source_directory. No empty guard
after dispatch_started: controller replay and collection must keep working.

## Read-only input command
A small tools/qualify-batch-inputs.py accepts --policy, --root, --home, --job,
optional --checkpoint. Validate policy through key_holder.policy_load with its
normal root binding, then money.manifest. Call _admit on loaded in-memory state;
never call reserve, dispatch or money.locked, never alter HOLDER_ENABLED.
If batch directory exists, open its existing lock read-only with O_NOFOLLOW and
take shared flock; a missing lock refuses as state_unlocked. If directory is absent,
use the loaders' empty-state defaults and label observation batch_absent. This is
an advisory point-in-time observation; authoritative reserve/dispatch recheck it.
Missing journal is labelled journal_absent; missing checkpoint ACK is caught and
reported input_refused, not a traceback. Missing batch with checkpoint refuses.
Read/validation errors report input_refused. Reports contain eligible (boolean),
observation, input_kind and launch_ready:false. Exit 0 means input eligible only;
exit 1 means refused. Existing failed/retired operations are reported refused;
existing pending/launched operations are labelled replay, never new launch.
No secret bytes or arbitrary exception text enters JSON. No directories/files are
created. Policy/release validity is required even for an empty input.

## Migrated-store command
Add --qualify to tools/migrate-legacy-checkpoints.py, mutually exclusive with
--dry-run. Reuse load_plan then return before preflight, identities or writes.
Walk every plan entry through existing/complete at plan.output_root. Missing root
or per-row output is a failure. Refuse symlinked root and manifest/migration files.
Report schema, plan digest, counts by kind, source digest/case/kind and each row's
local_integrity (passed/missing/invalid). Verify files and original-card binding
with complete; do not invent new cryptographic proof. Both variants of
case-20261017T125556Z-18681d (checkpoint/divergent_checkpoint) remain historical;
card_bound_absent remains unavailable. Report local_integrity_passed separately
from qualified:false, vm_unwrap_verified:false, r2_verified:false. Exit 1 even when
local integrity passes because VM/R2 proof is outstanding. This limited command
cannot close migration rows. No claims about remote publication or key access.

## Tests, evidence and exams
Mid-term exam: empty guard and shared admission regression tests pass. Use retained
sealed/case-20261017T212118Z-1ad7fa.statement.age and .casekey.age as opaque real
collision evidence in isolated directories, with authored case names explicitly
identified. Cover all namespaces, dangling symlinks, empty parent, job1/job10,
fresh empty reservation, replay after output, and collision arriving after reserve
before dispatch. No new case archive is generated.
Reuse test_batch_holder lifecycle fixture for qualifier successor acceptance,
stale sources refusal, no-ACK refusal and unchanged tree contents/mtimes. Existing
test_lifecycle_status_ack_retirement_source_and_replay,
test_wrong_authority_and_pointer_alone_never_grant and
test_two_sources_never_return_to_old_generation retain checkpoint coverage.
These authored bindings are contract evidence, not live authentication or row closure.

Test --qualify with the real frozen plan against absent output, a missing per-row
output, and tampered authored manifest/card bindings using retained encrypted bytes.
Authored migration metadata tests are contract-only. Assert divergent/absent counts,
always-unverified remote proof, failure exit and no writes. No fixture generated by
the migration implementation is used as real migration qualification.

Final exam: required full suite passes with a unique log/digest/exit record and a
fresh diff review. Public live evidence is docs/reports/batch-auth-inputs-live-20261031.json:
UTC observation, labelled VM id/name, /home/user/unbug-bench/sealed/generations
existence/count, /home/user/.unbug-control/batches names and legacy checkpoint count,
Mac plan output existence, no case model calls/workers and rows_closed:[]. Inspect
through bin/control-vm.selected and ssh using read-only pathlib probes; never read
keys or private case content. Record --qualify result in a companion JSON report.

## Murphy and scope
Targets new-single-path-1, new-batch-service-1 and -2 remain OPEN: real migrated
outputs, VM unwrap and R2 bindings are absent/unproved. Record the newly identified
empty namespace collision as new-batch-auth-inputs-1, open pending live evidence;
contract tests do not close it. No migration or store mutations are authorized.
B owns cleanup/legacy ownership; B3 owns policy/release/manifest. Deletes no path;
extracts existing admission logic and directory discovery to avoid duplication.

## Impact, risks, cost and timeline
This gives the practice owner an explicit empty-input alternative and an honest
migration refusal, but does not authorize activation. Risk: overbroad empty guards
could block legitimate replay; exact filenames and dispatch_started boundary tests
address it. Benefits: no silent reuse of old case evidence and no false migration
pass. One implementation/review cycle, no workers or paid case calls; review-agent
usage is separate. Live migration/VM/R2 qualification is deferred until founder
migration produces artifacts, not assigned a fabricated completion date.

## Review-2 clarifications
empty_input treats only ENOENT as absent; every other OSError or existing object
raises ValueError('request_refused'). Reserve creates no operation on refusal;
dispatch records terminal failed/preflight_refused with dispatch_started false.
_admit returns authority for both new and replay; reserve detects replay through
identity membership in ops. The empty guard is inside _admit for new empty input.
Drop --root from the CLI: use key_holder.ROOT and its normal policy_load binding.
Report replay in admission; eligible pending/launched replay exits 0.
Invalid migration plan keeps exit 2. Symlink checks tighten shared complete/existing
and qualifier root validation. Compare home, root/sealed and output_root trees
including mtimes in no-write tests; invoke Python with -B. Tests live in
 tests/factory/test_batch_holder.py and tests/tools/test_qualify_batch_inputs.py;
existing tests/tools/test_migrate_legacy_checkpoints.py and
 tests/factory/test_restore_inventory.py must pass unchanged.

## Diff-review clarification
Canonical Git discovery under the batch lock has a 10-second timeout. Missing Git,
failed Git, timeout, unreadable or dangling Git metadata refuse empty admission as
plain ValueError, so dispatch terminates preflight rather than retrying forever.
Only an absent .git entry means an installed release with no common checkout.
The existing legacy restore_inventory fallback stays local-only on lookup errors;
that fallback is not used by empty admission. The qualifier reports journal_present
when an existing journal is observed under its shared lock.
