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
uv run --with numpy --with scipy --with dbos==3.4.0 python -B tests/run.py
```

See [tests/README.md](tests/README.md) for individual suites and live probes.
[factory/README.md](factory/README.md) describes case-building entry points.

## Check factory status

Install the standalone client with `python3 bin/install-unbug` (Python and SSH only),
with `~/.local/bin` on your PATH. After saving the controller connection:

```sh
unbug status                    # configured default batch
unbug status b-other            # another batch
unbug report --json             # machine-readable scorecard
unbug board                     # Sealing Board: every case in every batch
unbug board --live --json       # only live cases, as JSON
```

The client reads `~/.config/unbug/client.json`; see
[factory/README.md](factory/README.md#operator-client) for its format. These commands
read the controller's stage, status, gates and sealed count without launching work.
The formatted view also shows recorded attempt state, worker assignments, batch
spending/reservations and settled call counts. In-flight usage is not a settled charge;
worker assignment does not prove liveness. `--json` retains exact micro-dollar values.

`unbug board` is the Sealing Board. It is generated on every read from the engine's case
cards, workflow records and the ledger, so it is never edited by hand and cannot go stale:
per case it shows stage, status, writer round, gates passed (and the failed gate), spend and
the time of the last recorded event. It also shows each case's time to seal against the
6-hour target. That clock starts at the case's first attempt and keeps running across resume
batches. The time is split by step kind into attempts that produced a result, attempts lost to
infra or provider limits, and the running attempt; it also counts worker setup, waits between
attempts and time held for a person. Live cases get a projection of the time left, using the
median time of each remaining step. The fleet line gives the median and p90 time to seal and
the five largest time sinks over the last week. On the control VM the same board comes from
`python3 control/campaign/campaign_board.py [--live] [--text]` or
`bin/unbug --config CONFIG board`. Sections it cannot read are named, never guessed.

## Benchmark rules

- [SPEC.md](SPEC.md): application, traffic, oracle and guard interface.
- [PROTOCOL.md](PROTOCOL.md) and [V2.md](V2.md): experiment and build contracts.
- [FACTORY.md](FACTORY.md): case contents, qualification gates and sealing rules.
- [CONTESTANT.md](CONTESTANT.md): contestant-facing instructions.

Bench internals and answer keys remain private. Distribute contestants only the
application, promise and guard interface. Medusa package source is not patched.
