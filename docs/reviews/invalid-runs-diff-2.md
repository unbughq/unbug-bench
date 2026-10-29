I'm returning FAIL. One blocker and one major are open. All five findings from the first diff review (B1, M1–M4) are fixed. The full text is below for the elephant to save verbatim.

---

# Invalid-runs diff review 2: FAIL (1 Blocker, 1 Major, 3 Nit)

**Range:** `8c5de61..b36d084` on `invalid-runs`. The merge-base equals the current `factory-simplify` tip, so the branch is rebased. `396689c..HEAD` touches only `docs/reviews/invalid-runs-validation.md`.

**Mode:** REVIEW, using the Zoom-Out and Implementation-Readiness standards. Heilmeier was design context only.

**How I reviewed:** read-only. I read the design and its normative resolutions, all earlier review records, the validation, artifact and provenance records, the full code diff and the regression-test assertions. I ran no tests or workloads.

**Independent checks I made:**
- **Pins:** the pinned `current_files` digests in `factory/invalid-runs-compat.json` match HEAD. The `base_files` digests match `6f17c5f`, which is an ancestor of the base. The runner AST digests (`calibrate`, `checkpoint`, `time`, `tree_digest`, `verdicts`) match `gate_state.source_inputs` at HEAD.
- **Fixtures:** all 37 embedded files in `invalid-runs-real.json.gz` match the named public `results/` sources byte for byte and by SHA256.
- **Orphan test:** the deleted `test_restore_failover_bundle.py` loaded an untracked `finalize-restore.py`, so deleting it is correct.

## Blocker

**B1. G2 still counts made-up or dead search results toward the freshness minima (row 24 is marked closed).**
- **Where:**
  - `factory/freshness_retrieval.py:51-76`, where `fetch` returns rather than raises for 404, 410 and DNS-not-found, and an empty Wayback lookup sets `retrieved_from='none'`;
  - `factory/run.py:1655-1663`, where only an `InvalidInfra` adds a row to `freshness_unfetched`.
- **What happens:** an unflagged row whose URL returns 404/410 or does not resolve, and has no archive snapshot, gets a runner receipt saying "nothing exists here". The row is not excluded, so `freshness_counts` still counts it toward 3 web, 3 GitHub and 2 attacker searches. A searcher that invents an issue URL (common for model-written search logs) with `retrieved: true, hit: false` therefore helps clear G2.
- **Consequence:** this is the silent wrong result row 24 describes: freshness clears on searches that cannot have happened. A case whose bug is public can then be admitted with too few real searches. It also contradicts the design ("retrieves every structurally valid logged result URL before counting it"; "fetch failure supplies no evidence"; "No model retrieval assertion can restore an excluded count").
- **Why the tests miss it:** they patch `fetch` only to return 200 or to raise. Neither path covers 404 plus an empty Wayback lookup.
- **Minimal fix:**
  - In the unflagged branch of `g2`, also add `row['url']` to `c.freshness_unfetched` when any returned receipt has `retrieved_from == 'none'`. The existing topup message then asks for an alternative.
  - Add a test that replays a 404 and an empty `archived_snapshots` through the transport seam and asserts the row is not counted.

## Major

**M1. A rule that was never in the design turns a case-writing defect into an infrastructure stop.**
- **Where:** `factory/run.py:1290-1292`, the new `verdicts()` check that raises `InvalidInfra('checkpoint omitted a promised observation')`.
- **What happens:** if the judge does not emit a key named in `case.json`'s `promise_paths`/`promise_checks`, every run is classified invalid-infra. That happens when the writer misnames a check or path, or a scenario lacks `judge.py`. No check before this one validates those names; G1 only checks that they are non-empty, plus the unannounced-window path equality.
- **Consequence:**
  - G4, G5, G6/G7 and G10 retry identical inputs, exhaust, and stop as `infrastructure_exhausted` for D's diagnosis. Before this change the writer got G4/G5 feedback and could fix it.
  - That is the reverse of row 38's fix: a writer-fixable structural defect becomes an unscored operational stop, which is a pit stop.
  - The check does close a real silent pass: a missing promised path used to read as "not violated". Detecting it is right; only the classification is wrong.
  - The design, the normative resolutions and the tests never mention this rule, so it was not reviewed. That is an Implementation-Readiness gap.
- **Minimal fix (pick one):**
  - Report a missing promised observation as a structural case problem. A G1 contract problem, or a scientific G4/G5 failure carrying the problem text, both route to the existing writer repair.
  - Or document it as a deliberate invalid-infra classification and add a test with real artifacts. I recommend the first option.

## Nits

- **N1. A workflow failure now hides a valid cheat-pass.** At `bin/verify-negative:256`, the workflow-status check moved ahead of the cheat-pass check. A probe batch with one workflow-status failure and one validly passing record now reports `invalid-probe`, and G6 stops for operational reasons instead of failing on science. This is conservative, not a wrong verdict.
  - Fix: evaluate the validity-checked cheat-pass first.
- **N2. The replacement key can drift after a one-time migration.**
  - `factory/fairness.py:55` keys a missing-fix replacement on the SHA256 of the original results row.
  - `completed_attempts` rewrites kept rows with the migrated `identity` (`calibration.py`, `kept.append({**row, 'identity': identity})`).
  - So if G10 re-runs after a pinned migration, the next G16/G17 key changes and could buy one more replacement. This happens once per legacy series.
  - Fix: key on try, workspace and artifacts rather than the whole row.
