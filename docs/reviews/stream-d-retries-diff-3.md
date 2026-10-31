# Stream D retries diff review 3 (fresh Claude goldfish, parent-commissioned)

Scope: 2499b5d..83828bf, focused on 1867e6f (fix for diff-2 blocker 1).

**PASS**

- Q1: Blocker 1 is fixed for every production entry point. `Ctx.__init__` installs the barrier (run.py:125). `run.main` is the only production Ctx constructor. `write_and_attack` installs it before its resume dispatch (run.py:1116). Every other dispatch route already installs or bypasses it by design. Fail-closed on a missing recipient is preserved (run.py:197).
- Q2: The rebuilt-context tests prove fresh-context resume. With the run.py part of 1867e6f reverted, 3 of 33 tests fail with `stress_publication_configuration_missing`. Reverting only run.py:1116 fails 2. At HEAD 33/33 pass.
- Q3: No new blocker. Removing the factory_job guard is inert for non-factory jobs (model_runtime.py:58-60). Shallow copies share the work directory and active_model_calls.

Blockers: none. Majors: none.

Nits (optional):
1. The callback is installed in five places. run.py:1116 only repeats Ctx.__init__ in production. Building test contexts with `run.Ctx()` would let it be deleted.
2. No test runs `run.main` in a real subprocess, so row 11 is not end-to-end crash proof.
3. run.py:2242 prose still says `http_5xx`. It should say "http_500–http_599".

Full suite not re-run by the reviewer; relied on stream-d-retries-suite-5.md (158 scripts, 0 failed).
