# parallel-tests diff review, round 1 (goldfish, claude-opus-5-5)

Reviewed `a169a40..89934c9`: parallel `tests/run.py`, host-wide slot pool, and a pass cache. This review was read-only.

**Verdict: BLOCK**

1. **Blocker: a docs-only commit can return a false pass.** Four tests read data files under `docs/reports/`, but the cache key excluded all of `docs/`.
2. **Major: a pass with skipped tests was cached,** then reused after the skip condition went away (env vars, `openssl`/`age` installed, and so on).
3. **Major: a commit made mid-run could be cached under the old key.**
4. **Major: Ctrl-C kept running the rest of the suite** (`with ThreadPoolExecutor` waits for queued futures).
5. **Slot pool: no defects found.** flock is per open file, it is freed on exception or kill, and there is no deadlock. Nits: waiters poll rather than queue, and runners with different `TEST_SLOTS` values don't share one cap.
6. **Output and exit codes are correct.** Nit: a slow early script delays the output after it.
7. **Parallel hazards: none in the offline suites.** Timing tests may flake at full load; `-j 1` is the documented check.
8. **Nits:** use `--untracked-files=normal` explicitly. Gitignored paths are not in the key.

## Disposition
- ee17a83 fixed findings 1–4 and added negative controls.
- An independent Codex check (relayed by the founder from thread 796b18cd) then found a further cache hole that the skip regex misses: `tests/bench/test_refusal.py:165` exits 0 with "permission check deferred". On the founder's instruction the **cache was removed entirely**, including findings 1–3, `--no-cache` and `tests/tools/test_run_cache.py`.
- Finding 4's fix (`shutdown(cancel_futures=True)`) is kept.
- The slot pool is unchanged.