- **N3. The exhausted-gate record can be overwritten.**
  - `gate_pipeline.py:146` and the `finally` join at about `:199-201` can both call `stop_infrastructure`.
  - A foreground gate's exhaustion followed by a crashed overlapping G10 overwrites `infrastructure_gate` with G10 and leaves two `invalid-infra` gate entries.
  - Fix: keep the first recorded gate.
- **Minor, no action required:** flagged rows are fetched twice, once in `g2` and again in `confirm_hits`, and the retained bodies (up to 8 MiB each) accumulate in sealed work.

## Are the diff-review-1 findings resolved?

- **B1, review evidence: resolved.**
  - Every review row's actual workspace is bound as `try-N`, including an early-probe workspace outside the folder and replacement workspaces.
  - Transcripts for the folder, `early_probe` and replacement series are copied. Owner Q&A lives in `<workspace>/owner/questions.jsonl`, so the workspace binding includes it.
  - Inputs are digest-checked before and after the call, and `validate` refuses a missing guard or `execution.json`.
  - The regression test moves the attempt to `early_probe/try-1` and asserts the digest and transcript bytes inside the review directory.
- **M1, replacement purchases: resolved.**
  - Only a try with no submission gets a one-try replacement series, keyed per original row.
  - A replacement with a submission is reviewed in the same invocation.
  - A completed no-fix replacement is kept and never bought again. The test asserts `obtain.assert_called_once()` across two invocations.
  - The valid later try and the original no-fix row stay unchanged in `results.json`, as the test asserts.
  - Seeds reproduce the original `seed + try`. (See N2 for the post-migration edge.)
- **M2, blocked unflagged URLs: resolved for access errors**, which are now uncounted, keep their history, and go through the existing bounded topup. It is **not resolved for dead or non-resolving URLs**; see B1 above.
- **M3, row 36 wording: resolved.** The register text now says an unscored stop for D's diagnosis, separate from structural reselection, and the test asserts no writer call and no change to candidate or round counts.
- **M4, retry allowance after success: resolved.** Success sets `invalid_attempts=0`, and the fail/pass, fail/pass test covers it.
- **N1–N3: resolved.**
- **Provider-wait reviewer receipts (self-audit): correct.** A `running` record is retried with the same family after its stale output is removed, and only a completed inconclusive review uses up a family.

## Checked and found sound

- **Shared validity check:** `run_validity.classify/require_valid` is the only predicate. It is used by `read_completed` (now on by default), `verdicts`, G14, strategy and silent windows, calibration receipts, G11 rerun batches and `verify-negative`.
- **Retry journal:** nested exhaustion is not retried again. Budget, pause and provider exits clear the running marker without using allowance. A process killed while running uses one attempt. The key includes `runtime_revision`, so plumbing updates get a fresh allowance.
- **Row 22:** all-invalid G6/G7 cheats raise instead of counting as rejections.
- **Row 23:** G10 commits only after valid execution and saves `execution.json`. `pending-<try>.json` avoids paying for the solver again.
- **Row 25:** collection requires the exact name and digest for each card and for every unwiped work case. The probe and startup exceptions cannot cover work.
- **Row 40:** G11 requires a single, guard-bound, valid report, and scanner suspicions need independent adjudication against runtime evidence.
- **Row 41:** unchanged evidence goes to the next independent family.
- **Recovery:** every recovery entry point refuses infrastructure-exhausted cards.
- **Corpus projection:** the public-card projection changes only `case-20261017T125556Z-18681d`, and no card is rewritten.
- **Row 14:** correctly left open.
- **Cross-stream edits:** they are named in the design. A's lease/provider-wait shapes and E's `sh()`/lifecycle are untouched.

## Not judged

- Live S11 120-second qualification, because launches are prohibited.
- Whether the suite passes; I relied on the saved validation record.
- The 64 practice files and 58 VM cards against their remote sources. I did verify the 37 `results/` files above.
- Model quality of the adjudication prompts.

**Not PASS:** B1 is open. M1 should be fixed or explicitly documented in the same round.


## Elephant response

All findings accepted; none rejected. B1 excludes runner no-page/no-archive
receipts, with a real-practice-log transport replay asserting zero search counts.
M1 uses a structural CaseProblem only after execution validity, caught at the gate
and prototype boundaries for ordinary writer repair. It names the missing path or
check; real invalid batches still raise before any structural feedback. N1 restores
validity-checked cheat-pass priority, N2 binds replacements to stable try/workspace/
artifact identity and tests a policy identity migration, N3 keeps the first gate
stop under dual foreground/G10 exhaustion. The branch was rebased onto stream E's
merged first increment. Its deadline code was retained; the frozen live runtime now
ships E's required processes.py. Compatibility pins were refreshed and removed AST
dependencies are deleted during migration. A fresh full suite and diff review
follow; this response does not itself declare PASS.


The first E+C full run exposed E's old timeout-test fixture: no case path for C's
journal identity, plus an expected runner_error/scientific failed_detail shape.
The fixture now supplies a case directory and explicitly asserts the new unscored
stop, no failure fields and no writer callback. This changes test integration only,
not E's deadline implementation. A complete full-suite rerun follows.
