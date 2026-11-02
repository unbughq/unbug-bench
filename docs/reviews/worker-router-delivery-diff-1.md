# Worker router delivery: diff review 1 (goldfish, Mode: REVIEW)

**Verdict: PASS. No blockers, 2 majors, 6 nits.**

**Scope:** range `28b18d0..4b01d08a08e8f698b2f6cee382234d070a2ffde7`. Source commit is `1597620`; `4b01d08` only adds validation records, and `git diff 1597620 4b01d08 -- factory tests tools bin` is empty.

**Reviewed against:** `docs/designs/worker-router-delivery.md`, including the "Parent-approved after round 2" section, and design reviews 1 and 2.

**Personas and standards:** `zoom_out` and `implementation_readiness`, with `implementation-readiness-standard.md` and `docs/ENGINEERING.md`.

**What I did:** I made no edits, git mutations, network or provider calls, worker runs or delegations, and read no real secrets.

## Design conformance

**Production code**
- **One shared RAM directory.** `factory/worker_secrets.py` holds the constant: default `/dev/shm/secrets`, one override `UNBUG_TEST_WORKER_SECRETS`.
  - It is imported by `model_router`, `job_config`, `account_handoff` and `run`.
  - `model_runtime` reaches it through `model_router.SECRETS`.
  - I grepped `factory/*.py` for other worker Python readers of `/dev/shm`. None are left; the remaining hits are shell text in `launch.sh` and `bin/push-secrets`, which the exam maps.
  - Neither holder's dispatch environment passes the override.
- **Packing in `launch.sh` (lines 325–335).**
  - It sits right after the selection filter and before the need-check loop. It runs only when `--batch-release` is given; I confirmed both holders get that flag through `batch.bind`.
  - `held_secrets_b64` and the Codex login inputs are captured earlier and are unchanged.
  - On resume, the three names are appended to `$secrets` with no pack, probe or need-check.
  - The three `vm_creds` cases run `test -s` and read RAM files on the worker; nothing is interpolated into host argv.
- **`router_delivery.py`.** It checks owner, mode and symlinks, refuses duplicate keys, oversized input, non-HTTPS or userinfo/query/fragment URLs, control characters and an invalid CA. It refuses a conflicting tar member rather than overwriting it. Every failure prints one fixed label.
- **`model_router.router_request`.** One shared function backs both `_rpc` and the host `/status` probe. It uses `create_default_context` plus the optional CA, `ProxyHandler({})`, the renamed `_NoRedirect`, a bounded read, and keeps the localhost-HTTP allowance for `_rpc`.
- **Model subprocesses.** `FACTORY_ROUTER_*` is filtered after `os.environ` and `model_env` are merged.
- **Paid gate.** It calls `_rpc` from inside the runner process, so `paid_reserve` and `paid_settle` keep router authority. I checked this specifically: no input is missing on the Linux-only paid path.
- **Manifest.** `worker_secrets.py` is in both `TRUSTED_FILES` and `REQUIRED_RELEASE`. `router_delivery.py` is host-only and removed from `worker_files`. `model_router`, `budget` and `token_prices`, which the host packer imports, were already trusted.
- **Path persistence.** `control_resume.ENVIRONMENT` gains only the client-file path.

**Review 2 items, each checked in code**
- Explicit Claude executable via `FACTORY_CLAUDE_BIN` in the exec edge.
- Fail-closed `npm`, `apt-get`, `curl` and `sudo` (only `loginctl` passes).
- Private TMPDIR.
- Real `age` required, otherwise a loud skip.
- `test -s` before the router exports. Resume runs under `set -eu`; a fresh launch is guarded by `push-secrets`' own `test -s`.
- The client path is forwarded only if it is set.

**The new exam is a separate, real full-command exam**
- `test_complete_worker_command_router_delivery` runs the real `key_holder.serve` loop, `launch.sh`, `control_resume`, `push-secrets`, `job_config` and the runner.
- The router is the real `Server`/`Store` over loopback TLS.
- There are no patches of `run.py`, authority, metadata or transport.
- The older interruption test keeps its runner double, and the report correctly does not cite it as delivery evidence.

