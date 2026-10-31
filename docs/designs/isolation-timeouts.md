# Isolation, deadlines and startup supervision

## Problem and boundary

A failed upload currently exits the multi-worker shell through its EXIT trap,
retiring healthy peers. Serial runner commands and silent strategy shells have
weaker cancellation than parallel commands. Detached startup has no exit receipt.
The HTTP owner can block on an incomplete request. Boat updates can change the
orchestration executable during a batch, and overlapping wallet deltas are
reported as attributable spend.

This change is the first independently reviewable E increment. It addresses the
runtime ownership boundary before changing the larger batch service. It must not
change model routing/account handoff/restart policy (stream A), gate scoring
functions in run.py (stream C), keys, source qualification trust, or restore
bundles. No cloud launch or decryption is needed for validation.

## Changes

1. Add `bin/processes.py` (importable by both bench and factory), a stdlib process owner. `run(args, timeout=120,
   deadline=None, cancel=None, **Popen-options)` returns CompletedProcess and
   supports input/check/capture_output like subprocess.run. Every foreground child starts
   in a new session unless UNBUG_DIAGNOSTIC_PROCESS_GROUP=1, whose existing
   diagnostic owner owns the complete group. On cancellation snapshot numeric
   PID/PPID relationships with bounded ps (no command lines) and kill descendant
   groups too, before killing/joining the direct child; this covers nested owners.
   Background strategy watchers retain their existing diagnostic opt-out. The effective monotonic deadline is the minimum of the
   caller timeout, a context-local deadline, and inherited
   `UNBUG_PROCESS_DEADLINE` (same-host monotonic value). Child environment carries
   that deadline. Communicate polls at most 0.2 seconds for cancellation. On any
   BaseException, kill the process group and join the direct child, then rethrow.
   Kill remaining descendants on successful parent exit too. No unbounded drain
   of inherited pipes. `deadline(seconds, independent=False)` nests with the earlier deadline using
   ContextVar, so overlapping gates cannot change each other's deadlines.
   `shell(command, timeout=120)` is the async equivalent for silent windows,
   killing and awaiting the child on timeout or CancelledError.
2. Replace the two sh() paths in run.py with this owner, retaining command log
   and return semantics and passing role_cancel. Route bench.command, strategy
   checkpoints, run_artifacts subprocess calls, and worker version discovery
   through it. All routed commands are foreground clients; Docker daemon-owned
   services from compose up -d intentionally outlive the client, while stray
   local descendants do not. Wrap G13/G14/G15 evaluation in GatePipeline.check with a deadline
   bounded by agent_timeout (default 4h); cached checkpoint receipts remain the
   existing strategy_resume implementation. Shell children inherit the same
   deadline. Seal and wipe get independent 600/120 second deadline contexts with independent=True (ignore outer context and inherited
   deadline, without changing os.environ) so
   a spent gate deadline cannot prevent finalization; provider-lifetime reserve
   remains owned by the controller. Do not edit run.py gate evaluators. ContextVar is used only within synchronous
   GatePipeline.check; that context sets the inherited deadline on each spawned
   child. G13/G14/G15 do not submit work to a parent executor; overlapping G10
   starts its own check context. No global environment mutation is allowed.
3. Put each provisioning/setup iteration of launch.sh in an explicit subshell
   with its own EXIT trap disabled. Set parent +e immediately before the
   standalone subshell and restore -e after capturing status; never put the
   subshell in an if/! or || condition (which disables errexit inside). It owns
   `$state/$id.setup-status` containing one integer exit code and returns
   failure to the parent; the parent records failure and continues dispatch and
   monitoring. `guard_new` remains in the parent so IDs/serials survive errors.
   Before each worker run, repeat only idempotent pin/qualification commands
   (the opencode_pin SSH block and worker_release.py SSH verification only;
   maximum two attempts, 1-second delay); never repeat `new` or detached execution after an
   ambiguous response. A failed worker is retired individually; healthy peers
   remain monitored until their own DONE/deadline. Setup failures still go through
   collect-before-delete (including keys/work already installed); uncertain
   collection leaves the existing KEEP/TTL protection. SIGINT/TERM still retires all
   workers because it is an explicit batch cancellation. Replacement of lost
   workers from encrypted checkpoints remains stream B, so row 18's replacement
   portion is not claimed closed by isolation alone.
