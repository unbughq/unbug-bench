**FAIL: 1 blocking finding is open.**

I reviewed `b500db9..2499b5d` against `docs/designs/stream-d.md` from "Fourth increment" to the end of the file. I used Mode: REVIEW, the `zoom_out` and `implementation_readiness` personas, and the implementation-readiness standard. I did not edit anything. I ran one focused probe, built from the existing `RetryTests` fixture. It lives at `/tmp/goldfish_probe.py`, outside the repo. Nothing in the repo was written.

### Blockers

**1. After a crash, a fresh process cannot get past a pending stress publication. Resume stops with an unrecognised label instead of retrying the checkpoint.**
- **Where:**
  - The barrier is checked at `factory/model_runtime.py:73-76`. If `c.model_publication_barrier` is missing, it raises `stress_publication_configuration_missing`.
  - That callback is installed only inside `opencode` (`factory/run.py:213`), `stress_categories` (`:208`) and `pending_call` (`:400`).
  - `write_and_attack` dispatches `'resume'` at `factory/run.py:1116`, before any of those run. The resume path reaches it at `factory/run.py:553` without calling the model first.
- **How it happens:**
  - A category completes. The marker is written with `pending: true` (`factory/stress_progress.py:139`).
  - The process is killed before `publication()` clears the marker (`stress_progress.py:41`). That covers the whole window from `:139` to the end of upload, and the c40234f fix makes this window present for every category.
  - The control VM resumes in a new process, so the context has no barrier attribute. The first dispatch raises `BudgetError('stress_publication_configuration_missing')`.
  - That label is not in `diagnosis._trigger` (`factory/diagnosis.py:46-47`), so a person has to step in.
- **What the design says:**
  - "On crash after upload but before clearing, another checkpoint is safe."
  - "Failure retries publication in place under batch authority before paid work."
  - "Missing production callback with a pending marker fails configuration closed." That is meant for a production setup with no callback, not for a normal resume.
- **Evidence:** I copied `test_publication_marker_precedes_category_state_commit` and deleted `c.model_publication_barrier` before resuming, to simulate a new process. Output: `marker {'pending': True} … RESUME RAISED BudgetError stress_publication_configuration_missing`.
  - The committed tests (`tests/factory/test_stream_d_retries.py:377-391` and `:497-515`) resume on the same `self.c` object. The callback installed before the simulated kill is still there, which hides the failure.
  - Row 11 cites `test_publication_kill_keeps_completed_category_on_resume`, so that claim is not yet proven.
- **Fix:** install the runner callback where the case context is built, or at least before the `'resume'` dispatch in `write_and_attack`. That covers every dispatch path, including direct `ModelRuntime.call` users. Then make the publication-kill tests resume with a fresh context that has none of the in-memory attributes.

### Prior blockers (verified closed)
- **Prior blocker 1:** `ordinary_freshness.obtain` (`:22-72`) keeps a per-URL cache.
  - Live successes are reused until the 24-hour expiry in `load`.
  - A held URL refreshes once per cycle (`refresh.discard`), and the confirmation step copies the same bytes.
  - `test_mixed_held_and_changing_live_page_reuses_real_orchestration_judgment` runs the real `g2` → `ensure` → `confirm_hits` path through the router and ledger. It shows 3 cycles, 1 live fetch and 1 reviewer call.
  - Recovery after a 403 with no archive copy (`:470`) and a broad HTTP outage with no top-up (`:478`) are also covered.
- **Prior blocker 2:** `stress_progress.run` checks `attack_diagnostic_unfinished` in three places: before each call (`:93`), at aggregate completion (`finish`, `:63-66`) and on saved-report resume (`run.py:1353`).
  - In category mode, the normal path raises `stress_validation_exhausted` (`run.py:1526`).
  - `test_last_category_interrupted_diagnostic_is_recognized_exhaustion` covers both entry paths.

