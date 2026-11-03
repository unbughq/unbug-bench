**FAIL.** One blocker, two majors and five nits. The blocker is a one-line fix.

I read only the worktree `t3/batch-service-control-vm` at `bef877d`. Mode was REVIEW, with the zoom_out, design_critic and implementation_readiness personas, against `heilmeier-standard.md` and `implementation-readiness-standard.md`. I made no edits and ran no Docker, network or provider calls. I used no delegates.

## Round-1 findings: where they stand

| Finding | State |
|---|---|
| B1 mechanism | **Settled.** `commands.log:1–2` reads "Creating", so Compose did not take over the old container. That is shown by retained evidence, and the local reproduction agrees. |
| B1 fix | **Not fully fixed.** The design does the steps in the wrong order. See new blocker B1′. |
| B2 | **Fixed.** `sh` gets a bounded output tail and the card gets a constant pointer. Startup reaches `sh(check=True)` through the child's stderr, which goes to `commands.log`. The child's `bench.command` error text, including the Docker message, therefore lands in the tail. |
| M1 | Fixed: `COMPOSE` is kept. |
| M2 | Fixed: the new JSON record and the secret-file scanner are gone, and the design no longer overclaims about the archive. |
| M3 | Fixed: writers get a fresh seeded shop before any model runs. |
| N1–N4 | Fixed. |

## Blocker

### B1′. Removing the container after `down -v` leaves the old database in place, so the "fresh" startup fails on the most likely real state
**Scope:** "One existing preparation owner", the phrase "after existing down -v and before setup", and exam 1.

**Where the old container most likely came from.** The bake script runs `down -v`, then `bin/setup`, then `docker ps -q | xargs docker stop` (`bin/bake-image.sh:16-23`). So the leftover `unbug-bench-postgres-1` is most likely the bake's stopped Postgres. That container has the named volume `unbug-bench_postgres-data` attached, holding the baked, already-seeded database.

**Why the design's order fails on that state.**
1. Docker refuses to delete a volume that any container uses, even a stopped one. Compose's `down -v` turns that refusal into a "Resource is still in use" warning and exits 0. So `down` succeeds and the volume survives.
2. `docker rm -f` then removes the container but not its named volume.
3. `setup()` starts Postgres on the old data directory. Migrate and seed run against an already-seeded database.
4. Then `CREATE ROLE bench_checker` (`bin/bench.py:337`, which runs with `ON_ERROR_STOP=1`) fails because the role already exists. `CREATE DATABASE medusa_seed` would fail the same way.

**Consequence.** Every startup on that image fails, at $0 but every time. That is a pit stop, and it contradicts the design's claim that the startup shop is fresh.

**Why the planned exam misses it.** Exam 1 uses a fixed-name container without labels and no volume, and its setup step only runs `up`. The author's local reproduction also only checked `up`. Neither would catch this.

**Required:**
- **Fix:** in `prepare_factory_main`, force-remove the four fixed names *before* `dc("down", "-v")`. Once nothing holds the volume, `down -v` deletes it. This order is also correct if the old container had no volume, so it costs nothing either way.
- **Exam 1:**
  - The leftover container must mount the project's data volume, with a marker written into it.
  - After preparation, assert the marker is gone. That proves the volume is fresh.
  - Also run at least the step that fails on stale data: `CREATE ROLE`, or the seed-template SQL. Running `up` alone is not enough.

## Majors

### M1′. Exam 1 needs an isolated test project, but the cleanup names are hardcoded
**Scope:** exam 1 against the cleanup paragraph.

- The cleanup removes the literal names `unbug-bench-{postgres,redis,medusa,medusa-b}-1`. `bench.COMPOSE` is fixed to the project `unbug-bench` (`compose.yaml:1`, `bench.py:15`).
- Exam 1 requires a "unique project namespace via test adapter". In that namespace the hardcoded names point at nothing, so the test cannot exercise the real cleanup line without the implementer inventing a seam.

**Required:** decide this in the design. Either:
- build the names from one module constant, say the project name, that the test patches together with `COMPOSE`; or
- have the test patch `bench.command` and `bench.dc` and run against the real names.

