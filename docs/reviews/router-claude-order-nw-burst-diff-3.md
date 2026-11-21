# Diff review 3: lane config reload, commit d5348ea1 (goldfish)

Reviewer: fresh general-purpose subagent (zoom_out, implementation_readiness; Mode: REVIEW), given the commit,
design section 3 and the coordinator's request.

## Verbatim review

**Scope.** Reviewed section 3 and "Rollout preconditions and steps" against `factory/model_router.py`: `lanes()` at 435, `Store.__init__` at 461, `_reload` at 496, `_routes`, `rpc` at 526, `lift_credit`, `reconcile`, `Server`/`Handler` and `main()` at 1270, plus the new test and its fixture. All work on a `git archive d5348ea1` copy.

**Tests (on the copy):** test_neuralwatt_routes 16 OK; test_model_router 53 OK; test_router_capacity 10 OK.

**What holds:**
- Thread safety. Every read of `capacities`, `disabled_routes` and `burst_capacities` is inside `rpc`, after `BEGIN IMMEDIATE` and after `_reload` (546–547), covering `_routes`, `free`, the `above_floor_at` loop and observe's burst branch. `lift_credit`, `reconcile` and `refresh_credit` never read these attributes. `lanes()` builds the values before one tuple assignment. A probe with 8 threads calling `capacity` while a writer cycled valid, burst and broken files 300 times saw only `{3, 6}` slots and no exceptions.
- Same validation function: startup and reload both call `lanes()` with the same defaults.
- Nothing escapes `rpc` from a bad file (OSError on stat; `except Exception` on parse/validation, covering a list, a string `disabled_routes`, a burst below the floor).
- File edge cases: partially written — logged once, picked up when the write finishes; deleted — logged once, running config kept, reloaded when it returns; same content — re-parsed, no effect.
- Logging: only the error's type name; mutation M7 (log content) fails the test.
- Startup without `config_path` unchanged.
- Leases held and burst state: lowering a floor or burst stops new seats only; `renew`/`finish` never consult capacities; burst state lives in `health` and survives a reload.
- Keys not reloaded are stated plainly (docstring 497–500 and the doc).
- Zoom-out: minimal — a stat per RPC under the existing lock, startup checks extracted into `lanes()`; no watcher thread, no new module.

**Mutations:** M1 remove `_reload()` call — caught; M2 move `_reload()` before `BEGIN IMMEDIATE` — survives; M3 never record `config_seen` — caught; M4 record only on success — caught; M5 drop `st_size` — survives; M6 narrow except to `(ValueError, OSError)` — caught; M7 log file content — caught; M8 don't reload `disabled_routes` — caught; M9 don't reload `capacities` — survives.

**BLOCKING 1: an edit that startup would reject is half-applied silently; the next restart then fails.** `_reload` (`model_router.py:506-509`) checks only the three lane keys; startup also rejects an `accounts` value outside `ACCOUNTS` (469), a bad `paid_ceiling_usd` (463–466) and a `database` key (`production_database`, 339). Probe: live config plus `burst_capacities: {neuralwatt-key: 6}` and one of those changes each time: NW capacity went 3 → 6 and nothing was logged, while building a Store from the same files raised `ValueError: unapproved account` / `invalid paid amount`. The request says "Validate it exactly as startup does. If the new config is invalid, keep the old one and log it." The next drained restart would end in "router startup failed" with live cases. Fix: one full-config check used by `main()`/`__init__` and `_reload`; refuse the whole file when it fails; add a subtest with a bad `accounts` plus the burst key.

**NIT 2:** changing the floor is not tested (M9 survives); add an assertion editing `capacities['neuralwatt-key']=4`.
**NIT 3:** the lock ordering is not tested (M2 survives); add a comment at 547 that it must stay after `BEGIN IMMEDIATE`.
**NIT 4:** `(st_mtime_ns, st_size)` misses a same-size, mtime-preserving copy (`cp -p`, `rsync -t`); add `st_ctime_ns` and `st_ino`.
**NIT 5:** the error log runs while holding the write lock; a `print` raising `BrokenPipeError` would 400 that RPC. Optionally wrap in `try/except OSError`.
**NIT 6:** a successful reload is not logged; log one line, or tell the operator to check `journalctl -u unbug-model-router`.
**NIT 7:** rollout step 2 says both "edit in place" and "temp file + mv"; say "replace atomically (temp file in the same directory + `mv`)", and name the path the router actually reads (the `--config` in drop-in `zzz-approved-ceiling.conf`, per `neuralwatt-routes.md:443`).

**Verdict: FAIL.** Blocking 1 breaks the explicit requirement to validate exactly as startup does. Everything else holds.

## Response (elephant)
- B1 fixed: `config_lanes(config)` holds every file check startup makes (object, no `database` key, approved `accounts`, parseable ceiling, lanes); `main()` now calls it at startup and `_reload` calls it, plus Store's database check (ceiling below retained spending). The whole file is refused and the running config kept on any failure. Test subtests: bad `accounts`, bad ceiling and a `database` key, each beside a valid burst key, are refused, and each also fails startup's own path; a ceiling below booked spending is refused and one covering it reloads. Mutations: reloading with `lanes()` only fails 3 subtests; dropping the spending check fails the test.
- NIT 2: floor edit 3 → 4 asserted (1 free seat with 3 held).
- NIT 3: comment added at the call.
- NIT 4: change key is now `(mtime_ns, ctime_ns, inode, size)`.
- NIT 5: print wrapped in `try/except OSError`.
- NIT 6: `router config reloaded` logged on success (also once on the first RPC after start); test asserts it.
- NIT 7: rollout step 2 rewritten with the atomic replace and the real path.
