# Review: stream-d diagnosis-input design 1 (queued diagnosis inputs, review-17 follow-up): FAIL

**Reviewer:** a fresh goldfish, read-only, `Mode: REVIEW`, using the zoom_out, design_critic and implementation_readiness personas. I checked the section against ENGINEERING.md, heilmeier-standard.md and implementation-readiness-standard.md.

**Scope:**
- The section `docs/designs/stream-d.md:1213-1269`, at worktree `t3-21bef30c`, branch `t3/stream-d-implementation`, HEAD `03574e7`.
- I checked it against the diff `fab9014..03574e7`, the diagnosis and held design (`stream-d.md:317-475`, `1088-1211`), and interfaces §8 (`interfaces.md:410-430`, `539-560`, `725-790`).
- Review-17's Ma1 and Ma2 are the motivation for this section, and the elephant accepted both.
- `factory/diagnosis.py`, `launch_manifest.py`, `worker_release.py`, `gate_state.py` and `job_config.py` at this HEAD were used as supporting evidence only.
- `.stream-d-next/` was excluded.
- I ran no suite, and I claim no suite result. No Murphy row closes.

## What holds
- **Ma2 is answered.** Both result validation and finding replay now use one frozen root, and the live `work`/ledger is explicitly banned as the evidence root (lines 1215 and 1251-1256). The required test (freeze, finding, interrupt, ledger append, replay with no model) covers exactly the probe that review-17 reproduced.
- **Ma1 is answered.** `factory_bug_history_invalid` makes `exhaustion` false and the projection None, it covers both the infrastructure-marker case and the damaged-completed-hold case, and it mints no new ID (1258-1261). This matches what the elephant accepted.
- **No checkpoint names itself.** `generation` is the restored, B-verified `source_generation`. The snapshot never names the generation that contains it, and a later wait/checkpoint does not rebind it (1221-1222, 1248-1249). This matches interfaces §8:548-549. Interfaces 416-422 confirm that diagnosis always runs on a restored resume, so a non-null `source_generation` is the right precondition for the normal path.
- **No new authority.** Nothing is added to public state or to the nine-field RAM config. No money or dispatch is enabled, and code (not the model) chooses the inputs. The shared held-dispatch guard stays the only model gate, and B's addendum must edit that guard rather than go around it (1261-1263; this is review-17's N4).
- **The write order is sound in outline:** stage, hash, fsync, publish, and only then `input.json`. After that, the snapshot is never rewritten.
- **Exclusions are stated.** Credentials, environment, restore keys, job config, logs and other case roots are named as never copied, and symlinks and non-regular files are refused.

## Blockers

**B1. Refusals in the input protocol have no defined lifecycle.**
- **Where:** lines 1244-1246 and 1255. The same gap applies to the non-null rule at 1221.
- **What's missing:** the section says "otherwise it refuses" and "changed immutable evidence still refuses", but never says what the card becomes.
  - It names no `terminal_stop`.
  - It doesn't say whether `diagnosis_state` stays pending.
  - It doesn't say what `exhaustion()` and `pending_projection()` return.
  - It doesn't say what `unbug status` shows.
- **Why it matters:** if the refusal is just an exception and the pending state is left in place, the projection stays present. B keeps queueing same-owner diagnosis resumes that each refuse. That is the review-17 Ma1 loop again, and it sits on the path that Ma2's fix just created.
- **The section also leaves open the case where `source_generation` is null or doesn't match on initial creation.** Interfaces 416-422 make that state "should not happen", but the dispatcher still needs a defined outcome for it.
- **This fails the zero-decision rule:** the implementer would have to invent the stop label and the projection behaviour.
- **Fix:** name one terminal attention stop, for example `diagnosis_input_invalid`, that handles it exactly like `factory_bug_history_invalid`: `exhaustion` false, projection None, no new ID, held guard unchanged. It would cover:
  - a changed or missing frozen file;
  - a manifest that doesn't match its inventory;
  - a manifest whose case or exhaustion ID doesn't match;
  - a missing or mismatched input generation on initial creation.

  Add the two projection assertions to the test list. Leave the stop off the status known list, so it shows `check case`.

## Majors

**Ma1. The crash window before `input.json` should re-stage, not refuse.**
- **Where:** 1244-1246.
- **Why the reuse path is unnecessary:** no model call happens before `input.json` exists (1216), so nothing is bound to an orphaned `inputs/`. Reusing it "only while they still match the authenticated source" adds a comparison against something the section never defines (live work? the restored archive?).
- **The failure:** a crash, followed by any legitimate change on restart (settlement rewriting the ledger, for example), hits "refuses". That leaves the case stuck, which is Ma2's failure again in a smaller window.
- **Fix:** if `inputs/` or the staging directory exists but `input.json` doesn't, delete both and re-stage from current state. Refuse (B1) only when `input.json` exists and doesn't verify. Also say where the staging directory lives: under `work/diagnosis/<exhaustion_id>/`, so the rename stays on one filesystem and is atomic.

