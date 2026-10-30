Design review 6 **passes**: no blockers, no majors, three optional nits. Every earlier resolution still holds at `71a9f3d`. I wrote and ran nothing: no files, commits, tests, workloads, launches or decryption.

---

# Review: stream-d diagnosis-input design 6. PASS (no blockers, no majors, 3 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. Personas: `zoom_out`, `design_critic` and `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md` and `zoom-out-standard.md`. I read `docs/ENGINEERING.md` first.

**Scope:**
- `docs/designs/stream-d.md`, section "Queued diagnosis inputs (review-17 follow-up)", lines 1268–1524, at `71a9f3d`.
- The focus is the diff `a540e70..71a9f3d`, which changes only that section (+23/−6) and adds `stream-d-diagnosis-input-design-5.md`.
- I also checked the cumulative diff `ebf3b1a..71a9f3d`, to confirm the earlier resolutions are still in place.

**Read verbatim, with their elephant resolutions:**
- `stream-d-diagnosis-input-design-3.md`
- `stream-d-diagnosis-input-design-4.md`
- `stream-d-diagnosis-input-design-5.md`
- `stream-d-diff-22.md`

**Supporting inspection only:**
- `factory/run_artifacts.py`: `results_since`, `seal` (lines 59–62) and `wipe`.
- `factory/gate_state.py`: `inventory`, `save` and `load`.
- `factory/run.py`: the resume `c.t0` (line 2937), `factory_slots`, and the restored-results readers that fall back from `BENCH/results` to `work/bench-results`.
- `bin/bench.py`: the `RESULTS`, `IDS` and slot paths (lines 16–26), and the `calibration-summary.json` write (line 836).
- `factory/launch_manifest.py`: `WORKER_BENCH`, and the rule that `results/` is never exported.
- `factory/diagnosis.py` at `ebf3b1a`: `add`, `add_tree`, the names tuple and `_verify_input_records`.

Production `ebf3b1a` is unchanged. It still checks `card.sha256`, copies `gate-cache` whole, and raises `different input copies` on duplicate bench paths. That is a gap in the code, not in the design, and it is not reviewed here.

## Prior resolutions retained

- **Design-3 resolutions 1–6: hold.** Lines 1358–1364 and 1434–1451 are unchanged by this diff:
  - immutable manifest replay;
  - the terminal input-invalid and history-invalid lifecycle;
  - refusal of a missing manifest once something is bound to it;
  - producer-specific stop evidence;
  - source selection through the authenticated release chain;
  - isolation.
- **Founder generation correction (design 4): holds.** The generation comes only from the existing `sealed/<case>.restore-accounting.json` (lines 1276–1278 and 1293–1305). It follows the existing `launch.sh → restore_ledger.install → authenticate/_authenticated_source` chain, described at lines 1339–1356.
  - The card's `sha256` may be absent or name an older generation, and is never used as the generation (lines 1289–1292).
  - Replay validates the frozen receipt and card against the manifest generation, not the live receipt (lines 1358–1364).
  - No producer, field, launch mode or authority change is added.
- **Design-4 Ma1 and N1–N4: hold.** All three ledger branches still have tests (lines 1490–1497):
  - an authenticated founder correction, accepted through `retained_ledger_sha256`;
  - deleting or altering that field refuses;
  - a carried-forward ruling, accepted through `ledger_sha256`.

  The nits also hold: strict `type(version) is int` and `is True` checks, refusal of a missing embedded budget, the separate card bullet, and the rationale for the receipt.
- **Diff-22 Ma1 (stale caches): holds.** Lines 1366–1383 apply semantic filtering only at creation:
  - selected evidence is copied first;
  - a cache record is kept only if every reference is safe, has kind `work` or `bench`, carries a digest and resolves to copied evidence;
  - live bytes are never changed;
  - unsafe paths, symlinks and non-regular files still refuse, and only semantic invalidity is left out;
  - replay stays strict, with no omission or re-selection.

  The pass-then-fail-then-exhaust test is retained (lines 1500–1504). Diff-22 N1 (reconciling before the snapshot) stays a dispatcher obligation. N2 (descriptor-based read) stays a code obligation.

## Design-5 fixes: verified

- **Ma1 (restored vs current fixed-name bench copies): resolved.**
  - **Rule (lines 1309–1314):** at creation, a current `bench/results/<rel>` copy takes precedence over a restored `work/bench-results/<rel>` copy. Both sides are read safely. Neither live copy is changed. Restored-only paths are kept. Replay never re-selects a current copy.
  - **Why the overwrite is real:** `seal` calls `shutil.move` for each file in `results_since(c)` into `work/bench-results/<rel>`, overwriting the restored copy. Slot 0 is the primary bench and runs without `FACTORY_SLOT`, so `runs/baseline.json` is written at the top level. Slots ≥1 write `factory-slots/<n>/seed-ids.json`, and each fresh seed regenerates it. Same-name collisions are therefore expected after a resume.
  - **Fits the rest of the design.** "Copy current evidence first" (line 1367) gives an obvious implementation: freeze the current inventory first, then copy the restored `bench-results` tree, skipping names that are already present. The cache rule then automatically drops records whose bench digest names a superseded restored copy. This also matches `gate_state.load` and the `run.py` strategy readers, which check `bench/results` before `work/bench-results`, so the snapshot keeps the bytes the current gates read.
  - **Fails closed.** A symlinked or non-regular file on either side, including a superseded one, still refuses.
  - **Test plan (lines 1507–1513) covers:**
    - freezing the current bytes;
    - keeping restored-only files;
    - dropping caches that name superseded bytes;
    - leaving both live copies untouched;
    - unchanged replay after the live current bytes change again.

    The plan states honestly what the fixture is (saved bytes in an authored layout, not two live prepares), and it names the producer evidence (`RunArtifacts.seal`, `bin/bench.py`).
