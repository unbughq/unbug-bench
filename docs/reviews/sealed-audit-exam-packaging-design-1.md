# Design review 1: sealed-audit-exam-packaging

Reviewer: fresh goldfish run as a `claude -p` subprocess (Claude Code 2.1.318), with no conversation history. It is the same model family as the elephant, because no other family was reachable from this cloud session.

- **Tools:** read-only (Read, Grep, Glob, git show/log/diff, ls, wc).
- **Personas:** zoom_out, design_critic, implementation_readiness. Mode: REVIEW.
- **Standards:** `heilmeier-standard.md`, `implementation-readiness-standard.md`.
- **Reviewed:** the first, uncommitted draft of `docs/designs/sealed-audit-exam-packaging.md`.

## Verbatim review

The design gets the main thing right but fails review on three blocking problems. Its plan is to count cases from public files only, and it never treats public evidence alone as enough to qualify a case, so "qualified" always stays 0 until a decrypting audit runs. The problems are a wrong case count, a freeze step that cannot run on this repo, and too many decisions left to whoever writes the tool.

# Goldfish design review: `docs/designs/sealed-audit-exam-packaging.md`

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier-standard (design), implementation-readiness-standard (readiness).

## Summary

The design is preparation only and stays inside the job's limits. It reuses the existing exam admission check (`verify_exam_metadata`) instead of writing a second one. It records unavailable evidence as unavailable. Money and deadline stay null and founder-required, and it reports the expected shortfall instead of raising limits. It deletes nothing, closes no Murphy rows, and does not count practice fixtures.

Checked against the files, it fails in three ways:
- **The headline count is wrong.** It says 51 hidden cards, but 51 is the number of files and includes the dry-run card it excludes elsewhere.
- **The freeze step cannot run.** The packaging procedure depends on `bin/freeze create`, which rejects this repository's top-level layout.
- **Too many choices are left to the implementer.** These include the "canonical hash" method, the rules for filling each criterion cell, how `--round` treats archives that aren't in the checkout, and where the package lives.

The production manifest proposal also leaves out "completion timeouts" and the per-case attempt limit, both of which the handoff checklist item names.

## Findings

**1. BLOCKING: the hidden-card count contradicts the exclusion rule.**
- *Evidence:* The design says 51 hidden cards at `sealed-audit-exam-packaging.md:100` and test 1 at `:158`. There are exactly 51 `sealed/case-*.scorecard.json` files, and one of them is `sealed/case-20261014T130816Z-a869de.scorecard.json`, which has `"dry_run": true` and `"source": "fixture (dry-run)"` (lines 3–4). Test 3 (`:163`) excludes that same card. So the number of hidden cards is at most 50. The shortfall rate "3 in 51" (`:121`) uses the same wrong denominator. This is the "hand count includes a dry-run card" mistake the design was written to prevent.
- *Fix:* State 50 hidden cards and 1 excluded card in `sealed/`, plus 1 excluded smoke card outside `sealed/`. Change test 1 to "exactly 50 hidden, exactly 1 excluded from `sealed/`". Restate the rate as 3/50.

**2. BLOCKING: the procedure step `bin/freeze create` does not work on this tree, and the package location is undefined.**
- *Evidence:* `bin/freeze:58-64` (`source_files`) raises "Unclassified bench inputs" for any top-level name outside `INPUTS`, `EXCLUDED`, `.git`, `results` and `sealed`. This checkout has `docs`, `tools`, `analysis`, `control`, `report`, `EXAM.md`, `AGENTS.md`, `CLAUDE.md`, `refusal-integration-r*.json` and others at the top level, so `create` fails today. `bin/freeze:103-104` also refuses output under the input folders; the documented location is `results/freeze/<id>`. The design's `exam/<round-id>/` (`:127`) gives no parent folder. If it sits at the repo root, it becomes one more unclassified input.
- *Fix:*
  - Say where the package lives: `results/exam/<round-id>/`, or a stated path outside the source root.
  - Say which `--root` `bin/freeze` runs against.
  - Record that `bin/freeze create` currently refuses this tree. Either name the reviewed change that classifies those top-level names, or list it as an open blocker in `docs/exam-packaging.md`.
  - Add a test that runs `bin/freeze create` against a copy of the real tree, or mark the step "not yet runnable" with the reason.
  - Don't claim the procedure is reproducible until this works.