4. Add `factory/runner_supervisor.py`. It takes a command after `--`, inherits
   credentials without recording them, runs the command in an owned group,
   discards pre-handler stderr (may contain secrets), and atomically records
   only attempt number, integer exit status, phase, timestamps, and reason
   (enum running, startup_retry, startup_failed, finished, cancelled, timeout) to
   `~/sealed/runner-status.json`. run.py writes `runner-ready` immediately after
   its finalization/signal setup, and only when FACTORY_RUNNER_READY names
   that attempt's fresh marker path. The supervisor owns marker removal. If startup exits before that marker with an
   operational status (1, 126, 127 or signal), retry twice with a 1-second delay
   under the original deadline, only while ~/work has no entries and ~/sealed has no *.continuation-budget.json.
   Status 1 includes SyntaxError and ImportError; those get the same bounded retry
   without inspecting private stderr. Usage status 2, an existing DONE, or any
   work/ledger prevents blind retry. Existing restores therefore never blindly
   retry, including in-place startup: record startup_failed and preserve work.
   On exhausted startup failure the controller probe returns STARTUP_FAILED,
   in guard_wait, promptly collecting the worker (no fake case DONE). Collect
   runner-status.json alongside public receipts; an unstarted empty work tree
   uses collect.sh's existing startup/no-WORK exception. In-place failures with
   work require existing verified archive collection, otherwise KEEP. Unstarted
   jobs remain infrastructure failures, not scored cases; replacement remains B. Wrap both initial and
   in-place detached runners; preserve the existing restart locks. Supervisor
   guards in launch.sh reuse_check, restart shell and resume-in-place.sh must
   match runner_supervisor.py as well as run.py, closing retry-delay overlap.
   On SIGTERM supervisor forwards TERM to run.py (pause), waits up to 720 seconds
   within its original deadline for seal, then kills/joins leftovers. Its own
   signal path never retries. It obtains its monotonic deadline from a positive
   FACTORY_RUNNER_SECONDS supplied on the remote host (ttl minus collection
   reserve, recomputed remaining for in-place start). Receipts are operational metadata and never assert a case verdict.
5. Pin Boat 1.0.85, observed read-only from the installed executable on
   2026-10-29. boat-call resolves `~/.ascii/bin/boat` or PATH directly, checks
   `--version` before use, including BOAT_CMD when basename is boat, and always sets BOAT_NO_UPDATE=1. BOAT_CMD remains an
   explicit executable path for Hetzner/offline tests; basename hcloud-boat or
   any other test transport skips the version check. Production control points
   to /usr/local/bin/boat, so it is checked. Expected version is 1.0.85 there
   too; a differing installation is refused before any provider operation.
   The controller qualification receipt records this prerequisite; no cloud
   access or VM upgrade is claimed by this patch. It also gets
   BOAT_NO_UPDATE=1. Delete interactive-shell discovery. Verification and the
   command share one timeout. Mismatch fails before the provider command.
6. In boat-spend, serialize Boat --check/--finish with flock under
   UNBUG_CONTROL_HOME (default ~/.unbug-control). An atomic JSON ledger reserves
   the whole batch estimate by absolute spend-record path. Admission subtracts
   every unfinished reservation from current available balance (conservative
   about already accrued spend). As superseded by stream-b-delayed-creation.md,
   expired holds remain reserved; neither TTL nor idle inventory releases them.
   Retries of one record are idempotent. Release only on verified completion
   via the existing finish call. Keep balance_before/after as observations;
   actual_spend_usd stays null unless authoritative per-worker usage is supplied.
   Record `account_balance_delta_usd` with attribution `account_observation`;
   never add it as worker spend. This fixes false attribution but lifecycle
   usage retrieval remains open. No new credential stores or network APIs. Ledger path is
   $UNBUG_CONTROL_HOME/boat-reservations.json, schema {version:1,reservations:{
   absolute_record_path:{usd,expires_at,status}}}; status is reserved/finished/
   reconciled_expired (historical only; admission no longer produces it).
   Lock is boat-reservations.lock. Refused checks write
   allowed=false but reserve nothing. Hetzner bypasses the ledger. This is a
   single-control-host guarantee only; cross-host admission remains open, so
   row 17 stays open. Rollback retains spend records, cannot refund provider
   charges, and must preserve active holds. Tests use a committed allowlisted
   billing receipt captured from the local CLI read-only, never its credentials.
