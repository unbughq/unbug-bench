# Practice startup repair, diff review round 1 of 2

**Verdict: FAIL.** One blocker and one major are open. Both are small fixes inside the approved design, and neither needs a design round 3.

Scope: `467a884..8a0f54a`. Runtime change is `8f4aafb`, the test-double correction is `c3a1f6d`, and `8a0f54a` only adds records. I reviewed against `docs/designs/practice-startup-error.md`, design reviews 1 and 2, and the parent's resolutions after round 2. I used the `zoom_out` and `implementation_readiness` personas with the implementation-readiness standard. Everything was read-only: no edits, no Docker, no network or model calls, and no suite run.

## Blocker

**B1. Command output can now reach the public scorecard through `early_probe`.**
- **Where:** `factory/run.py:184-186` (the `sh` change), reaching the card through `factory/run.py:2839-2840` and `:2850`.
- **What happens:** `sh` is shared by the whole runner. Every `check=True` failure now raises `RuntimeError("<exe>: exit N\n<log tail>")`, not just at startup.
- **How it gets out:** `early_probe` catches any `Exception` and stores `f"{type(error).__name__}: {error}"[:200]` in `c.card["early_probe"]["skipped"]`. That card is written to `sealed/*.scorecard.json`, the file the new tests treat as public.
- **Example path:** `early_probe` → `calibrate` → `sh(... bench.reset(... load_scenario(base)) ..., check=True)` at `run.py:2668`. The pilot commands in `make_pilots` take the same route.
  - Before this diff, the card got `RuntimeError: exit 1`.
  - Now it gets up to about 180 characters of the encrypted command log: tracebacks, case paths, psql `LINE 1: …` echoes of scenario SQL.
  - Redaction removes credentials and URLs, not case content.
- **Why it blocks:** the design says "never put the output tail/message in the card". Section 4 of `docs/ENGINEERING.md` keeps the protections that hide cases from contestants. The new card checks only cover the top-level handler path, so they don't catch this.
- **Smallest fix:** in `early_probe`, store only the exception type or the first line of the message. Add a test: a real `sh` failure inside `early_probe`, then assert the card has no tail text.
- **Other catchers I checked:**
  - `provider_preflight` only stores `BudgetError`.
  - The `--probe` errors map holds no case data.
  - `record_crash` writes `gate-details`, which stays in the encrypted work tree.
  - `early_cheat_check` re-raises.
  - So `early_probe` is the only path I found from this diff to the public card.

## Major

**M1. No test protects the forced `check=True` in the startup adapter (M2′).**
- **Where:** `tests/factory/test_practice_startup.py`, the stub `prepare` in the mode test; and `factory/run.py:3412-3414`.
- **What the real code does:** the fresh path in `factory_pool._prepare` (`bin/factory_pool.py:61-66`) calls `execute(args, **kwargs)` with no `check`. Only the adapter's `{**kw, 'check': True}` turns a failed main setup into an exception. Without it, `sh` returns a status, `prepare` returns `False`, and `run.main` ignores that return and carries on to model selection with no shop. That is exactly the "fail before models" property the design depends on.
- **What the test does:** the stub calls `execute([...], check=True)` explicitly. Swap the adapter for a plain `lambda cmd, **kw: sh(c, cmd, **kw)` and all 8 mode subtests still pass. The stub only proves that a duplicate `check` key doesn't crash.
- **Smallest fix (either one):**
  - make the stub call `execute(args, cwd=..., timeout=3600)` with no `check`, the way `factory_pool` does; or
  - in `run.main`, raise if `prepare(...)` returns `False`.

  Doing both costs one line each.

## Checked and found sound

- **Removal before `down -v`** (`bin/bench.py:366-371`):
  - Exactly four fixed names, from `COMPOSE_PROJECT`.
  - A failed `rm` is suppressed, following the `remove_seed` convention.
  - `setup()` runs after `down -v`. No other containers are enumerated.
- **Real Docker exam** (`RealDocker`):
  - It uses an isolated project (`unbug-startup-test-<uuid>`) with `COMPOSE` and `COMPOSE_PROJECT` patched together, `--pull never`, and `--no-build`. The image must already be cached or the test fails. It skips only if the Docker binary is missing.
  - Setup is real: an unlabelled fixed-name Postgres mounts the labelled project volume, with a marker file, `bench_checker` and `medusa_seed` already created.
  - It proves the real name conflict, and that `down -v` alone leaves the volume in place.
  - Then the real `factory_pool.prepare(1, fresh=True)` runs, with the real lock and the real `prepare_factory_main` (only `setup` and `stop_inventory_services` are replaced). After it, the marker is gone, both SQL statements succeed, the unrelated container survives, and a non-blocking flock confirms the lock is held. This repeats for G3.
  - Cleanup touches only its own project.
  - Both full-suite logs contain `REAL DOCKER: conflict, mounted-volume freshness and repeated seed SQL passed`, and the file reports `Ran 3 tests … OK` with no skip.