**3. BLOCKING: the "canonical hash" method for test 1 is not defined.**
- *Evidence:* The VM cards in `docs/designs/stream-d-cost-evidence.json` carry `canonical_json_sha256` with no recorded method. Review finding N3 in `docs/reviews/stream-d-design-1.md:162` already flagged this ("does not record how … was computed"). `stream-d.md:948-951` mentions migrated projections for 6a8a7d, cae763 and 055481, so it's not safe to assume every card in the checkout matches the 2026-10-29 record byte for byte.
- *Fix:* Write out the exact method, e.g. `sha256(json.dumps(card, sort_keys=True, separators=(",", ":")).encode())`, and confirm it reproduces every VM record. Name the cards expected to differ. If the method can't be found, report that cell as `unavailable:canonicalization-method` instead of asserting equality.

**4. BLOCKING: the rules for filling each criterion cell are left to the implementer.**
- *Evidence:* The table at `:61-70` lists evidence sources but not how each becomes `pass`, `fail`, `missing` or `unavailable`. Examples:
  - In `sealed/statement-registry/registry.json`, every visible entry, including fcde6b, has `"complete": false`. Is that `fail`, `missing` or `pass` for "Distinct bug"?
  - "Card wipe record clean" (`:70`) names no field or test. Cards carry a `wipe` object of unspecified shape.
  - An absent G16/G17 key: test 2 (`:162`) calls it a "fail at G16 with verify_exam_metadata's fairness error", but the cell grammar suggests `missing:G16`.
  - `dedup.duplicate_of` set: 953035, 6a8a7d and 5a6ef3 are non-null.
  - What "`source` names a fixture" means (`:80`).
  
  Under the zero-decision rule, each of these is an open design choice.
- *Fix:* Add a decision table with one row per criterion. Each row gives the exact card or registry field path, the predicate, and the resulting value. For example: absent gate → `missing:Gn`; `"fail"` → `fail:Gn`; `registry.complete == false` → `missing:registry-complete`; `duplicate_of != null` → `fail:duplicate_of=<id>`. Define the not-hidden rule exactly: `dry_run is True`, or `source not in {"port", "hunt"}`, or the ID matches `practice|smoke`. Add one test per rule using the real cards named above.

**5. BLOCKING: the `--round` check has no defined behaviour for archives that aren't present.**
- *Evidence:* The design says `--round` "does not open the archives" (`:87`). But `bin/exam-round:specification` (`:42-52`) requires `archive.is_file()` and hashes the archive bytes, which reads the `.age` file. So the tool can't reuse `specification()`. No `*.tar.gz.age` exists in this checkout, so for test 5 (`:170-172`) every archive is missing.
- *Fix:* State that `--round` parses `round.json` itself and maps each archive to a case using `bin/exam-round`'s rule (`name.removesuffix(".tar.gz.age")`). It looks up `sealed/<case>.scorecard.json` and checks neither the archive's existence nor its bytes. State the exit code and error text for each rejection: not hidden, not eligible, duplicate, wrong count. Optionally factor `bin/exam-round`'s name-to-case rule into a shared helper so the two can't drift.

**6. BLOCKING: the manifest proposal leaves out checklist fields.**
- *Evidence:* `docs/cloud-handoff.md:96-97` asks to pin "completion timeouts, roles, cumulative money ceiling, deadline and attempt/concurrency limits". The design's manifest (`:110-118`) has creations, money, deadline, concurrency, milestones and roles, but no completion timeouts and no per-case attempt or extension limits. ENGINEERING.md §3 sets the limits at 5 extensions and 3 factory-bug resumes.
- *Fix:* Add `completion_timeouts` (copied with citations from the reviewed pilot or stream-d values, or `null` plus `founder_required`). Add `per_case_limits: {extensions: 5, factory_bug_resumes: 3}` citing ENGINEERING.md §3. Extend test 7 to check these.

**7. NIT: role pins taken from `pilot-bounded-roles.md` are tied to the pilot.**
- *Evidence:* `docs/designs/pilot-bounded-roles.md:16-22` binds admission to the exact manifest ID `b-real-pilot` with exactly three templates. A 48-creation production proposal that references those pins can't be admitted under that rule.
- *Fix:* Say outright that admitting the production proposal needs its own reviewed admission change, so readers don't think it is one approval away from launch.