7. In factory/exam_responder.py only, bound responder header/body parsing at a
   total 5 seconds using a daemon timer that shuts down the connection (an idle
   timeout alone is insufficient), and bodies at 16KiB, reject
   negative/oversize/missing length, non-object JSON and incomplete bodies.
   Validate/pre-read the body then pass an in-memory stream to protocol.Handler;
   cancel the timer before model invocation. Do not edit harbor/responder.
   Use ThreadingHTTPServer with daemon handler threads, a single owner-call
   lock and nonblocking acquisition (503 for concurrent calls), a 0.1-second
   server poll, and bounded shutdown join. The owner cancellation event stops
   model subprocesses through existing runtime cancellation. Do not log bodies
   or private exceptions in public responses. Concurrent asks return operational
   HTTP 503 (ask-human already treats non-200 as failure), never a canned answer.
   Changing factory/exam_responder.py changes owner contract code_sha256; prior
   certifications must recertify using existing contract invalidation. No old
   certification hash is rewritten or accepted by exception.

## What is deleted

Delete per-worker-count subprocess branching, duplicated shell process cleanup,
interactive zsh Boat discovery, and balance-delta-as-actual-spend labeling. Keep
existing verification and collection rules; a failed collection never authorizes
deletion. No additional dependencies or generic task framework.

## Tests and evidence

`tests/factory/test_isolation_timeouts.py` reads committed public allowlisted
fixtures under tests/factory/fixtures/isolation-timeouts/, copied from the real October 29 restore
control-home/launches/653390023bca4019b391be6013e9c80c/{launch.json,monitor.sh,new.1,
bx_d6dzvjbc.worker-release.json}; only argv, selected numeric monitor values,
created event id/TTL and runtime image/tool fields are committed. These are
independent saved artifacts, not outputs generated by the implementation.
The external evidence is read-only; tests never skip when it is absent. Tests copy only public metadata into a
temporary directory; no ciphertext is opened and no secret-bearing files are
copied. Fault injection attaches hung processes and crashes to those real
command/envelope inputs. Drive actual run.sh with bench_workers=1 and actual strategy.silent_checkpoint
with an injected run_window that invokes Environment.exec. Assert descendant
death after sync timeout, async
cancellation, pause and successful shell exit; assert earlier nested deadlines
and independent thread contexts. Exercise startup failure/retry/non-retry and
safe receipt fields with real runner arguments. Feed partial/oversize HTTP
requests over real sockets and verify health and bounded close. Exercise two
concurrent wallet checks using the real billing response shape, rejecting the
second admission and retaining reservations after uncertain outcomes. Regress
isolation through the real launch shell with a failed worker and healthy peer;
retain the existing fake transport only for side effects. Update tests/bench/test-boat-call.py for a fake executable basename boat and
version mismatch; tests/bench/test-launch-guards.py for supervisor command
wrapping/account-observation fields/worker-setup isolation; test_early_crash.py
for injected process adapter; tests/tools/test_launch_manifest.py for new
process/supervisor files; worker-release and responder tests for the adapter.
Read real saved list.json pageInfo and billing limits.creditBalanceSeconds
shapes in schema assertions; do not manufacture both expected and actual shapes.

Run targeted scripts, then the mandatory full offline suite:
`uv run --with numpy --with scipy python -B tests/run.py`.

## Murphy row accounting and remaining E work

Target closure in this increment: 31 (pinned/no-update Boat), 44 (owned strategy
and serial runner groups), 46 (startup exit receipt and bounded retry), 52
(bounded HTTP input/shutdown). Row 18 gains peer isolation; leave it open until
automatic replacement is integrated with stream B. Rows 17 and 49 gain atomic
reservation and honest account observations; 17 remains open because cross-host coordination is not supplied; 49 stays open until per-lifecycle provider usage exists.

