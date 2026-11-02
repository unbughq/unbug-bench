**Verdict: PASS.** No blockers. I changed no files.

## What I checked
- **Commit and tree.** HEAD is `b7a76d4`. Implementation commit `fdfab00` has tree `599910529c71285ef3a8d5e5c98371739c0d96c9`, which matches the suite record. `fdfab00..HEAD` changes only `docs/designs/stream-d.md`, `docs/reports/stream-d-writer-g1-observation.md` and the suite json/log. It touches nothing in `factory/` or `tests/`.
- **Suite record.** The json says the command ran under `lockf -t 7000 /tmp/unbug-suite.lock …` and exited 0: 177 scripts, 0 failed. The log's tail ends with `177 test scripts run; 0 failed.`. The log's SHA-256 is `72871d6e…447a2`, which matches both the json and the report.
- **Production diff matches the design.**
  - `factory/run.py:1162` adds the keyword-only `writer_g1=None`. The two post-writer G1 call sites, `run.py:1531` (fresh writer) and `run.py:1552` (completed/done-writer recovery), now call `(writer_g1 or g1)(c)`. The ordinary callers at `run.py:575` and `run.py:3089` are unchanged, so they still use the default `g1`.
  - `factory/extension_package.py:436` passes `lambda c: records.writer_g1(c, lambda: r.g1(c))` inside the existing `public.capture`. `r.g1` is looked up when the callback runs, which is the binding the design specified. The capture context and the handling of `freshness_public_match`, `unchanged_repair` and the handoff labels are unchanged.
  - `Records.writer_g1` (`extension_package.py:234-247`) does what the design says. It reuses `load` for the digest, support, case and version checks. It refuses an existing record that isn't `ok is False`, and otherwise restores that record without calling G1 again. When there is no record, it takes the baseline, calls G1 once and lets any exception propagate. It saves only a `False` result that `_pending` accepts, and checks the case hash before saving. It adds no retry and no model call.
- **No leak into stress or the final gates.** `writer_g1` is reached only when there is no stress record. A G1 failure always exhausts the extension's single round, so it never reaches `run_gates` replay. Nothing else in `factory/`, `bin/` or `tools/` scans `extension-package/<id>`, so the new `G1/` directory has no side effects.
- **Design review dispositions.**
  - **M1 (stop labels):** tested at both layers. Calling `writer_g1` directly gives `extension_comparison_pending`; going through `package.run` gives `extension_execution_pending`.
  - **M2 (why not re-run G1 at the end):** the reason is now in the design's Problem section.
  - **Nits:** the callback binding, the exact source-setting diagnostic and the `precheck_problems` assumption are all in the design, and the tests assert that exact problem list.
- **Scope.** No Murphy register edits. No change to activation, limits, attribution, schema or version. The existing `extension_execution_pending` hold stays, and the report and the `stream-d.md` entry both say no terminal or progress result is claimed. The only test file in the diff is the new `tests/factory/test_stream_d_writer_g1.py`, so no existing assertion changed.

## Tests I ran (single files, no lock)
- `tests/factory/test_stream_d_writer_g1.py`: 10/10 OK. This covers:
  - the fresh, completed and done writer paths;
  - a kill just after the record is written and a kill just before;
  - a legacy receipt with no record, where nothing is inferred;
  - the pass handoff;
  - pending results and exceptions passed through unchanged;
  - tampered, missing and symlinked support files, a changed case, a version change, and a pass-shaped record, each refused without calling G1;
  - the version-change label through `package.run`.
- `test_stream_d_execution`, `test_stream_d_runtime`, `test_stream_d_unchanged` and `test_stream_d_public_match` all pass. That covers the public-match integration.

## Optional findings
1. **Nit, `extension_package.py:243-244`.** If G1 fails *and* the case hash changed during the call, `writer_g1` raises `extension_snapshot_changed` instead of returning the failure the way plain `g1` would. The design asks for this ("as Records.capture does"), and the contract inspection shouldn't modify the case, so I don't expect it in practice.
2. **Nit, `docs/reports/stream-d-writer-g1-observation.md:26`.** One very long reflowed line ("Elapsed 2160.8 seconds. Fresh diff review remains required. …"). Cosmetic.
3. **Nit, test (`test_record_and_support_refusals_never_invoke`).** After the tampered-case check it writes `'authored changed draft'` back into `draft.txt`. That relies on the authored writer having produced exactly that text. The test passes, but reading the original bytes back would be sturdier.

## Writer disposition

PASS accepted. No blockers remain. Optional test/code nits are deferred; the report line is reflowed. No production or test changes follow review. factory-simplify is merged and was already up to date on the final handback check.