**8. NIT: test 3's smoke-card exclusion proves nothing.**
- *Evidence:* The tool's inputs are only `sealed/case-*.scorecard.json` (`:38`). The smoke card is in `docs/reports/provisioning-startup-smoke/...`, so it is never scanned, and "excluded and never counted" is true by construction.
- *Fix:* Add a `--cards DIR` (or extra-path) input and have test 3 run the tool against that real smoke card's directory, asserting it is reported as excluded. Otherwise drop the smoke half of the test.

**9. NIT: test 4's "patch open/read_bytes" guard is narrow.**
- *Evidence:* `verify_exam_metadata` imports `exam_responder` and `gate_state` and hashes `factory/*.py` (`factory/sealed_audit.py:24-31, 71-73`). A patch on `builtins.open` and `Path.read_bytes` misses `Path.read_text`, `os.open` and `io.open`.
- *Fix:* Also patch `Path.read_text` and `os.open`, and match on `.age` and on names containing `key`, as the job requires (it also forbids files named `*key*`, e.g. `sealed/case-20261014T130816Z-a869de.throwaway-key.txt`).

**10. NIT: Heilmeier cost and timeline aren't stated.**
- *Evidence:* There is no "Cost" or "Timeline" line. The work is offline, but the standard asks for both.
- *Fix:* Add one line: zero model or compute spend, one implementation and review increment, plus one full offline suite.

**11. NIT: the expected-result claims in §2 are asserted, not derived.**
- *Evidence:* "0 public-eligible" and the three G1–G15 cards (`:100-103`) are consistent with what I checked: no card has a G16, G17 or `owner_contract` key, and all three archive hashes appear in both the Mac and VM inventories (`batch-service-inventory-20261030.json:44,93,129` and `:815,864,900`). But the design states them before the tool exists.
- *Fix:* Label them "expected; the generated report is authoritative" so test 6 decides the numbers.

Verdict: FAIL

## Disposition (elephant)

All six blocking findings are fixed in the design. None were rejected.

1. **Fixed.** The count is now 50 hidden cards plus 1 excluded card (a869de, a dry run). The shortfall rate is restated as 3/50. Test 1 asserts both numbers.
2. **Fixed.**
   - The package lives at `results/exam/<round-id>/`, which is git-ignored and accepted by `bin/freeze`. `--root` is the release checkout.
   - `bin/freeze create` refusing this tree is recorded as a known blocker in `docs/exam-packaging.md`. Test 8 keeps the blocker list in step with the real refusal.
   - The procedure is not claimed to be reproducible until that blocker is cleared.
3. **Fixed.** `stream-d-cost-evidence.json` records the hash method in `extraction_method.vm`: SHA-256 of the UTF-8 bytes of `json.dumps(card, sort_keys=True, separators=(',', ':'))`. Before revising, the elephant reproduced all 51 VM records whose cards are present using that method. The design now states the method and names the three cards that exist only on the VM. Hash cells report `match`, `differs` or `not-recorded`, and are informational only.
4. **Fixed.** The design now has:
   - a gate-value rule table;
   - ordered parts for each criterion, with exact field paths and values;
   - the meaning of the registry `complete` flag (historical import, `factory/registry.py:83`);
   - the wipe-record predicate;
   - the exact not-hidden rule: `dry_run`, `source` not in {port, hunt}, or an ID matching `practice|smoke`.

   Test 3 adds one real-card case for each rule.
5. **Fixed.** `--round` parses the JSON itself and maps archive basenames using `bin/exam-round`'s rule. It never opens, stats or hashes an archive, and it prints a defined message for each rejection.
6. **Fixed.** The proposal adds:
   - `completion_timeouts: null`, marked founder-required. It cites the 8 h default and the pilot's 30-minute experiment, and chooses no value.
   - `per_case_limits`: 5 extensions and 3 factory-bug resumes, from ENGINEERING section 3.

   Test 7 checks both.
7. **Nit, accepted.** The separate reviewed admission change is recorded under blockers.
8. **Nit, accepted.** Added `--cards DIR`. Test 4 runs against the real smoke card directory.
9. **Nit, accepted.** Test 5 also patches `io.open`, `os.open` and `Path.read_text`, and matches any name containing `key`.
10. **Nit, accepted.** Added a cost/timeline line.
11. **Nit, accepted.** The expected numbers are labelled as expected. The generated report and test 6 are authoritative.
