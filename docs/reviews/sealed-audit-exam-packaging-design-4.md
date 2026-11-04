# Design review 4: sealed-audit-exam-packaging

Reviewer: a fresh goldfish, run as a `claude -p` subprocess with no conversation history. It is the same model family as the elephant. Its tools were read-only. Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: `heilmeier-standard.md` and `implementation-readiness-standard.md`.

It reviewed the design after three revisions, together with design reviews 1 to 3.

## Verbatim review

Review written. I made no edits. Python execution needed approval, so I checked everything with read-only reads and greps.

# Goldfish design review 4: `docs/designs/sealed-audit-exam-packaging.md`

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard (design review), implementation-readiness-standard (readiness review).

## Summary verdict

The design stays inside the job's limits:
- It reads only public files. The tool opens no `.age` file and no file whose name contains `key`.
- It records missing evidence with three fixed `unavailable:` tokens. Because public files can never supply those parts, the qualified count is 0 by design (`:117-123`).
- Dry-run, practice and smoke cards are excluded and never counted (`:67-75`).
- It reuses `verify_exam_metadata` and adds no new runner.
- The manifest proposal is inactive: 48 creations including retries; money, deadline and completion timeouts are null and listed in `founder_required`; no model route changes and no budget or ledger changes (`docs/designs/production-manifest-proposal.json:4-26`).

All blocking findings from the earlier reviews are fixed in the design text: review 1 #1–6, review 2 #1–3 and review 3 #1. I checked them against `tools/sealed_inventory.py`, `docs/exam-packaging.md` and the proposal JSON.

One new blocking problem remains, and it is really an incomplete fix of review 3 #1. The fresh-snapshot requirement covers procedure step 1 but not step 2. Run as written, the step 2 round check uses the dated defaults and rejects every case sealed after 2026-10-30. That means it rejects every real 24-case round, which is the failure review 3 #1 described.

## Prior blocking findings: checked

| Finding | Status | Evidence |
|---|---|---|
| R1 #1 count | Fixed | `:171`, test 1 `:271-274` |
| R1 #2 freeze and package location | Fixed | `:218-220`, `:249-254`; `docs/exam-packaging.md:79-104` |
| R1 #3 hash method | Fixed | `:47-52` |
| R1 #4 rule for each cell | Fixed | `:84-115`; code `tools/sealed_inventory.py:51-136` matches |
| R1 #5 `--round` | Fixed | `:134-151`; `check_round` uses `removesuffix('.tar.gz.age')` (`tools/sealed_inventory.py:213`) |
| R1 #6 manifest fields | Fixed | `:195-203`; proposal JSON `:13-31` |
| R2 #1 test 3 values | Fixed | Tests assert on `findings` (`:283-296`) |
| R2 #2 eligibility path | Fixed | `:173-184`; proposal `blockers` |
| R2 #3 registry status | Fixed | `:108`; `registry_cell` (`tools/sealed_inventory.py:97-104`) |
| R3 #1 stale snapshots | Partly fixed | Flags and `inputs` hashes are added (`:53-65`), but see finding 1 |

## Findings

**1. BLOCKING: the procedure's round check (step 2) still runs on the dated snapshots.**
- *Evidence:*
  - The design ties the fresh-snapshot rule only to "the freeze-time run … (§4 step 1)" (`:62-64`). §4 step 2 says only "Run the `--round` check" (`:239`). The `--round` section (`:134-151`) never says which inventory or registry it judges against.
  - The deliverable's step 2 command is `python3 -B tools/sealed_inventory.py --round results/exam/<id>/round.json --expect 24` (`docs/exam-packaging.md:44`). It has no `--inventory` or `--registry`.
  - `main` recomputes the inventory from the flags given in that same call (`tools/sealed_inventory.py:244-246`). Step 2 therefore falls back to the 2026-10-30 inventory and the checked-in registry. Every newly sealed case then fails with `not eligible <id>: missing:ciphertext-inventory` or `missing:registry-entry`.
  - The `inputs` hashes kept in the package come from step 1, not from the check that actually gates the round.
  - Test 8 (`:318-324`) and `test_round_check_messages` exercise `--round` only on the default snapshots.
