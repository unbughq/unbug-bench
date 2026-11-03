# Regression tests

Run the complete offline suite from the repository root:

```sh
uv run --with numpy --with scipy python tests/run.py
```

The analysis tests require NumPy and SciPy; other suites use their existing local
prerequisites. Select subsystems or inspect the selection without execution:

```sh
python3 tests/run.py factory bench
python3 tests/run.py integration tools control
python3 tests/run.py --list
```

Scripts run in parallel, one per CPU by default. Set `-j N` or `TEST_JOBS=N` to
change that, and use `-j 1` to check whether a failure only happens in parallel.
Each script's output is buffered and printed in order.

The runner sets `BENCH` to this checkout and executes each test file in a fresh
Python process. This covers unittest cases, import-time assertions, and standalone
scripts, including hyphenated filenames. A failed script makes the command fail.
No live-stack test is selected by the offline runner.

| Directory | Coverage |
| --- | --- |
| `factory/` | Factory gates, budgets, recovery, model execution, and orchestration |
| `bench/` | Benchmark judging, CLI behavior, exam flows, and inventory replay |
| `integration/` | Deployment, staging, source freezing, and runtime integration |
| `tools/` | Operational tooling and public qualification; historical fixtures are local |
| `control/` | Control VM behavior |
| `analysis/` | Scoring validity and report inputs |
| `harbor/` | Offline Harbor adapters, synthetic upstreams, and local responder checks |
| `live/harbor/` | Explicit Docker, pinned CLI, Harbor, or running-stack probes |
| `live/judge/` | Docker/Postgres property checks of the scientific judge |
| `live/guards/` | Reference-guard regressions requiring the pinned Medusa Node runtime |

Each file can also be run directly; factory checks need `BENCH` set to the
checkout, for example `BENCH="$PWD" python3 tests/factory/test_run.py`.
For unittest-only discovery within a subsystem:

```sh
BENCH="$PWD" python3 -B -m unittest discover -s tests/factory -p 'test_*.py'
```

Discovery alone does not execute all standalone main routines or hyphenated files;
use `tests/run.py` for the complete offline suite. Tests may use temporary files,
local loopback services, or installed local executables, but do not call model or
cloud providers. Live probes must be invoked explicitly after preparing the stack
and arguments described in their docstrings, for example:

```sh
python3 tests/live/harbor/keyswap/test_clients.py /absolute/linux/codex /absolute/linux/claude
```

Benchmark task bundles still contain `tests/test.sh`, verifier adapters, and Docker
files. Those are executable benchmark payloads, not repository regression suites,
and must remain in the task bundle.

## Deployment fixtures

`integration/deployment_fixture.py` builds a small temporary release covering every owned
source directory. It binds hashes and source count into the maintained offline
installer in `tools/install_source.py`, then binds those release inputs into a
temporary copy of the real deployment adapter. Tests exercise the actual
installation, verification, permissions, quarantine, and launcher sequencing.
Tampering is tested after the bindings are frozen.

The installer was promoted from the public release's offline installation engine;
the release-specific hashes and count became required bindings. Future release
builders can use this maintained source. This does not alter or requalify the
historical release, its artifacts, or the production adapter/launcher pins.

The tests deliberately do not depend on ignored `results/infrastructure` archives.
Hydration progress is synthetic; unit checks and actual launcher integration
checks remain separate. The obsolete source-text test of an archived one-off
controller was removed because current launcher tests exercise readiness ordering
and refusal behavior directly.