## Blockers

None.

## Majors

**M1. The exam drives the legacy holder path, not the one the next practice run uses.**
- **Scope:** `factory/batch_holder.py:811–812`; `tests/integration/test_batch_launch.py:416`; report sentence "Both holder launch paths pass the optional host client-file path."
- **What I found:**
  - `batch_holder.active()` is `HOLDER_ENABLED (False) or practice.active(...)`. The test policy does not activate practice, so the exam goes through `key_holder.serve` lines 742–747, not `batch_holder.dispatch`.
  - The next live step is a practice batch, which `batch_holder.dispatch` launches. That path adds `UNBUG_BATCH_OPERATION`, `UNBUG_PRACTICE_BATCH`, `FACTORY_ACCOUNT_POLICY`/`STATE` and `BOAT_TYPE`, and goes through `launch.sh`'s `batch_holder.py source/restore-check` branches.
  - No test sets `UNBUG_ROUTER_CLIENT_FILE` for `batch_holder.dispatch`. A grep of `tests/` finds the variable only in the integration test (key_holder path) and `test_router_delivery.py`.
- **Why it is only a major:** the router-delivery shell code is identical on both paths, and production uses the helper's default path, so I found no concrete missing input.
- **Why it still matters:** the report states "both holder launch paths" as evidence, and this "real launch" proof does not cover the practice dispatch that will actually run.
- **Fix:** either assert the forwarded path (present when set, absent otherwise) in the existing `test_batch_holder.py` dispatch tests around lines 154–174, or narrow the report to name the key_holder path.

**M2. The mutation (negative-control) evidence can't be reproduced or tied to a commit.**
- **Scope:** `docs/reports/worker-router-delivery-mutations.json`, `docs/reports/worker-router-delivery-export-mutation.json`, and the report's "Negative controls" paragraph.
- **What I found:**
  - Neither JSON names a source commit or tree.
  - No mutation script or patch is committed: a grep for `omit_pack`, `omit_worker_ca` and the other mutation names hits only the JSON.
  - So the design's key risk ("the end-to-end test must fail when delivery/export/TLS loading is removed") rests on writer-recorded results.
- **My independent reasoning supports the claimed kills:**
  - Removing the pack or the pushed token makes `push-secrets`' `test -s` fail, so the launch exits with no card.
  - Removing the export trips the supervisor `sitecustomize` assertions, which exit with code 95.
  - Removing the CA load makes TLS verification fail, so the run sits in `ProviderWait` until the outer timeout, with an empty `requests` table.
- **Limits of the kills:** `omit_worker_ca` is killed only by the 96-second outer timeout, not by a specific assertion.
- **Fix:** commit the mutation procedure (a sed or patch list per mutation plus the command) and add `source_commit`/`source_tree` to both JSON files.

## Nits (optional)

1. **`account_handoff.exports` runs on the host** (`launch.sh:339`). It now builds the worker path from the host's `UNBUG_TEST_WORKER_SECRETS` (`account_handoff.py:146`). Production is unaffected because the host never sets it. Still, a worker path should not depend on host environment; the literal `/dev/shm/secrets`, as in `vm_creds`, avoids the coupling.
2. **`CLAUDE_PREFIX` now follows `tempfile.gettempdir()`** (`model_runtime.py:34`), but `worker-release.json:28` still pins `/tmp/factory-claude-cli/bin/claude`. A worker with a non-default TMPDIR would install into one place and qualify another. Since the exam sets `FACTORY_CLAUDE_BIN` explicitly, consider keeping `/tmp` for `CLAUDE_PREFIX` and changing only the OpenCode config path.
3. **The audit hook in `worker_delivery_edge.py` is partial.** It watches `open`, `remove`, `mkdir`, `rmdir`, `listdir` and `scandir`, but not `stat`, so `Path.is_file()` probes of real `/dev/shm` are not caught. On macOS `/dev/shm` doesn't exist, so the hook was never challenged on this host.
4. **`verify_exam`'s sentinel scan has gaps.** It covers job logs, `calls.jsonl`, sealed `.json`/`.txt` and the whole control home, which includes launch state. It skips other `runtime/` files such as `reservations.json`. It also asserts the `job_money` batch/job but not the receipt bindings the design table names.
5. **The resume test runs a reconstructed slice of `launch.sh`** with its own `set -eu`, not the real `resume_one` heredoc at `launch.sh:621`. The report's limit column says this honestly.
6. **The Linux model-executable branch is unqualified.** On Linux the exam requires `model-edge.json`. Its success there, including the `sudo` and XDG prerequisites of the paid gate, is unproven on this Mac. The report says so.