- *Fix:* Make the round check use exactly the step 1 evidence. Either works:
  - **(a) Simplest:** merge steps 1 and 2 into one call that passes the same `--cards`, `--inventory` and `--registry`, writes `inventory.json`, and runs `--round`. Then define in the design that `--round` uses whatever snapshot flags are passed.
  - **(b)** Have `--round` read the step 1 `inventory.json` and refuse to run if that file's `inputs` don't match the given flags.

  Update §1 `--round`, §4 step 2 and `docs/exam-packaging.md:44` to match. Add a test 8 case: `--round` with fcde6b and the edited inventory/registry copies from test 3 reports `not eligible … missing:ciphertext-inventory`. This confirms the round check honours the snapshot paths.

**2. NIT: §4 has drifted from its own deliverable.**
- *Evidence:*
  - The design lists six steps, with freeze at step 4 and hashing at step 5 (`:238-244`). `docs/exam-packaging.md:36-77` has eight: hashes and cards at 4, freeze at 5, seal at 6, launch at 7, report at 8.
  - The design's "Known blocker" names only `bin/freeze` (`:249-254`). The doc also lists "no fresh ciphertext inventory or registry snapshot" (no producer, founder host access) and "no archives in this checkout" (`docs/exam-packaging.md:116-128`). Review 3's disposition says these were added "next to the `bin/freeze` blocker", but that happened only in the doc.
- *Fix:* Copy the doc's step order and its three extra blockers into design §4, so the diff review checks the code against the same text.

**3. NIT: the `not eligible` message token is ambiguous.**
- *Evidence:* The design says the message shows "`<first non-pass cell>`" (`:145`). A criterion cell can itself be an `unavailable:` token (`:95-96`). The code instead prints the first finding that is not `unavailable:`, across criteria in table order (`tools/sealed_inventory.py:226-228`).
- *Fix:* State the code's rule in the design: the first finding, in criterion-table order, that does not start with `unavailable:`.

**4. NIT: the ciphertext match is not tied to the card's own case.**
- *Evidence:* The design says "not equal to a final `<case>.tar.gz.age`" (`:114`). `evidence()` builds a single hash→hosts map over all cases' final archives (`tools/sealed_inventory.py:87-92`), so a card hash equal to another case's final archive would pass.
- *Fix:* Key the map by `(case, sha256)`, and say "this case's final archive" in the design.

**5. NIT: test 2 wording.**
- *Evidence:* "`verify_exam_metadata` returns its fairness error" (`:281`). The function raises `ValueError` (`factory/sealed_audit.py:69-70`), and the tool records the error text.
- *Fix:* Change the wording to "the metadata cell records the fairness `ValueError` text (`fail:metadata`)".

**6. NIT: Heilmeier "impact" is implicit.**
- *Evidence:* No line says who uses the counts or what decision they unblock. (The checklist ramp and the founder's money cap and deadline decision depend on the shortfall estimate.)
- *Fix:* Add one line under Problem that names the decision these numbers feed.

Verdict: FAIL

## Disposition (elephant)

The blocking finding is fixed, using option (a). No finding was rejected.

1. **Fixed.**
   - The design now says `--round` uses whatever `--cards`, `--inventory` and `--registry` flags the same call passes.
   - Design §4 step 2 and `docs/exam-packaging.md` step 2 now require exactly the step 1 snapshot flags.
   - `test_snapshot_paths_are_honoured` now runs `main(['--round', ..., '--inventory', copy, '--registry', copy])`. It asserts that the inventory was computed from exactly those paths. It also asserts that fcde6b is reported `not eligible`.
2. **Nit, accepted.** Design §4 now uses the doc's eight steps and its full blocker list.
3. **Nit, accepted.** The design now states the code's rule for the `not eligible` token: the first finding, in criterion-table order, that does not start with `unavailable:`.
4. **Nit, accepted.** The code keys the ciphertext map by `(case, sha256)`, and the design says "this case's own final archive". The count is unchanged: 10 hidden cards have a final archive in both inventories.
5. **Nit, accepted.** Test 2 wording now reads "the metadata cell records the fairness `ValueError` text (`fail:metadata`)".
6. **Nit, accepted.** Under Problem, the design now names the decision these numbers feed: the founder's money cap and deadline, and whether 24 is reachable within 48 creations.

Two parts of the design text received no fifth review: the step 2 wording and the `--round` sentence. Both are checked against the code in the diff review (`sealed-audit-exam-packaging-diff-1.md`).
