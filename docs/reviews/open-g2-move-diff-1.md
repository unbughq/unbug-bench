# Goldfish diff review 1: move open-g2-verdicts into tools/

Reviewer: fresh Claude Sonnet subagent, persona implementation_readiness, Mode: REVIEW, read-only. Verbatim.

Findings:

1. **NIT** – `tools/open-g2-verdicts.py` line 19, `OUT`. It is hardcoded to a past session's scratchpad (`/private/tmp/claude-501/.../00d02e9b-.../scratchpad/g2-open`). This is carried over unchanged from the original, so it isn't a regression. It does keep decrypted output outside the repo, so no secret reaches a tracked file. Once the script is tracked, a later session will write to or fail on that stale path, and `main()` refuses to run if the path already exists. Consider an env var or a CLI argument for it later.

2. **NIT** – `factory/RESCUE-INVENTORY.md:231` (an existing file, not part of this change). It still says the test needs the ignored `results/.../open-g2-verdicts.py`. That is now stale. The old copy in `results/` is still there but nothing references it, so it is harmless and ignored.

3. **NIT** – `tests/tools/test_open_g2_verdicts.py`, where the test patches `ROOT` and `OUT` (line 64). The test does not check the new `parents[1]` value directly. It does cover it indirectly. `runpy.run_path(SCRIPT)` runs the real `import unlock_sealed_audit` and `import run`, so a wrong `sys.path` would fail at load. I confirmed the imports resolve: `tools/unlock_sealed_audit.py`, `factory/run.py` and `bin/` all exist.

Checks:
- **Diff:** `diff` shows the script differs only on the ROOT line, `parents[3]` to `parents[1]`. Both give the repo root, because `tools/x.py` is one level below the root and the old `results/infrastructure/<dir>/x.py` was three.
- **Paths from ROOT:** `ROOT/'tools'`, `ROOT/'factory'` and `ROOT/'bin'` all resolve correctly from `tools/`. The bundle path `ROOT.parent/'unbug-bench-<id>-restore-14-20261029'` is unchanged in meaning. It sits beside the checkout, so it moves with the worktree exactly as before.
- **Test:** the test diff is the one-line `SCRIPT` change. The test still runs the moved script, and `python3 -B tests/tools/test_open_g2_verdicts.py` passes with 1 test OK.
- **Secrets:**
  - The age identity is read through `getpass`, checked against the `AGE-SECRET-KEY-1…` pattern, and passed only to `unlock.decrypt_one`.
  - The error path prints only the exception class name, never its message or a traceback.
  - Output goes to `OUT` under `/private/tmp`, with mode 0700 and a private-file write.
  - The only literals in the file are two ciphertext SHA-256 digests and case ids, which are not secrets.

PASS

## Elephant resolution

- Nit 1 (hard-coded output path): kept for now. The path is outside the repo and private; parameterising it is left for when the script is next needed.
- Nit 2 (stale line in RESCUE-INVENTORY.md): fixed in this commit.
- Nit 3: no change; the reviewer confirmed indirect coverage.
