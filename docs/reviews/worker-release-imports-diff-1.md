# Goldfish review: worker release imports (diff 1)

- Branch: fix/worker-release-imports, commit 76ff2d2e on main 2cae8c87; fixes in c889d6b8.
- Mode: REVIEW (zoom_out, implementation_readiness). No design doc (change under ~45 lines); reviewed against the commit message.
- Reviewer: fresh goldfish (Opus), read-only. Second goldfish (Sonnet) settled the rejected blocking finding.
- Verdict: **FAIL, with one blocking finding. That finding was rejected and the second goldfish upheld the rejection, so it was dropped. The nits are fixed. Result: PASS, with no blocking finding open.**

## Findings and disposition

1. **BLOCKING:** the reviewer said the likely root cause is provable: before 32589de9 (9 November), bin/bench.py did `sys.path.insert(0, ROOT/"factory")`, and a Nov-4 checkout as the baked bench reproduces 1108c's error exactly. It asked for a test with the insert-at-0 `bench.py` and a corrected commit message.
   **Rejected; upheld by the second goldfish.**
   - 32589de9 is an ancestor of e9c6c76d, the commit the bench image `durable-bench-20261111c-e9c6c76d` was baked from.
   - `e9c6c76d:bin/bench.py` only appends, and its sha256 starts with 31e77359, the same as the file read on the worker.
   - `git grep` at e9c6c76d finds no other code that puts `<bench>/factory` ahead of the release in the step process: no .pth or sitecustomize files, and the only insert-at-0 sites are standalone CLIs.
   - The second goldfish rated an extra insert-at-0 test a NIT, worth it only if an older image is still in use. Skipped: none is.
2. **NIT:** the docstring and ARCHITECTURE wording "every factory module" was too strong, because baked `bench.py` imports `case_permissions` before the path is cleaned.
   **Fixed:** the docstring now says "imported from here on". With the real append-only baked bench, `case_permissions` resolves to the release anyway, because the release dir comes first.
3. **NIT:** `EAGER` and the private `FileFinder` fields serve the stale-cache theory, so they could be dropped.
   **Kept:** the coordinator asked for both. They are the only evidence a repeat would leave about why the release dir did not serve the module. The fields are read with `getattr`, so a missing attribute records `None`.
4. **NIT:** a package (such as `durable`) was reported as not listed, and `json.dumps` could raise if a `Path` object were ever on `sys.path`.
   **Fixed:** the record checks for `name.py` or `name`, and the dump uses `default=str`. A test covers the package case.
5. **NIT (process):** the Murphy row named in the commit is not in any register, and origin/main has no `docs/murphy-register.md`.
   **Addressed:** the row is below. It goes into the register where the register lives (the murphy-parallel work branch) at merge.
- **Test flaw (from "checked and clean"):** `record_crash` ran outside an `except`, so the recorded traceback was empty.
  **Fixed:** the tests raise and record inside the handler, as `gate_attempt.execute` does, and assert the traceback.

## Murphy row

| # | Stage and failure | Evidence | Today | Likelihood / impact | Fix | Router | Stream | Status | Closed by (test) |
|---:|---|---|---|---|---|---|---|---|---|
| new-worker-imports-1 | **A gate step runs a stale factory module from the baked bench.** | 1108c gates:1 attempts 1-6 (bx_xarh7u8j, bx_hwcymey3), 2026-11-17/18: `G2 crashed ImportError at run.py:1812`, `cannot import name 'superseded' from 'admission' (/home/user/unbug-bench/factory/admission.py)`; ordinary_freshness also baked | Baked bin/bench.py appends `<bench>/factory`; any release factory module the release dir did not serve fell through to baked code. Why the release dir did not serve it on those workers is unproven. | **High / case** | `worker_step.release_run` (Worker.runner, helper_link main) removes the baked dir after `import bench`, so the fallback is gone; G2's lazy modules load at step start; an ImportError crash record keeps sys.path, the release finder and the release listing. | No | E | closed | `tests/factory/test_worker_release_imports.py` (this release as the plumbing tree, a copy of its bin/ and factory/ at a separate path as the baked bench, the worker layout; real `run`/`bench` imports and real `record_crash`). The cause on the worker is open until a repeat's crash record shows it. |

## Checked and clean (reviewer)

- The same-checkout guard `baked != str(FACTORY)` is correct; both sides are resolved paths.
- No legitimate baked-only import is lost: the bin code imports only `case_permissions` from factory.
- Importing `bench` and the three G2 modules at step start has no side effects that change gate identity.
- No bypass: ADMIT, DIAGNOSIS and gate steps go through `Worker.runner()`, and every helper job goes through `main`.
- The crash record handles ImportError and ModuleNotFoundError, catches its own OS errors, and adds nothing beyond what the traceback already held.
