# Empty input: whole case namespace and bounded Git discovery

Murphy row: `new-batch-auth-inputs-1` ("Empty batch input can reuse a case
namespace containing saved evidence"). Builds on `docs/designs/batch-auth-inputs.md`,
whose guard (`factory/batch_holder.py:empty_input`) is merged and reviewed
(`docs/reviews/batch-auth-inputs-diff-2.md`, PASS).

## Problem

The merged guard refuses a new empty reservation, and both locked dispatch
checks, when saved evidence for the case exists. It checks four things:
- the eight exact `launch_manifest.collection_files(case)` names in each sealed
  directory;
- `sealed/generations/<case>`;
- `<batch>/generations/<case>`;
- `<batch>/current/<case>.json`.

Real artifacts show two gaps.

1. **The guard's name list is narrower than what really lands in a case
   namespace.**
   - Non-batch collection (`factory/collect.sh:58,75`, `dest=$root/sealed`)
     accepts any `*.age`, plus `*.scorecard.json`, `*.scorecard.txt`,
     `*.progress.json` and `*.throwaway-key.txt`.
   - `factory/run.py:3346,3428` writes `<case>.continuation-budget.json` and
     `<case>.throwaway-key.txt` under `sealed/`.
     `factory/restore_ledger.py:169` writes `sealed/<case>.continuation-budget.json`.
   - The real tracked inventory holds
     `sealed/case-20261014T130816Z-a869de.throwaway-key.txt` (twice, counting the
     Git common checkout). Neither copy is a `collection_files` name, so on its
     own it does not stop an empty reservation of that namespace today.
   - Any future suffix will be missed the same way, because the guard lists
     suffixes instead of asking whether the namespace is occupied.
2. **Git discovery can silently resolve the wrong repository.** This is M1 in
   `docs/reviews/batch-auth-inputs-diff-2.md`, deferred there as non-blocking.
   - `batch.sealed_directories` runs `git -C root rev-parse --git-common-dir`.
   - If `root/.git` is a dangling symlink or a corrupt directory and a parent
     directory is a repository, Git walks up and exits 0. Probe on this host:
     returns `../.git`.
   - The canonical sealed directory is then missed, and "discovery must
     succeed" (design review-2) is not true.
   - This host's real layout makes the walk-up plausible: agent worktrees live
     at `<main checkout>/.claude/worktrees/<name>`, inside the main repository.

## Change

1. **`empty_input` checks the whole namespace in each sealed directory.**
   - It refuses if any directory entry is named exactly `<case>`, or starts with
     `<case>.` or `.<case>.`.
   - The last form covers `factory/transfer.py:63,68`, which writes
     `.<name>.transfer.lock` and `.<name>.<sha>.part`. An interrupted
     non-batch collection can leave only these. The real tracked inventory
     holds 18 such locks, for example
     `.case-20261019T061116Z-3826d5.checkpoint.tar.gz.age.transfer.lock`.
   - It replaces the per-suffix `lstat` loop for sealed directories with one
     `os.scandir` per directory.
   - The dot delimiter keeps names exact: `case-b-j1` does not match
     `case-b-j10.*`, and `g11-review-<case>.*` is a different namespace.
   - **Batch case names contain no dot.** This is derived, not stated in the
     code. `check_manifest` (`factory/batch_money.py:52,67-68`) restricts the
     batch id and the job names to `[a-z0-9-]+`, and builds the case as
     `'case-' + id + '-' + name`, or takes a `carry_from` case that was built
     the same way.
   - **Errors.** The `os.scandir()` call and the iteration over its entries are
     both wrapped.
     - A missing sealed directory is absent (`FileNotFoundError`), unless
       `lstat` shows that the path itself exists, as a dangling symlink. That
       refuses (diff review 1, N3). The base code admitted it.
     - Any other `OSError`, such as `NotADirectoryError` or `PermissionError`,
       raises `ValueError('request_refused') from None`.
     - So a `dispatch` that meets one ends terminally, as `failed`/
       `preflight_refused`, rather than as a `TEMPFAIL` retry: its `OSError`
       handler (the `except (money.MoneyWait, …, OSError)` clause in
       `dispatch`) never sees one.
   - `sealed/generations/<case>`, `<batch>/generations/<case>` and
     `<batch>/current/<case>.json` keep their `lstat` checks.
   - Replay, the dispatch-started boundary and the callers are unchanged.
   - This supersedes the "exact `collection_files` names" clause of
     `batch-auth-inputs.md`. "No prefix glob" still holds, because matching is
     anchored on the `.` delimiter.
2. **Git discovery is bounded to the checkout.**
   - `sealed_directories` runs Git with a copy of `os.environ` that drops
     `GIT_DIR`, `GIT_WORK_TREE` and `GIT_COMMON_DIR`, and sets
     `GIT_CEILING_DIRECTORIES=str(root.resolve().parent)`.
   - Dropping those variables stops an inherited one from bypassing discovery.
   - `resolve()` is needed because Git ignores relative ceilings and compares
     against the real path. Production `key_holder.ROOT` is already resolved.
   - With `root/.git` present but broken, Git now exits 128, and empty
     admission refuses as before.
   - A valid gitfile (linked worktree) or `.git` directory in `root` is
     unaffected, because the ceiling only stops searches above `root`.
   - `restore_inventory` keeps its local-only fallback on that error.

Deletes the guard's dependency on `collection_files` (the import and the
per-name loop). No other path is added or removed.

## Tests (`tests/factory/test_empty_input_real_namespace.py`)

Real artifacts are the tracked `sealed/` inventory, used read-only. None of them
is generated by the code under test.

