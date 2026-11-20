# Design review 1: g2-blocked-source (goldfish)

Reviewer: fresh Claude subagent (general-purpose, no history), read-only; personas zoom_out, design_critic,
implementation_readiness; standards heilmeier, implementation-readiness. Reviewed the first draft of
`docs/designs/g2-blocked-source.md` (JSON ruling file in `factory/`, shipped via `WORKER_CONFIG`).

## Checked and found correct

- **Identity claim.** I ran `gate_state.runner_inputs` for G1–G17 on this tree. Only G2 reaches `checked_freshness_verdict`, `confirm_hits`, `_g2` and `ensure_freshness`. G8 and G9 reach `retained_answer`, which this design does not change. `loop_freshness` is reached only from `engine_stress_round`, and the stress `scientific_version` does not hash runner source (`gate_state.py:270-280`). The gate-identity rule also holds for engine checkpoints: `checkpoints.directory` drops plumbing (`durable/checkpoints.py:115-120`). `run.py` and `launch_manifest.py` are not in `VERDICT_CODE` (`checkpoints.py:130-133`).
- **Why the sealed FOUNDER_RULING can't be used.** The note's argument holds against the code:
  - A ruling reaches a step only through `escalate` (`engine.py:1949-1971`), and only a STRESS or GATES step (`contract.py:260`).
  - `resume_held` sends only `{"kind":"resume","hold"}` (`engine.py:2647-2657`).
  - The ruling digest is in `source_binding` (`run.py:3214-3216`), so it rescopes `checkpoints.directory` (`:116-119`) and `retained_answer` (`run.py:405`).
  - `review` appends `engine_review_ruling(c)` without a gate (`run.py:2424`, `3272-3280`), so G8/G9 would read the ruling.
- **The file reaches workers.** A `WORKER_CONFIG` entry goes into `worker_files` (`launch_manifest.py:26-42`), and `_release_files` keeps every `factory/` name (`durable/workers.py:238-243`). There is a precedent: `rotation-3writers.json` is read on the worker via `PROMPTS.parent` (`model_runtime.py:219`).
- **Scope gate.** Requiring `access_failure(receipt)` (`freshness_retrieval.py:142-145`) means a page that becomes readable live goes back to the reviewer. The flagged codes 202, 429 and 403 all match it.

## Findings

1. **BLOCKING: "a reviewed answer that confirms `same_bug: true` is never overridden" is undefined for invalid answers. As written, a ruling can hide a match the reviewer claimed.**
   - `checked_freshness_verdict` only counts a confirmation when the answer is valid. That means `agrees()` matches the receipt, the answer is resolved, and the archive URL passes the regex (`run.py:2224-2264`).
   - Example: on a 2a7b2a cycle where the Wayback copy appears, the reviewer writes `same_bug: true` but fails `agrees` or the snapshot regex. Today that row stays blocked. Under the design it is "would stay blocked + receipt access failure", so a `not_needed` ruling clears it.
   - This is exactly the "mask a real public match" case. It also leaves the implementer a decision to make, which breaks the zero-decision rule.
   - Fix: say the ruling never applies when `isinstance(answer, dict) and answer.get('same_bug') is True`, whether or not the answer is valid. Add that case to the scope tests.

