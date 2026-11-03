# Practice startup error — revision 2

Make a fresh worker ready before it can spend on models, and retain an actionable
error when startup fails. One offline increment, $0 provider spend. No live retry
until merge, repin and parent approval.

## Evidence and mechanism
The b75c9b4 worker made zero router requests. Retained real commands.log:1–2 says
Postgres and Redis **Creating**, not Recreate; :3–4 reports the existing fixed
name `/unbug-bench-postgres-1`. Compose 5.3.1 did not adopt that container.
RuntimeError: exit 1 is at run.py:3387 -> sh:161. The exact sanitized exception
and locations are in tests/factory/fixtures/practice-startup-conflict-20261103.json.
A name collision survives ordinary Compose down when its container is not adopted.
Deleting only the early up would defer the same failure until after paid writing.
The stopped worker's old container labels cannot now be recovered; no race claimed.

## One existing preparation owner
Replace run.main's early standalone Compose up with factory_pool.prepare(1,
fresh=True, execute=the existing logged sh adapter), before model selection or
preflight. Its existing root .bench.lock remains held through the child setup.
Use check=True on this startup adapter so failed setup raises with its output
before models. Preserve G3's independent fresh preparation and normal extra-slot
retirement. Keep runner.COMPOSE: extension_evaluator and comparison tests use it.
Writers retain a freshly seeded working shop for their pre-G3 self-checks.

In bin/bench.py prepare_factory_main, after existing down -v and before setup,
force-remove only unbug-bench-{postgres,redis,medusa,medusa-b}-1. This is the
existing disposable factory slot-zero namespace; no enumeration or removal of
other Docker containers. Reuse command and the existing remove_seed convention:
suppress RuntimeError from rm (missing names), then let setup fail normally on a
Docker error. Keep setup's seed cleanup. This path is factory-only and called by
the locked pool; ordinary exam setup/reset does not acquire new deletion behavior.
Update factory_pool's docstring: fresh preparation is used before models and G3.
Delete the unlocked startup route; add no new launch or retry mechanism.

## Actionable retained diagnostics
In run.sh, open commands.log in a+ mode and remember its end offset before the
command. On check=True nonzero exit, flush then read at most the final 4096 bytes
written since that offset. Raise RuntimeError with executable basename, exit code
and that bounded output. For capture=True, stdout is appended as today; stderr
already uses the same log. A ponytail comment states concurrent commands may
interleave in that tail. Do not include argv, which can contain credentials.
Before adding the tail, redact exact nonempty sensitive environment values
(names containing TOKEN, SECRET, PASSWORD, KEY or AUTH, case-insensitive), bearer
values, sk-* credentials, age private identities, PEM private-key blocks and
URL userinfo/query strings. No RAM-secret scanning or extra secret copies.
Keep the existing chained traceback log write. Set the public card's constant
error_evidence to logs/runner.log; never put the output tail/message in the card.
Delete revision 1's new JSON artifact, secret-file scanner and fallback subsystem.
Existing encrypted commands.log is unchanged: tests must not claim the whole
archive is secret-free. New exception text and public card must exclude sentinels.

## Accounting and tests
Missing continuation budget is a consequence of the pre-model crash. Preserve the
collection refusal/hold; do not fabricate zero usage. Pre-admission runner errors
still requiring repair before collection are a known pit stop, not closed here.

1. Add a real-Docker offline regression, cached images only, isolated unique
project namespace via test adapter: a fixed-name container without Compose labels
reproduces the retained Creating/conflict. Exercise real locked preparation down,
fixed-name removal and setup; unrelated sentinel container survives. The test
setup adapter runs real Compose up --pull never --no-build for Postgres/Redis;
image builds and app migrations are outside this container-ownership exam.
Repeat the same preparation as G3 and require success. No shared default project.
2. Full worker-command exam uses the retained conflict at the Docker edge until
fixed-name removal, then allows preparation; assert removal/setup before first
router request. With cleanup deleted, fail before model admission. Authored edge
plus real captured error, not live-cloud qualification.
3. Real sh and runner handler: failing command emits the captured Docker error;
retained traceback contains it plus exit/type, public card points to it without
output. Test both capture modes, 4096-byte bound, old-log exclusion, env/pattern
sentinels and original exception preservation. Existing G3/pool tests must pass.
4. Locked full suite and fresh diff review, maximum two rounds.

Murphy new-practice-startup-1 closes only on the owner/G3 conflict regression;
new-practice-startup-2 on real-error retained-message/card-reference regression.
Risks: full fresh setup costs startup time but spends no model budget. It already
owns G3 setup/seeding; do not claim this offline evidence qualifies a future run.