1. **Every real case-named file, alone, occupies its namespace.**
   - Take every top-level file in `ROOT/sealed` named
     `case-<UTC>-<hex>.<suffix>` or `.case-<UTC>-<hex>.<suffix>`.
   - Copy each one byte-identically, under its real name and alone, into an
     isolated root with no `.git`.
   - `empty_input(root, batch, case)` must refuse, and the copy's SHA-256 must
     equal the original's.
   - The real file keeps its name. The neighbouring names `<case>0` and
     `<case>` minus its last character are passed as the `case` argument, and
     must be admitted.
   - On the pre-change code this test fails for the real `.throwaway-key.txt`
     file and for every real `.transfer.lock`. That failure is the red step.
2. **The real checkout, in place, with real Git.**
   - `batch.sealed_directories(ROOT)` runs unpatched and returns `ROOT/sealed`,
     plus the real common checkout's `sealed` when `ROOT` is a linked worktree.
   - For every real case name in the real inventory, `empty_input(ROOT, <empty
     temporary batch directory>, case)` refuses.
   - A name absent from every real directory is admitted.
   - The real tracked files (`git ls-files sealed`) keep their mtimes and
     hashes afterwards.
   - The common checkout's `sealed/` is shared with other sessions, so the test
     does not compare that directory as a whole, and it excludes in-flight
     `.part` partials from the cases it enumerates.
   - Discovery runs once with real Git, and its answer is reused for the
     per-case checks.
   - The test is skipped, with a reason, only if `ROOT/.git` is absent
     (installed release).
3. **Real Git walk-up is refused.**
   - A real temporary parent repository (`git init`) contains a checkout. The
     checkout's `.git` is set up three ways:
     - a dangling symlink;
     - an empty directory;
     - a valid checkout with an inherited `GIT_DIR` pointing at the parent
       repository.
   - In each case `sealed_directories` raises or ignores the parent,
     `empty_input` refuses (or still checks the checkout's own `sealed`), and
     `restore_inventory` falls back to local `sealed` only.
   - A real linked worktree (`git worktree add`: a gitfile to
     `.git/worktrees/<name>` with `commondir`) still resolves through the
     ceiling.
   - Before the change, the dangling-symlink probe resolves the parent
     repository.
4. **Reserve and dispatch wiring for a non-collection name.** This is
   contract-level and labelled as authored.
   - It uses the `test_batch_holder` fixture.
   - A real retained ledger is placed as the fixture case's
     `sealed/<case>.continuation-budget.json`. The bytes are the real
     `continuation_budget` of the saved `e15450` card already used by that
     fixture; the name is authored.
   - A fresh empty `reserve` refuses and writes neither `money.json` nor
     `reservations.json`.
   - Placed after `reserve`, the ledger makes `dispatch` terminal
     (`failed`/`preflight_refused`, `dispatch_started` false, no spawn). Empty
     replay of the reserved operation still returns the same operation.
   - A second variant places the ledger during preflight, after the first
     locked check, so that the second locked check in `dispatch` (the one just
     before `dispatch_started = True`) catches it. The test records that the
     first call admitted and the second refused.
   - A third variant makes the sealed path a regular file
     (`NotADirectoryError`). `dispatch` must end `failed`/`preflight_refused`,
     not `TEMPFAIL`. This is a regression guard, not a red step: the base code
     also refused here.
   - A fourth variant makes the sealed path a dangling symlink, and a new empty
     `reserve` must refuse.

Existing tests must pass unchanged: `tests/tools/test_qualify_batch_inputs.py`,
`tests/factory/test_batch_holder.py`, `tests/factory/test_restore_inventory.py`
and `tests/factory/test_practice_readiness.py`.
`test_all_exact_names_and_namespaces_refuse_empty_without_money`
(`tests/tools/test_qualify_batch_inputs.py:79`) patches
`batch.sealed_directories`, and its `<case>0` neighbour check at lines 95–96
still holds.

## Murphy

`new-batch-auth-inputs-1` stays **open**.
- **What tests 1–3 prove:** on real retained artifacts and real Git, every real
  saved file occupies its exact namespace. Discovery from a broken `.git`, or
  with an inherited `GIT_DIR`, no longer resolves an enclosing repository.
- **What they cannot prove:** no real saved evidence exists in a namespace that
  a batch manifest can reach. Manifest case names are `case-<batch id>-<job>`,
  lowercase only, and every retained case contains an uppercase `T`/`Z`. Test 4
  reaches `reserve` and `dispatch` only through an authored name, so it is
  contract evidence.
- **Closure path:** the real collected `case-b-plumbing-practice-3-smoke.*`
  artifacts from the 2026-11-04 live smoke, reserved empty under the real
  `factory/batches/b-plumbing-practice-3.json`. Those files are retained only on
  the separately owned practice4 branch, so this change does not use or alter
  them.

No new row. Gap 1 is a deficiency inside this row's own fix direction ("reject
exact-name artifacts"), not a new failure seen in a real run.

The register is not edited. The row stays open, and `docs/murphy-register.md`
is changed by a separately owned branch (practice4). The fix-direction wording
("exact-name") still describes the rule correctly: every match is exact on the
`<case>` component, and the integrator can align the wording when merging.

## Timeline

One implementation and review cycle. No live step.

## Risks

- **A legitimate new launch might see a `<case>.*` file before dispatch.** On
  the control host, batch collection writes to the launch state
  (`UNBUG_LAUNCH_STATE/collected`, `factory/collect.sh:11`), not to
  `root/sealed`. Holder publication writes to `<batch>/generations`. The
  existing suite's dispatch and collection lifecycle tests exercise this.
- **Cost:** one directory listing per sealed directory under the batch lock,
  which is about 230 entries here.
- No workers, model calls, money, keys or decryption.
