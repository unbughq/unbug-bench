# Stream D item 4 fresh-process publication suite

Code commit: `1867e6fad5479eee4afeb7fef6a8b4d3f6c24f09`.

Command: `uv run --with numpy --with scipy python -B tests/run.py`.
Log: `/tmp/stream-d-lane1-item4-full-20261031-implementation-4.log`.
Log SHA-256: `464ffb3d954dd11bb74cb33791e075729258c37e6cc66e361c2375fba46dea03`.

Finished with exit code 0: **156 test scripts run; 0 failed.**
All 33 retry tests passed, including fresh-context crash resumes and direct
production-context dispatch. The existing runtime tests passed. No timeout-only
failure or isolated rerun was needed. Existing conditional skips remain in the log.
The code stayed unchanged during this run. No real cases or provider calls ran.

During this run the parent requested a merge of factory-simplify at 4fecb01.
This record validates the publication fix before that merge; the final merged
suite will be recorded separately.