**Also required:** say how exam 1 behaves on a machine without Docker:
- **Skip:** then say where it runs for real to close the Murphy row.
- **Fail:** then say so explicitly.

### M2′. The design doesn't say how to force `check=True` through the existing adapter
**Scope:** "Use check=True on this startup adapter".

- `_prepare` calls the main preparation with no `check` argument (`factory_pool.py:62-63`).
- It calls retirement and extra slots with `check=True` already (`factory_pool.py:50`).
- So `lambda cmd, **kw: sh(c, cmd, check=True, **kw)` raises `TypeError` (duplicate keyword) on any extra-slot or retirement call. A plain copy of G3's lambda instead returns `False` with no message tail.

**Required:** state one exact form. For example:
- `execute=lambda cmd, **kw: sh(c, cmd, **{**kw, 'check': True})`; or
- keep G3's lambda and add `if not ok: raise RuntimeError(...)`. This form loses the tail, so the first is the one that meets B2.

Also state the call (`prepare(1, fresh=True, ...)`, with `previous_slots` left at its default) and confirm it runs in every mode the old `up` ran in: dry-run, rehearse, audit, statement-only and extension.

## Nits

- **N1. Ignore short environment values in redaction.** Values like `1` or `true` under a name like `*_AUTH_ENABLED` would get masked all over the tail. Skip values shorter than about 8 characters. Read the tail back in binary and decode with `errors="replace"`, because seeking a text-mode file to a raw byte offset is unsafe.
- **N2. Update the stale records.**
  - The Murphy rows `new-practice-startup-1` and `-2` still describe revision 1's fixes ("Remove redundant unlocked pre-start", "structured exception evidence").
  - `factory/README.md:343` still documents the early `up`.
  - Both belong in the target scope.
- **N3. The startup lock fails fast.** `prepare(fresh=True)` takes `.bench.lock` with `LOCK_NB`. If anything still holds it at startup, the run fails at once with `BlockingIOError` instead of waiting. That costs $0 and is acceptable, but say so under Risks.
- **N4. Put a number on the extra setup time.** Startup now runs a full build, migrate and seed, and so does G3, in every mode including statement-only rounds. Give a rough figure from bake or G3 timings so the Heilmeier cost answer is complete.
- **N5. G3 failures still produce no message tail.** At G3, a failed preparation still becomes `InvalidInfra("bench setup did not complete")`, because G3's adapter has no check. Note this as out of scope.

## Scope and size
- The smallest-change goal is met: the design reuses the existing locked owner and deletes the unlocked startup route.
- Nothing speculative is added. I searched for an existing text-redaction helper and found none to reuse; `tools/unlock_sealed_audit.py:scrub` removes reasoning fields, not secrets.
- Boat settlement is correctly left out.

## Smallest change that would pass
1. In `prepare_factory_main`: remove the four fixed names, then `down -v`, then `setup`.
2. In exam 1:
   - the leftover container mounts the project volume, with a marker;
   - after preparation the marker is gone;
   - the role/template SQL step runs;
   - the cleanup names come from one patchable constant;
   - the design states whether the test skips or fails without Docker.
3. Write the exact `check=True` adapter form into the design.

**Verdict: FAIL** (B1′ open). Since this was the final round, the writer goes back to the parent. The fix is a reorder plus a stronger exam, not a redesign.

## Parent disposition: parent-approved after round 2

All findings accepted. Parent directs fixed-name removal before down -v, real Docker volume-marker and SQL exam, one patchable project constant, exact check=True adapter across all modes, short-env-value exclusion, binary tail reads, and updated records. No round 3. Implement and use plain lockf for the full suite, then at most two diff-review rounds.

## Parent disposition
Parent-approved after round 2: implement B1′ remove-before-down and real mounted
volume/seed SQL exam; M1′ COMPOSE_PROJECT constant and mandatory Mac Docker run;
M2′ exact check override adapter in all modes. Apply N1/N2; retain N3/N5 limits.
No round 3. Diff review checks the implementation and real evidence.