## Evidence I checked myself

**Suite records**
- **Hashes match.** Both suite logs and the passing-rerun log decompress to the recorded `log_sha256`, and the compressed hashes match too.
- **Source trees match.** `1597620^{tree}` = `1cc91978…` and `607bf58^{tree}` = `9db9910c…`, as recorded.
- **Final full run** (`…072446Z-8ca7e013`): "174 test scripts run; 3 failed". The failures are:
  - `test_isolation_timeouts`: the 2-second `wait_for` deadline in `processes.shell` raised `TimeoutError`.
  - `test_model_router`: `BudgetError('timeout')` in the per-call quota test. That test patches `router._rpc` with `store.rpc`, so the new TLS code is not on its path.
  - `test_parallel`: "grandchild did not start" against its 10-second deadline.
  - All three are deadline failures, and none of the three test files or `bin/processes.py` changed in the range.
- **The new exam really ran.** `tests/integration/test_batch_launch.py` reported "Ran 8 tests in 42.285s OK" with no skips. The shorter "Ran 4" lines are nested qualification runs.
- **Rerun record `…083651Z-a7ae8f44`:** all three exit 0, with `BENCH` set and the same source tree. The `…083144Z` record is correctly marked non-qualifying.
- **First-run corrections:**
  - The historical probe's `environment` literal equals the base `ENVIRONMENT` minus exactly the three later-added keys the old code subtracted. `probe.py` did not change in the range, so this is a faithful correction, not a weakening.
  - `worker_secrets.py` was added to both gate-smoke preallocation lists.
- **The report makes no all-green or live claim.** The new Murphy row stays open, and no rows are closed.

**My own runs** (on `4b01d08` with `BENCH` set, load about 17–34)

| Test script | Result |
|---|---|
| `test_router_delivery.py` | 5 OK |
| `test_batch_launch.py -v` | 8 OK in 59 s; the full-command and missing-config tests ran |
| `test_isolation_timeouts.py` | 26 OK |
| `test_model_router.py` | 42 OK |
| `test_parallel.py` | exit 0 |
| `test_cleanup_qualification_evidence.py` | 5 OK |
| `test_gate_smoke.py` | 7 OK |
| `test_launch_manifest.py` | 2 OK |
| `test_job_config.py` | 6 OK |
| `test_model_runtime.py` | 3 OK |
| `test_key_holder.py` | 4 OK |

**Secret handling**
- The token reaches the worker only through stdin, the tar, push-secrets and RAM files.
- It is absent from boat argv (the edge asserts this, and `calls.jsonl` is scanned).
- Refusals print only fixed labels.
- `HTTPS_PROXY` is ignored (tested).
- A redirect is not followed and the bearer token is not forwarded (tested: `calls == ['/status']`).

## Limits

- I did not rerun the full suite or reproduce the mutations, which would need edits to a copied tree.
- The Linux branch was not executed.
- Nothing was checked against live deployment: the control-VM RAM file pair, the service restart, or the effect of `ProxyHandler({})` on real worker egress.
- Reading the real restore inventory was limited to what the integration test itself does.

## Writer disposition

PASS accepted; no blocking finding remains. Per the parent's stop-on-pass
instruction, no further code/test changes or second review round are started.
M1 and M2 remain open: the full-command exam covers key_holder.serve rather than
practice batch_holder.dispatch, and the mutation records lack reproducible,
commit-bound procedures. The report now states these limits explicitly. The six
optional nits remain open too; none is rejected or claimed fixed. No Murphy row
is closed and no live action is authorized by this review.

