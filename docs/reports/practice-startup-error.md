# Practice startup diagnosis (offline)

The one parent-approved read-only transfer retained the encrypted checkpoint and
wrapped case key in mode-700 scratch outside git. No worker/provider/Boat action,
remote mutation, identity transfer, plaintext key file or ledger change occurred.
Decryption used the existing control identity in-process; only ciphertext and a
sanitized exception/location extract crossed the connection. No secret material
was printed. Decrypted case material was not written to disk.

Real traceback: RuntimeError: exit 1, `/home/user/factory/run.py:3387` in main,
then `run.py:161` in sh. Retained location: `logs/runner.log:4–9`.
Underlying Docker exception at `logs/commands.log:3–4`: container name
`/unbug-bench-postgres-1` already in use. Exact sanitized extract is the committed
fixture. The public card's error label discarded this message; encrypted logs
retained it. The missing continuation-budget ledger follows the early crash
before any model request, so accounting refusal stays intact.

Local experiment: pinned source archive in mode-700 scratch, isolated Docker
project, cached images only, no pulls. A created old-Compose-labelled Postgres
container was successfully recreated. This does not reproduce the deleted
worker's exact Docker metadata; no stronger cause claim is made.

Parent authorized one additional read-only extraction, with no remote mutation.
Retained commands.log:1–2 reports Redis Creating and Postgres Creating, confirming
Compose did not adopt the conflicting container. Worker Compose version: 5.3.1.
The proposed removal-only fix was rejected by fresh review: it could defer the
failure until after paid work. Revision 2 preserves pre-model preparation through
the existing locked owner and adds fixed-name cleanup there.

Discriminating local Docker reproduction (cached images, isolated project): an
unlabelled fixed-name Postgres container produces the same name-conflict failure
(exit 1); it survives Compose down. Removing that exact name and re-running up
succeeds (exit 0). All experiment containers/volumes were removed; no shared
bench containers were modified. This proves the unadopted-name mechanism, not
the inaccessible old worker container's exact labels.

## Parent-approved implementation and targeted evidence

After design round 2, the parent approved removing the four fixed names BEFORE
Compose down -v. The runner now uses the existing locked fresh preparation before
model selection in every former startup mode. A single COMPOSE_PROJECT constant
lets the real Docker exam isolate its project. No new launch/retry path exists.

The real Mac Docker exam actually ran (not skipped): 3 startup tests passed in
15.875 seconds. It reproduces the unadopted-name conflict with a stopped Postgres
using a marked, already-seeded named volume; proves down alone retains that
volume; then checks marker deletion and successful CREATE ROLE bench_checker /
CREATE DATABASE medusa_seed under the real lock, twice (startup and G3). An
unrelated container survives. Only the test's own project is removed afterwards.
The setup adapter excludes app builds/migrations; 16 seconds is not a production
startup-time estimate. The first test run exposed an initialization-server race
in the test itself; readiness now uses TCP to wait for the final Postgres server.

Real runner/handler tests cover ordinary, dry-run, resume, rehearse-only, audit,
late-gate rehearsal, statement-only and extension. A real failing command emits
the retained conflict. Decrypted test archives contain its bounded diagnostic;
public scorecards carry only logs/runner.log and no message. Test credentials are
throwaway. Existing encrypted commands.log remains raw; no archive-wide secret
redaction claim is made. G3's generic failure wording remains out of scope.
Pool (6), gate setup (15), and historical evidence (5) tests passed. The latter
now validates retained 2026-10-31 ledger counts against that probe's embedded
scanner schema, not today's added settled state; retained observations are
unchanged. This corrects the sole earlier settlement-suite failure, not runtime
accounting. Early-crash missing-ledger collection refusal is still intentional.

The full worker-command regression now passes (1 test, 27.424 seconds): real
launch.sh, runner, preparation owner and TLS router, with authored Docker/app
edges. Its seed-ID double was extended for the now-executed checker path. A failed
exam decrypts only its throwaway archive to expose the retained traceback. This
is offline delivery coverage, not a real application build or cloud qualification.

## First locked full suite

The 20261103T121120Z-fa16c8ee run at source 8f4aafb completed all 180 scripts:
3 failed, so its record is qualifying=false. Dispatch, qualified-allowance and
runtime main-path tests had four stale sh doubles returning None or an object
without returncode. The new real pool owner exposed that invalid adapter contract
(AttributeError: NoneType has no attribute returncode, or the equivalent object).
The correction returns status 0 for successful non-capture calls and preserves
capture stdout with returncode=0. No assertion, budget or timing limit changed,
and production source is unchanged. All other scripts passed, including the
real Docker startup/volume/seed exam and the full worker-command integration.
The failed log and hashes are retained; they are not claimed as validation.

Corrected adapter targeted runs: dispatch 63/0 (80.491s), qualified allowances
10/0 (8.275s), runtime 42/0 (84.475s), using the same uv Python/dependencies as
the full suite. Original assertions are intact. A second locked full suite
follows; no production file changed after 8f4aafb.