Rows 42/43 gain gate deadlines and shared ownership for the named paths, but
remain open until all direct subprocess callsites (including stream A's model
setup and stream B's transfer/collection paths) use remaining-time bounds.
Rows 29/30/32/37/45/50 remain open (row 28 moved to B): complete paginated/queued inventory,
operation-ID reconciliation, explicit batch contract, complete frozen release
installation/digest-pinned image distribution, disk/host-memory admission,
and restart-safe provider/UTC clock handling require subsequent changes. Do
not pretend a local Docker image ID from a historical receipt is a registry
manifest digest, or derive a pagination API contract from invented CLI flags.
These limits are deliberate review boundaries, not claims that the overall E
workstream is finished.

## Fingerprints and rollout

These are plumbing changes with no case verdict, but the legacy bench_manifest
hashes bin/ wholesale. Editing boat-call, strategy, bench and adding processes
changes bench_sha. No digest is forged or excluded to conceal this. Fresh
workers install the changed release and launch.sh computes the clean new bench
SHA before restoring; run.py receives that SHA through the existing checked
--resume-bench-sha path. Gate_state retains only evidence whose dependencies
still match. G11/carry-over bound to a previous review_bench_sha256 must be
recertified by a new audit, never same-worker continued across this update.
Existing reuse-review with an old hash still refuses safely. This increment
does not deliver the target of rolling plumbing without invalidating broad
legacy bench fingerprints; that limitation remains open with release migration.
Real-card tests must show the new clean SHA is required while mismatches fail;
no saved restore bundle or scorecard is modified.

## Design review 1 responses

B1: chose explicit fingerprint migration above; shared helper lives in bin,
not a reversed bench-to-factory dependency. B2: all executable basenames boat
are pinned, including production BOAT_CMD; add schema/real-version fixtures.
B3: exact ledger and bounded provider-TTL reconciliation; row 17 stays open.
B4: status-1 retries are bounded without false classification, exact phases,
ready marker, guard updates, and controller/collection semantics specified.
B5: drive both named row-44 call sites and preserve diagnostic ownership;
background daemons remain outside local client group. M1: independent deadline
reset form and explicit child-env propagation, no global env mutation. M2:
standalone errexit subshell and exact step retries/receipts. M3: factory-only
HTTP adaptation with total parse timer and explicit contract invalidation. M4:
committed allowlisted artifacts and exact existing-test list. M5: retain one
reviewed change with four commit-sized phases: process ownership; isolated
launch/supervisor; Boat pin/accounting; HTTP owner. Full suite after integration.

## Parent scope agreement (2026-10-29)

The parent approved this first increment and these remaining open evidence gaps
(pagination API and registry image digests). E owns deadlines/process groups,
per-case launch lifecycle, boat-call/spend and release/image pinning. Do not edit
budget.py provider classification (A). Delete obsolete
tests/tools/test_restore_failover_bundle.py with explicit parent authorization.
Keep tests/tools/test_open_g2_verdicts.py; its missing gitignored helper is a
baseline worktree failure being moved to tracked tools/ by the parent.

## Trusted launcher rollout (round 2 N1 and M-A–M-E)

The launcher fingerprint changes. launch_manifest.TRUSTED_FILES remains the
security boundary; add bin/processes.py there because boat-spend imports it,
and to WORKER_BENCH for worker installation. runner_supervisor.py is covered
by the factory worker glob, not imported by the host. No old approved policy
is rewritten or allowed to bypass code_sha256. This changes bound code bytes,
not the fingerprint/approval security property. The parent owns merging and
deployment; this branch never deploys, unlocks or starts a real job. After all
four phases merge together and reviews pass, the parent regenerates the public
policy code_sha256 using key_holder.fingerprint on the final deployed checkout,
retains the same job authorizations, and presents that concrete policy to the
founder for approval before holder unlock. Existing policy approval is not
carried forward implicitly. The old holder/checkouts keep managing their live
workers until collected; do not overwrite a live controller's checkout. Pending
old reservations remain with that generation and may be resumed only there;
new policy launches use a distinct frozen reviewed checkout. Parent integrates
E before later streams per the agreed merge order. This branch supplies no
policy replacement and changes no approved policy or restore bundle.

Before enabling the new checkout on the control VM, the deployer must verify
BOAT_NO_UPDATE=1 /usr/local/bin/boat --version returns boat 1.0.85. This is
check-only pinning; control/setup.sh download pin/distribution remains open
with image/release rollout. The Mac receipt does not assert a VM observation.

Process tree cleanup never killpg's the caller's process group or session. A
shared diagnostic child is killed by PID plus descendant PIDs; only a distinct
owned session leader's group may be killed. Test the shared-group opt-out in
a separate subprocess and assert the owner survives. Gate deadline expiry
raises subprocess.TimeoutExpired; the existing gate_attempt crash path records
runner_error:TimeoutExpired and an operational stop, not a scientific verdict.
Test that path with a real public-card gate context. The legacy bench change
invalidates G13/G14/G15 strategy cache signatures and G11/carry-over identity;
those rerun (broader plumbing-neutral migration remains outside this increment).

Keep args plus detach and credential variables inside the setup subshell. It
may append resume arguments there; restore is N=1, so parent does not need the
mutated args or identity. Parent serial/id ownership stays outside. Required
persistent outputs are bench-sha, setup-status and existing receipts only;
put_ckpt/put_final and identity never persist. Supervisor alone records timeout
and cancelled. collect's matching TERM may hit both supervisor and runner;
repeated TERM is safe under the runner's pause handler. A held/uncertain VM
never releases its wallet reservation via finish: guard_exit checks all IDs
are deleted/verified before --finish regardless of launch-state mode. Expired
holds remain reserved until finish; provider TTL is not release evidence
(stream-b-delayed-creation.md supersedes the prior expiry reconciliation).

## Implementation clarifications

The parent owns row 28 after the interfaces.md contract; E drops it. Unknown
launch outcomes stay pending. Startup_failed is a runner phase and never a
claim that Boat created no worker. Row 29 remains open for operation-ID retry
and reconciliation integration. On the runner's work deadline, supervisor
requests the normal pause/seal path before killing. It passes that monotonic
deadline to children and reserves a separate grace of min(720, margin/2)
seconds inside the already allocated provider collection margin. The remaining
margin belongs to collection. This prevents the supervisor racing normal TTL
retirement and killing a checkpoint in progress. No provider TTL is extended.
The only live consumer of actual_spend_usd is public-qualification/finish.py;
it already refuses unknown spend. This remains safe but blocks financial
finalization until authoritative per-lifecycle provider usage is supplied (49
open). Parked Hetzner servers bypass the Boat-wallet ledger entirely.

Expired wallet holds stay reserved even after complete idle inventory. A late
creation may still become visible, so admission no longer queries inventory or
produces reconciled_expired (superseded by stream-b-delayed-creation.md).
Authoritative per-operation cleanup and cumulative infrastructure money remain
future work; historical releases require deployment qualification.

Nested helpers inherit UNBUG_PROCESS_GROUP_OWNED=1 and stay in the already
owned outer group. Top-level foreground calls still create a session. This
prevents nested owners from escaping when an intermediate shell exits; shared
diagnostic ownership is preserved. A shared child kills only its own PID tree,
never the owner's group. Strategy watcher cleanup uses the same helper.

A creation response without an owned worker ID is unknown, not failed.
guard_new writes new.<serial>.pending; guard_exit retains the batch wallet
reservation and leaves the launch incomplete. It never retries that creation.
A new real-envelope lost-response test proves pending survives the exit path.
Operation-ID reconciliation still belongs to the remaining row 29 work.

Before allocation, launch_manifest.verify_worker_runtime checks the frozen
bundle's supervisor and process-helper hashes against the reviewed launcher
checkout. Historical qualified releases without these files refuse before a
worker is allocated; otherwise the new launcher would detach a missing
supervisor and recreate row 46. Deployment therefore requires a newly qualified
complete release built from the integrated checkout, as already required by
the rollout section. This is a compatibility check, not a new upload path or
a claim that rows 32/37 are closed.

## Validation and closure

Mandatory offline suite completed on 2026-10-29: 130 scripts, 0 failed.
Command: uv run --with numpy --with scipy python -B tests/run.py. Focused
real-envelope fault tests pass (15), controller recovery tests pass (14),
launch guard tests pass, and the final runtime compatibility guard is checked
against both a real historical source inventory and a current stamped bundle.
The final supervisor-attempt cleanup adjustment is rechecked by the focused
fault suite. No real VM was launched, no restore bundle changed, and no real
ciphertext was decrypted. Only public metadata was copied from the read-only
restore directories. Existing offline tests use throwaway synthetic keys.
Rows 31/44/46/52 are marked closed with their test paths in this fix commit,
pending diff-goldfish confirmation. Other E rows remain open as documented.

## Diff review 1 responses

B1: import processes in the real wipe child snippet. New regression executes
the real copied bench/process/permission sources and real compose file against
a local Docker executable adapter, using the saved two-slot launch configuration.
It asserts guard-1 removal and factory_cleanup_ok; no process call is mocked.
B2: bench.command explicitly permits 3600 seconds for standalone build/setup
commands, still taking the minimum inherited deadline. The real process test
advances a clock by 121 seconds after a child signals readiness: standalone
execution completes, and an inherited 60-second limit kills the still-blocked
child. The general helper's 120-second default remains unchanged.
M1: execute byte-identical real run.py copies through the real supervisor.
A poisoned gate_pipeline dependency fails before setup and retries exactly
three times without a ready marker/work. A poisoned free_models import fails
after the real ready marker and is not retried. Both use saved routes/caps in
a fresh dry-run namespace; no provider, Docker or encryption is reached.
M2: default ~/.ascii/bin/boat discovery now has pass/mismatch tests with no
BOAT_CMD; register explicitly states mismatch refusal and the deployment install
prerequisite. M3: parent unsets restore identity after subshell completion.
M4: smoke fixture uses its own temporary control home and the fix is committed.
Four finished synthetic holds from earlier runs were removed under the ledger
lock; other entries were untouched. No real worker was launched.

The repeated-failure launch test has a 60-second harness budget (production
command deadlines stay unchanged). Its previous 30-second limit could expire
while six bounded collection attempts performed their per-file one-second
timeouts; the committed-tree rerun exposed this once. The earlier full suite
passed 130/0. Re-run the final full suite after these fixes.

Kill-tree snapshots also retain numeric PGIDs, avoid duplicate signals to one
group, and skip a reaped leader's group if the snapshot has no members. Direct
children are joined and streams closed even if tree cleanup raises.
contextlib now imports normally; processes stays function-local in GatePipeline
because run.py installs the bench bin path after importing that module. This
optional import-style nit cannot justify breaking real worker import order.

Round-1 fix validation: 20 focused fault tests pass, including executable slot
cleanup, real runner pre/post-ready failures, default Boat discovery, a 121s
accelerated standalone command with an earlier inherited-deadline countercase,
concurrent 503 handling, and an actual body trickle. Gate setup, parallel
cleanup and owner protocol regression scripts also pass. Full suite is rerun
on the committed fixes. No blocking review finding was rejected.

## Final handoff validation

Reviewed source commit: 78473870ec2acb6672e9a2a24c97ac1f24114751, rebased
onto factory-simplify 8c5de614d14af0df1e6b63f31972195825e8cd53 before review.
Fresh diff review 2: PASS, no blockers. Mandatory full suite completed on this
source commit: **130 test scripts run; 0 failed.** Focused fault suite: 20 pass.
Command: uv run --with numpy --with scipy python -B tests/run.py.
The final evidence commit changes documentation only. No merge, push, Boat
worker launch, real ciphertext decryption, main-branch change or restore-bundle
mutation occurred. Deleted only the parent-authorized obsolete failover test.

Closed: 31, 44, 46, 52 with register test paths confirmed by diff review 2.
Remaining: 17 (cross-host/generation wallet ownership), 18 (automatic worker
replacement), 29 (operation-ID reconciliation/retry), 30 (batch contract),
32/37 (complete new frozen release and authoritative registry digests),
42/43 (remaining direct subprocess paths/provider-lifetime integration),
45 (disk/host-memory admission), 49 (per-lifecycle provider usage),
50 (restart-safe provider/UTC clock handling). Row 28 belongs to B.
Before deployment, parent must cut/qualify the new release, refresh adapter
and launcher pins, verify Boat 1.0.85 on the control VM, and regenerate the
root/fingerprint-bound policy for founder approval. Historical bundles stay
read-only; no digest or pagination API was guessed.

## Loaded launch-guard regression (2026-10-30)

The reported deletion at `test-launch-guards.py:465` happened during statement
installation, before detached execution. The test's global one-second command
deadline raced setup on a loaded host. Its mode-based assertion incorrectly
treated this empty, successfully collected worker as a running hung worker.
A three-CPU-burner reproduction with a 1.5-second delay at that same transfer
fails the identical no-delete assertion; the real launcher returns timeout 124,
collects the empty worker and retires it. Without that delay, the focused loaded
monitor/signal checks pass. This is not evidence of lost running work.

The signal check separately waits at most 30 seconds for a poll while leaving
both output pipes undrained. Setup time is unrelated to signal handling, and
enough setup diagnostics can prevent the poll indefinitely. Delete this
preparation-time assumption: the fake transport sends the requested signal to
the launcher PID only when its actual watchdog probe arrives, while the harness
continuously drains output with `communicate`. Keep one outer hang-detection
budget, not a separate readiness deadline; assert the probe event occurred.

For command deadlines, inject a clock into the temporary copy of boat-call's
process owner. Freeze it until the selected fake transport phase announces its
event, then advance it beyond the configured deadline. Keep real subprocesses,
timeout handling, collection, process cleanup and deletion decisions. Ordinary
setup does not compete against a one-second scheduler budget. Test both sides:
a timed-out pre-run statement transfer collects/deletes an empty worker; a
started worker with failed or timed-out monitoring and unverified collection
is retained. Assert runner start and watchdog arrival explicitly. Replace the
fake transport's ten-second hang sleep with an event followed by a signal wait.
Use the same clock handshake for the slow-restore test instead of a real sleep.
Watchdog progress/stall observations should also use injected time, independent
of host scheduling. These seams exist only in the copied test bench; production
deadlines and scripts remain byte-for-byte unchanged.

Validation: reproduce against the old harness under three CPU burners; run the
entire launch-guard script five consecutive times under that load, then the
mandatory fresh full suite. Add an output-backpressure signal regression and
retain exact timeout/collection/retention assertions. A fresh goldfish reviews
the diff. No Murphy row is closed or newly needed for a test-only fault; rows
18/42/43/50 remain open. No real Boat calls, merge, push or deployment.

The following details are the normative implementation contract, resolving
design review 4: copy `tests/bench/launch_guard_clock.py` next to the
temporary boat-call and insert its install call immediately after `import
processes`, asserting exactly one match. Only this executable replaces its
`processes.time` reference (not the shared Python time module). Every invocation
in every scenario freezes its monotonic clock at its real initial reading.
The real owner still propagates UNBUG_PROCESS_DEADLINE. Its fake transport and
the transport's shell/tar/version/probe/case_permissions children never read
that variable or import the owner; the actual worker supervisor is not run in
this test. Host spend/deletion helpers keep their real clocks and do not inherit
environment mutations made inside boat-call. No production hook is added.

Each boat-call supplies `FAKE_COMMAND_CLOCK=$FAKE_STATE/clock-<own-pid>-<monotonic-ns>` to its
child. The fake atomically publishes elapsed time there and waits for that
specific owner's `.observed` acknowledgement. Thus concurrent worker probes
and later collection/deletion calls cannot advance one another. Setup-timeout
and each hang advance by configured command timeout plus one second; restore
advances exactly one second, beyond 0.5 but below its three-second override.
The harness asserts all published events were observed, including both the
watchdog timeout and the collector's independent metadata/hash timeout. The
unreachable test drops its unnecessary one-second override.

Retention assertions now first require recorded `exec`, a watchdog marker and
failed collection (KEEPING diagnostic), then assert no delete, a live orphan
and an unfinished spend record. The setup-timeout countercase requires no
`exec`, an observed transfer timeout, and collection before deletion. Existing
mode expectations remain assertions, not evidence that a phase was reached.
The watchdog is identified by `.boat-launch-start`, absent from transfer and
collection snippets. Signal delivery uses a one-shot marker and the exact
launcher PID, with more than 64 KiB of stdout from an exec-preserving harness
prelude and stderr from fake setup; both streams must be completely drained,
and exit must be `128+sig` within the common outer 60-second hang budget.

Remote watchdog time is also explicit: fake worker files start at epoch
1000000000; the real probe runs with only `time.time` injected. Stale/mixed
workers observe epoch+10. Progress probes advance ten seconds per poll and
timestamp only the expected progress file, resetting its parent directory's
mtime so a missing file scan cannot accidentally pass. Other probes observe
the base epoch. The existing host `date` shim remains limited to autoretry;
host TTL and unreachable cutoff logic remain real, with hour-sized TTLs and
the outer hang bound. This is a small test-only change; validation time is
dominated by five complete script runs and one full suite.

Loaded regression validation is complete on source `46ec5ef`: five consecutive
passes under three CPU burners/nice +10 (388.87, 373.47, 360.09, 342.33, 328.33
seconds); concurrent full suite **148 scripts, 0 failed**. Fresh diff review 3
passes with no blockers. Exact evidence, hashes and baseline reproduction
commands are in `docs/reports/isolation-timeouts-loaded.md` and its JSON.
Only documentation changed after the tested/reviewed source commit.
