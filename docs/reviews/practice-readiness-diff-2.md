**Verdict: PASS.** Nothing blocking, nothing major. Scope: diff round 2 of 2, `ff30f03..f9d82c4`. Reviewed as Mode: REVIEW using `zoom_out` and `implementation_readiness`. There is no design doc for this change (small-fix exception), so I reviewed it against the commit message, the parent's scope, and `docs/designs/practice-run.md`.

**What I checked**

- **Size of the runtime change.**
  - `factory/key_holder.py` adds 4 lines and removes 1.
  - `factory/practice_cleanup.py` adds exactly 5 lines, which is nit 1's limit.
  - Both are well under the 20-line small-fix limit.
- **M1 fix: holder stays up and logs safely.**
  - It catches the activation error, prints only the fixed text `batch activation refused`, and returns.
  - No exception text, path or ID reaches the log.
  - Children that have already finished are not lost. Returning early is the same thing the old not-active path already did, so they get collected on the next scan.
  - The same exception-to-fixed-label pattern is already used for the scan, exit-record and child errors. Nothing was reimplemented.
- **M1 regression actually catches the bug.**
  - The real `batch_holder.active` runs, with the practice environment variable set and `ROOT` pointed at a manifest overwritten with `{}`.
  - The existing activation test (line 84) already shows that manifest raises `ValueError`. So without the fix, `batch_tick` raises and this test errors out.
  - It asserts the exact log text twice, that `children` and `waits` stay empty, and that nothing was spawned.
  - It then restores the manifest and confirms the scan runs on the next tick.
- **Nit 1: "waiting" versus "uncertain".**
  - `bin/boat-launch-guards.sh` writes `monitor.sh` in `guard_init`. In `guard_new`, it writes and fsyncs the `new.N.pending` marker before any `boat new` request.
  - So if there is no `monitor.sh`, no `new.*` file, and `ids` is empty or missing, no creation request can have been sent. Returning "waiting" is correct.
  - That path writes no new markers or IDs, and "waiting" never ends the cleanup loop. Only "complete" or "not_dispatched" do.
  - Once a `new.1.pending` file exists, the result is still "uncertain".
  - The test would fail without the 5 lines: `monitor()` would raise and the first assertion would see "uncertain" instead of "waiting".
- **Step 6 docs (nits 3 and 4).**
  - The step now says to run `export UNBUG_PRACTICE_BATCH=b-plumbing-practice` first.
  - It now says the provider's 60-minute auto-delete is the only backstop, and the state stays uncertain, if the controller dies before writing `.started`.
- **Founder decisions.**
  - They are quoted word for word in step 1 of `practice-run.md` and in `reports/practice-readiness.md`.
  - The old provider-bound and legacy-debt prerequisites are gone, and so is the "likely $0 abort" claim.
  - The abort list now covers credit above $5, auto top-up on, or either check unverified.
  - The legacy launch is recorded as disposed, with files kept and no fake completion markers. Later charges go on the infra-waste line.
  - The two docs agree with each other.
- **Suite provenance.** All of it checks out:
  - The uncompressed and compressed log hashes match the JSON for both runs.
  - Tree `148fc55` belongs to commit `e4715b7`, and tree `178e80f` belongs to `fd92c3d`.
  - `e4715b7..fd92c3d` changes only `docs/designs/practice-run.md` and `docs/reports/practice-readiness.md`.
  - `fd92c3d..f9d82c4` adds only the suite JSON and log and updates the report.
  - The log ends with `172 test scripts run; 0 failed.`
  - The `033050Z` record is marked `qualifying: false` with exit 143. It is labelled as not validation and is not used as such.
- **Local check.** I ran `tests/factory/test_practice_readiness.py` myself: 14 tests, OK. The worktree was clean afterwards. I did not re-run the full suite.

**Nits (optional)**

1. The `fd92c3d` commit message doesn't mention the founder decisions that were amended into the same commit. The report and the JSON explain it, but the commit message alone doesn't.
2. `factory/practice_preflight.py:20` still calls the first live-only item `provider_cost_and_legacy_debt`. The report calls these "historical preflight group labels" and the limit is $0, so nothing behaves differently. A reader may still trip on the old name.
3. If `monitor.sh` is missing but `ids` is non-empty, the result falls through to "uncertain". That is correct and safe, but no test covers it.

Nits 2, 5, 6 and 7 from round 1 are still open, as you intended; I didn't re-raise them. I closed no Murphy rows and made no edits, network calls or delegations.

## Writer disposition

Accepted PASS. M1 and round-1 nits 1, 3 and 4 are fixed and independently
verified. The founder decisions are recorded in the same M1 source commit.
Round-1 nits 2, 5, 6 and 7 and the three optional round-2 nits remain open;
none is rejected or claimed fixed. No Murphy rows closed. No live actions,
workers, paid calls, pushes or activation. Stop after this review as instructed.