- **N1: resolved.** `gate-cache` is removed from the list of roots copied whole (line 1316). Note that `bench-results` sits in the inventory sentence, not in the named list, so the precedence rule now governs it.
- **N2: resolved.** Lines 1374–1376 say a retained cache is a historical pass receipt. The current outcome comes from the authenticated card and the current gate details.
- **N3: resolved.** Lines 1504–1507 add four cases:
  - absolute references and references containing `..`;
  - references that go through another cache file;
  - each of those is left out and never followed;
  - a symlinked cache file refuses before semantic filtering.
- **N4: resolved.** The cache rule is now its own paragraph (line 1366).

## Findings

### Blockers
None.

### Majors
None.

### Nits

- **N1. "Matching the existing seal's overwrite behaviour" (lines 1310–1311) is broader than what seal does.**
  - **What seal does:** it overwrites only with files in `RunArtifacts.results_since(c)`, meaning their mtime is at or after `c.t0`.
  - **What the design selects:** `gate_state.inventory` takes every non-dot file under `bench/results`, whatever its mtime.
  - **Where they differ:** a reused worker that was not wiped after a crash can hold leftover `bench/results/<rel>` files older than `c.t0`.
    - Seal would leave the restored copy in place.
    - The snapshot rule would freeze the leftover file instead.
  - **Impact:** nothing refuses, and the frozen bytes are still what the current gates read, because `gate_state.load` checks `bench/results` first. So this is about the wording being precise, not a correctness gap.
  - **Fix, either of:**
    - say "current" means the inventory's live `bench/results` copy, and drop the claim of exact seal equivalence;
    - limit precedence to `results_since(c)`, reusing the existing helper.
- **N2. The duplicate-copy test names no fixture.** "Saved execution receipts" (line 1508) doesn't say which saved file supplies the colliding bench bytes. The rest of the plan names its sources (the 5813be ledger and the verified practice bytes), but here the implementer has to choose. Name the fixture, for example a saved bench run JSON under `tests/factory/fixtures/`, so the real-artifacts rule can be checked in diff review.
- **N3. The "Queued input implementation boundary" section (lines 1526–1545) is now out of date.**
  - It says `queued_inputs` "creates or verifies the private input manifest described above". At `ebf3b1a` it does not implement the receipt-based generation, selective cache copying or current-copy precedence.
  - Add one sentence: the `ebf3b1a` slice predates these amendments, and it is unqualified until they are implemented and pass their own diff review.
  - This also fixes the overlong line at 1376.

## Review against the brief

- **Original task:** the section still covers immutable diagnosis inputs and replay, the original authenticated input generation, and safe selection.
  - Selection is done by code and fails closed on paths.
  - Semantic invalidity is left out only at creation.
  - Replay is strict.
- **No new authority or runtime enablement:** nothing activates a dispatcher, model, money admission or runtime path (lines 1431, 1451 and 1534–1537).
- **Heilmeier:** the section states the problem, the change, the rationale, the cost (lines 1517–1524) and the risks.
- **Readiness:** the section states the targets (`factory/diagnosis.py` and the held/input tests), the test plan, that nothing is deleted, and that no Murphy row closes.
- **Zoom-out:** the amendments reuse existing behaviour (seal precedence, `gate_state.load` semantics, the existing receipt producer). They add no new module, field or mechanism. Nothing speculative.

## Validation boundary

PASS applies to design readiness only. The `ebf3b1a` code still needs these changes, each with its own diff review:
- receipt-based generation;
- selective cache copying;
- current-copy precedence;
- the descriptor-based read.

Dispatcher wiring still has to call `queued_inputs` before any finding replay, reservation or model invocation, and has to prove reconciliation before the snapshot. No files were written. No tests, suite, workloads, cloud, launches or decryption were run. No Murphy row closes. No dispatcher, model, money or runtime enablement is claimed.

## Elephant resolution

*(to be completed by the elephant)*

## Elephant resolution

PASS accepted. All optional nits accepted: live inventory defines current-copy
precedence, without claiming exact mtime-filtered seal equivalence; name the
plain/reference checkpoint receipts in invalid-runs-real.json.gz; state that the
original ebf3b1a slice predates the amendments and needs a new implementation
review. The rebase maps reviewed 71a9f3d to 02e3154 without changing this design.
No finding is rejected. Implement and review the combined input correction;
no dispatcher or money enablement and no Murphy closure is claimed.