### Nonblocking findings
1. **Resume tests reuse the same context object.** Every kill/resume test in `test_stream_d_retries.py` resumes on the same `self.c`. In-memory state survives the simulated kill: the barrier, `freshness_refetch_urls` and `router_excluded`. That is how blocker 1 slipped through. Real-artifact tests that claim crash safety should rebuild the context.
2. **One allowed value in the confirmation prompt is not a real status.** The batch prompt lists the literal `"http_5xx"` as an allowed `live_failure` value (`run.py:2242-2243`). `agrees()` requires the exact receipt status, such as `http_503`. The appended line "copy … actual three-digit HTTP status" helps, but the list itself still offers a value that can never match. Listing the pattern instead would remove the trap.
3. **Each hold cycle repeats the 120-second window for every unflagged access-failed URL.** `ensure` puts every URL into `freshness_refetch_urls` (`ordinary_freshness.py:136`), so each such URL gets a fresh window per cycle. The design accepts this ("per G2 invocation"), but serial windows multiply across hold cycles. It may be worth limiting refetch to flagged URLs while the case is held.
4. **Row 11 cites `factory/restart.py:57/:83`, but the boundary test never runs `restart.py`.** `test_batch_boundaries_bypass_legacy_restart_and_holder_attempt_caps` runs `launch.sh::factory_auto_resume` and `key_holder.admit_attempt`. The claim is acceptable if the launch exit is the only way into `restart.py`. Otherwise narrow the row text.
5. **A kill can leave a category state file that names an operation `attack-state.json` never records.** `stress_progress.run` sets `category_mode`/`phase` on the in-memory receipt (`:60`). Those are only saved when `pending_call` writes `attack-state.json`. A kill between `state.save()` (`:84`) and the first category dispatch leaves a state file with an `operation_id` but a legacy-shaped `attack-state.json`. Resume then falls back to the legacy rule ("start new coverage"). That is safe, but it creates a dead state directory.

### Verified as matching the design
- **Scientific decisions are preserved:**
  - repair requires the projection to match exactly (`ordinary_retry.py:146-149`);
  - output with no usable decision spends its route and moves to the next one with the full original request;
  - exhaustion is checked before admission (`:169`);
  - an interrupted call stays pending, because `on_complete` runs only when the process exits with code 0 (`model_runtime.py:419`).
- **Freshness verdicts:**
  - a page that failed with an access error and has an archive copy can confirm a match but cannot clear one (`run.py:2331-2335`);
  - an access failure with no archive copy holds until the page comes back or the batch deadline;
  - the deadline ends with `retired_batch_bound` through `job_authority.for_case`.
- **Outage handling:** an HTTP access failure with no archive copy now counts toward `all_transport_failed`. A top-up whose rows did not change does not repeat (`ordinary_freshness.py:145-149`).
- **Publication order:** the marker is written before the category state, and the publication I/O is refused while any model call is active.
- **Murphy rows:**
  - row 13 stays open;
  - row 15 is limited to answers with a usable decision and approved equivalent chains;
  - rows 11 and 12 name specific behaviour tests (row 11 still depends on blocker 1).
- **Suite:** the record `docs/reviews/stream-d-retries-suite-3.md` is present. I did not re-run the suite.

## Author response

Blocker 1 is accepted and fixed. Production Ctx construction installs the runner publication callback before any dispatch. write_and_attack also installs it before its resume dispatch for reconstructed or standalone contexts. The callback still refuses a genuinely missing production checkpoint configuration. A pending marker now reaches publication retry on a new process instead of the unrecognized configuration label.

All interrupted-call resume tests in test_stream_d_retries.py now reconstruct the context from launch inputs and the saved card, with a new cancellation event and publication transport configuration. They retain none of the old callbacks, locks, model resume state, exclusions or freshness scratch state. The two publication crash tests thus exercise fresh-context resume. A separate test constructs a production Ctx and enters dispatch directly with a pending marker, proving the barrier exists before a model wrapper can install it.

Nonblocking finding 1 is addressed by those fresh contexts. Finding 2 is fixed: the allowed statuses describe http_500 through http_599 rather than offering the impossible literal http_5xx. Finding 3 remains the documented per-invocation retrieval window; no throughput claim is added. Finding 4 is clarified in the register: the proof covers the batch launch boundary and batch holder, not legacy coordinator or standalone restart entry points. Finding 5 is safe abandoned coverage before the first paid category admission; no partial directory authorizes reuse, and no behavior change is needed for that storage-only nit.

No blocking finding is rejected. The small callback initialization fix is verified directly without another delegate, following the review workflow's instruction to fix small findings locally. Full-suite results are recorded separately.

