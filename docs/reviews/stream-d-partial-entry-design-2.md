**Verdict: PASS.** This was round 2 of 2, and both round-1 blockers are fixed. Nothing goes to the parent. I made no edits, calls or merges.

I checked `docs/designs/stream-d-partial-entry.md` at 16eda9f against the actual code: `extension_package` (`Records`, `observe`, `entry`), `extension_compare.snapshot`, `_save`/`_load`, `extensions.validate_snapshot`, `gate_state.inputs`, `run.case_hash`, the freshness writers in `run`, `gate_pipeline.run`, the diagnosis handling of infrastructure stops, and `tests/factory/test_stream_d_entry.py`.

## B1 (freshness): fixed

- **Every record's other case files must match live:** this is sound. `Records.load` already refuses unless `case_sha256 == run.case_hash`, and `case_hash` leaves out `freshness.jsonl`. The design's tree check adds the requirement that each record's copied files cover its own case copy exactly.
- **Live freshness must match the last retained record and any retained G2, G8 or G9 record:** this matches how the code behaves.
  - The pre-gate freshness check in `build()` runs before `observe`.
  - Within the gates, only G2 rewrites the file (`ensure_freshness` → top-up and `finish_freshness_repair`).
  - So in a complete traversal, G2 and every later record carry the topped-up file, and complete entries are unchanged.
- **Stress uses its own historical evidence:** this holds. The stress version comes from the judge dependencies, not the case files, and its record carries its own copied files. A freshness top-up therefore does not break the stress record.
- **A stop during the G2 top-up is held:** this holds. G1's record still has the old file, so the live file no longer matches and entry refuses. A change after the stop is refused the same way.
- **Overlapping G10 cannot add a record after a failure:** while records are being captured, `observe` forces the gates to run one at a time (`overlap_reason`). So the rule that any record beyond a retained failure is a conflict cannot reject a legitimate run.

## B2 (exact test changes): fixed

- The three named test changes match the real tests:
  - `closed.unlink(); self.pending()` flips to "same snapshot";
  - the test where every gate crashes on infrastructure becomes "stress pass, frontier 1";
  - the old-traversal test only refused because of stale `card.gates` labels, so it now needs a reset.
- `'invalid-infra'` and `infrastructure_gate.exhausted` are the exact values `stop_infrastructure` writes. Only `'pass'` or `'fail'` at or after the missing record refuses.
- The stale-card hold and the lost-score case are both written down as accepted limitations.

## Other scope checks: all hold

- **Missing record becomes unreached:** at the missing record, `Records.evidence` returns None, so `snapshot` produces exactly one pending row with null hashes. Nothing else in `Records.load` can produce a pending row. Changing that row's status to unreached passes `validate_snapshot` without moving the frontier. `snapshot` itself stays unchanged.
- **G3 workers before pinning versions:** the G3 record is loaded first, so the worker count is set before versions are pinned. Without that, `snapshot` would see its configuration change and fail. No new setup or evaluation runs.
- **Diagnosis path for test 2:** diagnosis already accepts `infrastructure_exhausted` as a trigger, so test 2's close-to-passing path needs no attribution change.
- **Scope:** activation, limits, attribution, versions and schema are unchanged. No Murphy row is closed; the design only says it supports rows 9 and 13. The recorded-traversal slice stands alone, and the legacy no-record adapters and all-outcomes integration stay separate.
- **Land12:** c18edce is only on `merge/land12` and `t3/stream-d-gates`, not on `factory-simplify`. It still has to merge before implementation.

## Optional (not blocking)

1. **Lines 37–42:** when stress is the *only* retained record (missing record at G1), the general rule requires live freshness to equal stress's copy. Say this outright, so "stress need not match" clearly applies only when later records exist.
2. **Line 39:** G2's version inputs (`gate_state.inputs`) leave out `freshness.jsonl`, so G2 depends on freshness through what it reads, not through its version. Reword the rationale.
3. **Line 75:** pinning versions with `_versions(workspace(owner, r))` gives the same result as `snapshot`'s default. Keep it as documentation, or drop it.

## Writer disposition

PASS accepted. Both blockers independently verified fixed. Clarify that stress-only retention must match live freshness because stress is then the last record; the exception applies only when later records exist. G2/G8/G9 consume freshness at execution time; no claim that G2 includes it in scientific_version. Keep explicit version pinning for ordering clarity. Land12 is still pending, so implementation has not started.

