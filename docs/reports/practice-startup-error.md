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