## Qualifying locked suite

Source c3a1f6d (tree 2fa1264db2fe026b90d98c0175f173b10ee4bd2b):
180 scripts, 0 failed, exit 0. Record and compressed log:
`practice-startup-error-suite-20261103T133626Z-742d551b.{json,log.gz}`.
Command: `lockf /tmp/unbug-suite.lock uv run --with numpy --with scipy python -B tests/run.py`
with UV_OFFLINE=1. Recorded command duration includes the shared-lock queue.
The log contains the real Docker conflict/volume/seed success marker; the exam
ran rather than skipping. All three corrected runner-path files and the full
worker-command integration pass. No production source changed after 8f4aafb.
Fresh diff review is the remaining gate. Settlement 0292abc predates this repair
and still needs its own diff review; this repair does not qualify live reuse.

## Diff round 1 corrections

B1: early_probe now publishes only the exception type, closing the newly exposed
path from rich command exceptions to the public card. The regression drives a
real failing sh command through early_probe calibration, using the retained
conflict plus an authored private-SQL marker. The command log retains both while
the card excludes both. M1: startup mode tests now omit check at the execute call,
as fresh factory_pool does; the runner adapter must supply check=True.
The Docker exam also pins COMPOSE_PROJECT to the compose file's name.
All URLs are redacted (not just userinfo/query). The G3 repeat uses the newly
adopted container; startup is the unadopted-conflict phase. The 15.875s measurement
above is the original targeted run, not the full-suite file duration.
Optional N2 (overlong single-line tail omitted) and N4 (historical AST position)
remain open. No live qualification or accounting release is claimed.

Round-1 fixes targeted validation: tests/factory/test_practice_startup.py ran
4 tests, all passed in 20.426 seconds, including real Docker (not skipped).
The changes await their own locked suite and final diff review round 2 of 2.

The 20261103T155412Z run at 0ee9831 is retained as non-qualifying (exit 143).
After the parent retired the suite lock, only this worktree's verified suite
process tree was stopped. Its one observed failure was the old calibration
test expecting provider_limit in the public skipped message. That assertion now
expects BudgetError, matching the type-only privacy contract; resume-flag and
no-completed-receipt assertions remain unchanged. The replacement full run uses
the parent's parallel-tests runner without lockf.

Parent-directed runner merge: parallel-tests 89934c9 merged at 3804bba.
Touched tests on the merged tree passed: calibration_attempts (9 tests) and
practice_startup (4 tests, 34.782s). The real Docker exam ran, including fresh
volume marker removal and repeated role/template SQL, without a skip.
The next qualifying suite uses the parallel runner without lockf.

Parallel run 20261103T173952Z at 6785aa7 completed 186 scripts, one failed.
Only test_parallel.py failed: a second old assertion expected provider_limit
inside the public early-probe message. It now expects the exact BudgetError
type; its label and non-stopping behaviour checks are unchanged. A repository
search found no further provider_limit/skipped assertions. The real Docker
startup exam passed all four tests in 45.964s in that full run. This failed run
is retained as non-qualifying; no production change was needed.

## Final review-fix validation

Source b7f6a974417a91911387eb67705a52cc00d78a10 passed the parallel full suite:
186 scripts, zero failed, exit 0, from 2026-11-03T18:21:59Z to 18:39:06Z.
Record: practice-startup-error-suite-20261103T182159Z-a587d574.json and its
.log.gz. The recorded tree and both hashes were checked. The real Docker
conflict/volume/seed exam ran and passed, not skipped. Both corrected public
message assertions pass. This run uses no lockf and no test-limit changes.
Fresh diff review round 2 of 2 is the remaining startup gate. Earlier failed
and interrupted runs remain non-qualifying evidence; settlement still awaits
its own separate review. No live state was changed.

## Handback validation after cache removal

Claude diff review round 2 passed with no blockers or majors; saved verbatim in
docs/reviews/practice-startup-error-diff-2.md. Optional nits remain open.
Parent-required parallel-tests 74dc5c7 merged at d3852e649dc074d5d056b5bb3b972c3da46f61fb.
The exact merged head passed the cache-free full suite: 185 scripts, zero failed,
exit 0, 2026-11-03T18:44:19Z to 19:18:35Z. No lockf or pass-cache reuse.
Record: practice-startup-error-suite-20261103T184419Z-2b586448.json and .log.gz.
Source tree and both log hashes checked; real Docker success marker confirmed.
Only documentation/evidence is committed after that tested head.
Both new-practice-startup-1 and new-practice-startup-2 closures were independently
confirmed by Claude. Missing continuation-budget accounting remains the early
crash consequence; no accounting evidence was invented or released.
No live calls, re-pin, preflight-area edits, or practice retry were performed.
Startup merges first; the founder's separate preflight branch rebases and merges
next, before any retry. Boat settlement 0292abc still requires separate review.