**Ma2. The `work/` allowlist drops gate evidence and has no required set.**
- **Where:** 1230-1234.
- **The gap:** the allowlist leaves out `work/bench-results` (restored gate results; `run.py:1702,1738,1757`, `gate_state.py:229`) and `work/judge_breadth`. `gate_state.inventory` treats both as gate evidence (`gate_state.py:173-183`), and `gate-cache` records cite those paths, so a snapshot that copies `gate-cache` without them carries references it can't resolve.
- **Why it matters:** the passed design (319-323) promises gate and calibration receipts, stop history and writer handoff. A G-stage factory bug would be diagnosed without the results that failed.
- **Also missing from the list, with no stated reason:** `fixes`, `evidence`, `history` and `verdict.json` (the G11 audit, `g11_review.py:124-142`), plus `prototype.json`, `public-search.json`, `idea-realism.json`, `audit-baseline.json` and `delivery-provenance.json`. `statements` is excluded too. That may be deliberate, since statements are encrypted separately, but the section doesn't say so.
- **No required set:** "Missing optional evidence stays missing" makes every entry optional, so a snapshot with an empty `work/` is valid. The implementer can't tell which files must be present.
- **Fix:**
  - Reuse `gate_state.inventory`'s work-root set, adding `bench-results`, instead of keeping a separate hand list.
  - State why each remaining exclusion is excluded.
  - Name a minimum required set and a stop for when it's missing. For example, `card.json` and `ledger.json` are required, and the trigger stage's gate-details are required when `gate_or_stage` is a gate.

**Ma3. "Matching release source" isn't defined, and three listed files aren't shipped.**
- **Where:** 1235-1237.
- **What's missing:** the section doesn't say what proves the source matches the release.
- **The shipped set:** the worker release already defines its source set and digests. `launch_manifest.worker_files` (`WORKER_BENCH` + `WORKER_CONFIG` + `WORKER_GLOBS`) is stamped by `worker_release.source_files` and bound through `batch_release_sha256`.
- **The mismatch:** `bin/run-exam`, `bin/score-claims` and `bin/land` are in neither `WORKER_BENCH` nor `WORKER_GLOBS` (`launch_manifest.py:65-90`). They won't exist on a worker, so the implementer would have to choose between failing and treating them as optional.
- **Fix:** define `source/` as exactly the verified release manifest's `files` entries under `factory/*.py`, `factory/prompts/*.md` and the `WORKER_BENCH` bin entries, each copied only if its digest equals the release manifest's. Drop the three files that aren't shipped, or add them to `WORKER_BENCH` through B's release design. Reuse `worker_files` and `source_files`; don't add a new list.

## Nits
- **n1. Say plainly what the binding proves (1251).** `checkpoint_sha256` equals the restored `source_generation`, but the snapshot holds post-restore, post-settlement bytes (the settled ledger, the current card). It is not that archive's content. What ties the snapshot to the finding is that both live in the same `diagnosis/<exhaustion_id>/` directory inside the authenticated archive. Say so rather than calling it a cryptographic binding.
- **n2. Name the exact source paths (1228-1229).** For `ledger.json`: `c.ledger` (`SEALED/<case>.continuation-budget.json`) or `work/continuation-budget.json`. For `card.json`: the restored card, or the card after settlement and `record_exhaustion`?
- **n3. Say whether a damaged history overwrites `terminal_stop: factory_bug_held` on an already-held card (1260).** Review-17 offered "don't overwrite" as one option. If it is overwritten, status loses `factory bug: see finding <id>` and falls back to `check case`. Also say who clears the stop afterwards.
- **n4. Storage cost (Heilmeier).** Each exhaustion keeps a full copy of the case tree and transcripts in every later encrypted checkpoint, bounded by the lifetime exhaustion count. State the measured size for 5813be. That is the only cost the section adds.
- **n5. Forward note for the dispatcher design.** The allowlist only keeps credentials out if the diagnosis role can read nothing but `inputs/`, under the same launcher isolation and `case_permissions`. The dispatcher design should state that the role's readable root is exactly this directory.
- **n6. Tie the snapshot to the existing boundary.** "Ordinary quiescent boundary" should name the existing `durable_checkpoint.checkpoint_progress(..., quiescent=True)` boundary, to show it is reused and not a new state.

## Readiness against the standards
- **implementation-readiness:** fails the zero-decision rule because of B1, Ma1's undefined "authenticated source", Ma2's required set and Ma3's source definition. The file targets (`diagnosis.py` plus the held tests) are implied, not listed.
- **heilmeier:** the objective, approach, risks and exams are clear. Cost is missing (n4).
- **zoom_out:** the scope is right and there's no YAGNI. Three spots hand-roll lists that the code already has (`gate_state.inventory`, `worker_files`/`source_files`, `checkpoint_progress`).
- **No hidden money or dispatch:** I found no money authority, model dispatch, public-config change or credential path in the section. B1 is the one hidden lifecycle decision.

## Tests
- I ran nothing. `/tmp/stream-d-held-suite.log` (pinned at fab9014) is not cited for this section. No full-suite pass is claimed, and no Murphy row closes.

---

Fixing B1 and Ma1 takes about a paragraph: one named terminal stop, plus "no manifest means re-stage". Ma2 and Ma3 are mostly a matter of pointing at the existing `gate_state.inventory` and the worker release manifest instead of hand-written lists.

## Elephant resolution

All findings accepted. B1 gets `diagnosis_input_invalid`, with no pending projection
or fresh ID. Ma1 deletes the orphan-reuse comparison: no manifest means re-stage
in the same parent directory. Ma2 reuses gate inventory, includes restored bench
results and the omitted retained evidence, and specifies required inputs without
requiring a gate-detail file from an attempt that crashed before producing one.
Ma3 uses the existing verified release manifest and shipped file set. N1–N3,
N5–N6 are made explicit. N4 records measured fixture bytes and distinguishes them
from the unavailable full private archive; no secret archive is decrypted.
No finding is rejected, no dispatch is enabled, and no Murphy row closes.