2. **BLOCKING: the release itself resumes the held cases. A digest or URL mismatch then burns one of three lineage resumes, and no repo test can catch it.**
   - `wait_for_fix` ends the hold as soon as the batch's plumbing changes (`engine.py:1929`). `resume_held` is only the other trigger (`:1941`), so operator step 2's `resume_held` will normally return False.
   - Each resume counts against `MAX_FACTORY_BUG_RESUMES = 3` (`engine.py:468`, `945-949`).
   - The two values that must be right are `statement_sha256` (of the held snapshot's `case/statement.md`) and the exact URL. The statements are secret, so the test claim "their statement digests are the held cases' real ones" can only compare against a digest copied into a fixture. That proves nothing.
   - Fix:
     - Add an operator pre-release step: a read-only check on the VM against each held snapshot, in the style of `tools/open-g2-verdicts.py`. It loads the snapshot's case, flagged rows, receipts and verdict, runs `checked_freshness_verdict` with the new code, and asserts the row lands in `ruled_rows`.
     - Rewrite operator steps 2–3:
       - The release is the resume.
       - Never `plumbing_release` to `b-import-18681d-h5` until its ruling is in; any release to that batch resumes it.
       - State each lineage's remaining resume count.

3. **NON-BLOCKING: `keep_mixed_receipt` calls `checked_freshness_verdict` with a namespace that has no `case` or `card`** (`ordinary_freshness.py:129-131`; `ensure` calls it on `public_match` with `unresolved_hits`, `:221`).
   - A ruling lookup that reads `c.case / 'statement.md'` raises `AttributeError` there and crashes the step. A `getattr` fallback instead silently leaves a `hand_checked`/`reports_this_bug: true` row out of `confirmed_rows`.
   - Fix: name the change, `case=c.case` on `one`. Also list `tools/open-g2-verdicts.py:84-91`, which already passes `case` and needs nothing. `ordinary_freshness.py` is outside G2's hashed inputs, so this does not touch identity.

4. **NON-BLOCKING: the identity proof is an off-tree script.**
   - `myident.py` does not exist in the repo. The hard constraint ("no other gate's identity changes") should be a committed test.
   - Fix: add a test asserting that `checked_freshness_verdict`, `G2_SOURCE_RULINGS` and `g2_source_ruling` are in `gate_state.runner_inputs('G2')` and in no other gate's.

5. **NON-BLOCKING: cost and risk of the resume are missing (Heilmeier Cost and Risks).**
   - `retained_answer`'s binding includes the full `source_binding`, plumbing version included (`run.py:405`, `3214`). So after this release the G2 reviewer is re-asked on every flagged row, not served from retention: 361 rows for cae763, 5 for 18681d, 16 for 2a7b2a.
   - A fresh answer can leave a different row unresolved. `REVIEW_REASKS = 2` (`ordinary_freshness.py:18`) limits the retries, so G2 can still fail with `freshness_review_unavailable` even with the ruling.
   - The bot_wall end-to-end test ("G2 passes on its first cycle") does not reflect this path.
   - Fix: state the expected reviewer spend and this residual risk. The timeline is also missing.

6. **NON-BLOCKING: there is a smaller design, and it closes the identity hole. The note should weigh it.**
   - The note says it follows aa7a1bf9's path ("written into G2's own code"), but it puts the data in a JSON file outside G2's identity. That needs a new `WORKER_CONFIG` line, file I/O, and an unspecified missing-file case.
   - Alternative: a module-level constant in `run.py` next to `SOURCE_CODE_NOT_PUBLIC`.
     - Gains: it is hashed into `runner_inputs('G2')` automatically (`gate_state.py:93-123`), ships under `WORKER_GLOBS`, needs no manifest change, and removes the "Known ceiling".
     - Costs: every later ruling addition (18681d) changes G2 identity for every batch that receives that release.
   - The ceiling as written is also wrong in one respect: "withdrawing one needs a new release anyway" does not mitigate anything. Gate checkpoints ignore plumbing, and the file is not hashed, so a new release leaves the checkpointed G2 pass in place.
   - Fix: pick one option and record the trade-off. If the JSON file stays, correct the ceiling text.

7. **NIT: the ruling also applies in the stress-round `loop_freshness` to attacker-requested rows with the same URL** (`run.py:1280-1287`). This is consistent with a per-URL ruling, but the note should say so. It should also say that several flagged rows sharing one URL are all cleared, which goes past the literal "that one flagged row".

8. **NIT: the ruling schema leaves decisions open.**
   - Which fields are matched? (`case` and `gate` appear to be decorative.)
   - What value does `decision` take, and how does it relate to `kind`?
   - What happens if the file is missing or unparseable? The answer should be: nothing applies, and the release check in finding 2 catches it.
   - What counts as "valid": types, the `checked_at` regex, non-empty `page_says`?
   - The cited format source `rulings/22e434-h2-g8-continue.json` is not in the repo, and no code validates that schema.

9. **NIT: conflict with a design rule.** ENGINEERING section 4 says "Do not add … one-off rulings". The note should cite the founder decision of 2026-11-20 as the explicit override, so a later reader does not "fix" it away.

10. **NIT: secrecy.**
    - `ruled_rows` copies the whole entry, including the hand-check `page_says`, onto the card. The repo file names case IDs and URLs next to bug-related text.
    - Confirm neither is visible to contestants, or keep `page_says` out of the card and the repo (store its sha256 instead).

11. **NIT: missing files.** `docs/murphy-register.md` and `docs/ENGINEERING.md` are not in this worktree, so the claim that row `new-walled-flagged-row-1` exists cannot be checked from the branch under review.

**Verdict: FAIL** (2 blocking: findings 1 and 2)

## Resolution (elephant)

All findings accepted; none rejected.

1. Fixed. `g2_source_ruling` returns nothing when the answer is a dict with `same_bug: true`, valid or not; scope test "reviewer claims the match".
2. Fixed. Operator steps rewritten (the release is the resume; never release to 18681d before its ruling; `diagnoses: 1` on each card, 3 resumes per lineage). Added the read-only VM pre-release check (`$SP/g2rule/vmcheck.py`): it runs the candidate `run.py`'s `g2_source_ruling` in memory against each held case's real snapshot statement, flagged rows, receipt and retained answer. Run on this branch: cae763 OK, 2a7b2a OK, 18681d "NO RULING" (as expected).
3. Fixed: `keep_mixed_receipt` passes `case=c.case`.
4. Fixed: `test_only_g2_identity_reads_the_rulings`.
5. Fixed: "Cost and risk of the resume" section.
6. Taken: rulings are now the constant `run.G2_SOURCE_RULINGS`; no JSON file, no manifest change, the ceiling is gone.
7. Stated in the note (several rows of one URL; stress-round `loop_freshness`).
8. Fixed: schema table (exact keys, matched fields, validity); `decision` dropped (`kind` says it).
9. Cited as an explicit founder exception.
10. Answered: the contestant box copies only `factory/case_permissions.py`; the card is private and published via the allowlist. `page_says` stays (it is the hand check the founder asked the factory to take as the source's content).
11. Noted in the note: the register is the main checkout's untracked file.