- **Startup call:** `prepare(1, fresh=True, execute=...)` with `previous_slots` left at its default. It replaces the old `up` on the same line, so it runs in the same modes. The mode test covers all 8 modes, with `pick_models` set to throw.
- **Diagnostics in `sh`:**
  - The start offset comes from `fstat` before the command runs, and the tail is read after the log is closed.
  - The read is binary and capped at 4096 bytes, decoded with `errors='replace'`.
  - When the read starts mid-log, the first partial line is dropped.
  - Environment values shorter than 8 characters are skipped. PEM blocks (including a truncated head), bearer tokens, `sk-` keys, age identities and URLs are redacted.
  - No argv goes into the message. The traceback still goes to `runner.log`. The handler card's `error_evidence` is the constant `logs/runner.log`.
  - Tests cover both capture modes, exclusion of older log content, the size bound, and the sentinels.
  - The encrypted test archives contain the conflict text, and the public cards do not.
- **Worker-command edge** (`tests/integration/worker_delivery_edge.py`): the Docker double returns the conflict until the exact four-name `rm` runs, then allows `up`. psql, seed IDs and app `/health` are labelled authored doubles, and router TLS stays real. The report also calls this offline delivery coverage, not real Docker, which is the right distinction.
- **Test-double correction** (`c3a1f6d`): the four `sh` doubles now match the real return contract (`0`, or `stdout` plus `returncode=0` when capturing). No assertions were changed and no production files were touched.
- **Historical cleanup-evidence fix:** the statuses now come from `SCANNER_SOURCE`, the scanner embedded in the retained `probe.py`, which gives `('reserved', 'finished', 'reconciled_expired')`. They no longer come from today's `inventory.STATUSES`. The retained `probe.py` itself is unchanged in this range.
- **Suite provenance:**
  - Both suite JSON records match their logs: the `log_sha256` and `compressed_log_sha256` values are correct.
  - `c3a1f6d` has tree `2fa1264…`, as recorded.
  - Only records changed between `c3a1f6d` and HEAD.
  - The failed run at `8f4aafb` is kept, marked `qualifying: false`, and its log shows exactly the three stream-d files failing.
  - The qualifying run shows `180 test scripts run; 0 failed`.
- **Murphy rows:**
  - `new-practice-startup-1` is closed by the real Docker volume, marker and SQL regression. That closure holds.
  - `new-practice-startup-2` is closed by the real `sh` and handler tests. They prove what the row claims, but the "public card excludes output" property is only proven on the handler path (see B1).
- **Records:** the README and docstrings match the change. Design-review dispositions are recorded.

## Nits

- **N1.** `COMPOSE_PROJECT` repeats `name: unbug-bench` from `projects/medusa/compose.yaml`, and nothing pins them equal. The edge test pins the literal names, not the yaml. One assertion would close it, or derive the constant from the yaml.
- **N2.** `command_error_tail`: if the last line alone is over 4096 bytes and the read starts mid-log, dropping the partial line leaves an empty tail. That's safe, but the diagnostic is lost.
- **N3.** URL redaction (`https?://\S+`) removes every URL, which goes further than the design's "userinfo/query". It's safe, and worth one word in the report.
- **N4.** `SCANNER_SOURCE` is read from `body[0]` by position, while `PROBE_ENVIRONMENT` next to it is matched by name. Matching `SCANNER_SOURCE` by name would be consistent.
- **N5.** The G3 repeat in the Docker exam starts from a container Compose already adopted, so the unadopted-conflict case is only exercised at startup. That's acceptable under "repeat as G3", but worth noting.
- **N6.** The report says the Docker exam took 15.875 s; the suite log shows 21.2 s for the file. Both are fine; just make sure the report names which run it quotes.

**To pass round 2:** fix B1 with its test and fix M1. No suite rerun is needed beyond the touched files plus the locked full suite the flow requires.

## Writer disposition
B1 accepted: early_probe publishes only the exception type; real sh/calibration regression checks that case output stays out of the card.
M1 accepted: the mode-test adapter double now calls execute without check, matching fresh factory_pool preparation, and returns its success status. No production guard or second preparation path added.
N1 pins the constant to the compose name in the Docker exam. N3/N5/N6 are clarified in the report. N2 and N4 remain optional and open.
