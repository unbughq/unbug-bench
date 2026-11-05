# Unbug bench

A benchmark for testing whether agents preserve Medusa inventory consistency as
requirements change. The case factory builds and qualifies sealed cases for the
exam. See [EXAM.md](EXAM.md) for the experiment and
[ARCHITECTURE.md](ARCHITECTURE.md) for the implementation.

## Run the public benchmark

Requirements: Docker Compose, Python 3, Node.js 22 or newer, npm. From this directory:

```sh
cd projects/medusa
npm ci --no-audit --no-fund
node verify-lock.mjs
cd ../..
bin/setup
bin/reset
bin/check
bin/run-case medusa-oversell none 30          # stress traffic (default); --normal for the fixed schedule
bin/calibrate
bin/verify-negative
bin/replay results/runs/<run-directory> [--runs 1,2,3]
bin/checkpoint --scenario scenarios/dev/S9-cleanup-job --guard reference --runs 3 [--claims claims.json]
bin/score-claims <checkpoint.json> <claims.json>
bin/stress-compare [--runs 30]
bin/fake-pass-check <guard> [<guard> ...] [--runs 5]
```

`bin/setup` is for a fresh volume. `bin/reset` restores the seeded database and
checks its baseline before each trial. Bench commands share a lock; use separate
factory slots for parallel trials.

The judge counts unfulfilled units promised on live orders against stock, rather
than trusting reservations. Backorders are exempt. A passing guard must also
preserve legitimate orders, admin edits, cancellations and resale. Operational
errors invalidate evidence; they do not prove a guard correct.

## Develop

Run the offline tests:

```sh
uv run --with numpy --with scipy python -B tests/run.py
```

See [tests/README.md](tests/README.md) for individual suites and live probes.
[factory/README.md](factory/README.md) describes case-building entry points.

## Benchmark rules

- [SPEC.md](SPEC.md): application, traffic, oracle and guard interface.
- [PROTOCOL.md](PROTOCOL.md) and [V2.md](V2.md): experiment and build contracts.
- [FACTORY.md](FACTORY.md): case contents, qualification gates and sealing rules.
- [CONTESTANT.md](CONTESTANT.md): contestant-facing instructions.

Bench internals and answer keys remain private. Distribute contestants only the
application, promise and guard interface. Medusa package source is not patched.
