Act as the review sub-agent for this task.

Fresh goldfish design review, read-only. Read tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md first, Mode: REVIEW. Apply heilmeier-standard.md and implementation-readiness-standard.md in tools/egm/document_standards. Review docs/designs/batch-practice-manifest.md and referenced sources only. User wants B3 reviewed policy, release pins, executable practice manifest and item8 draft; no workers, paid calls, push or merge. Dependencies intentionally unresolved; distinguish honest blocked preparation from unsafe runnable claims. Return complete review verbatim with blockers and pass/fail. Do not modify files or delegate.

Reading the design and the factory sources it references (batch.py, the existing practice manifest, stream-d Item 8) before I write the review.

Checking the earlier B practice design docs for the "two founder approvals" and the stream-d Item 8 numbers the draft is meant to copy.

Still reading sources: checking the existing practice policy and release reports from the earlier preparation before I write the findings.

Verifying the A-stream commit's claimed $10/$15 Claude profiles, then writing the review.

## Goldfish design review: `docs/designs/batch-practice-manifest.md` (design-1)

**Verdict: FAIL.** Three blockers are open.

Personas: zoom_out, design_critic, implementation_readiness. Mode: REVIEW. Standards: heilmeier and implementation-readiness, plus zoom-out as the persona requires. This was a read-only review: I changed no files, ran no workers, made no paid calls and pushed nothing.

### Checked and correct

- **Item 8 numbers match stream-d.** The total is $100, split $90 for models and $10 for infrastructure. Scenario caps are 10/10/5/15/15/25/10 (sum 90). Worker slots are 3/2/1/2/4/6/2 (sum 20). Execution minutes are 10/10/5/10/15/15/5 (sum 70). Run order is 1,2,3,4,5,7,6. Alpha gets $40 (10+10+5+15) and the beta releases share $50. Beta root halves are 7.50/12.50/5. Infrastructure is $0.40 × 20 workers + $2 = $10. Deadlines match: 8 hours total, 2 hours per worker, 15-minute overhead limit. Item 8 has no separate probe, and the five release/batch pairs are listed in order.
- **The manifest is unchanged.** `factory/batches/b-practice-20261031.json` still hashes to `90ce53ca…e928`, the same value in `docs/reports/stream-b-practice-policy-20261031.json`. Its `restore_recipient` equals `factory/control-recipient.txt`.
- **The A dependency is described honestly.** In d7539d1, `factory/token_prices.py:97-98` sets `:small` = $10 and `:medium` = $15. d7539d1 is not an ancestor of HEAD, so calling these "proposed dependency facts, not in this base" is accurate. A $10 minimum lease does make a cent-level probe impossible, and the design says so.
- **A new release is justified.** 12 trusted files changed between 6ac450e and HEAD, so the old `code_sha256` and release pins are stale.
- **Murphy rows exist** for 9, 39, 49, 51, new-single-path-1, new-batch-service-4 and new-isolation-outer-wall-2. Leaving out new-isolation-outer-wall-1 is correct because that row is closed. No row is claimed closed.
- **`--dry-run` means no model calls** (`factory/run.py:3154`).
- **The build is deterministic.** `factory/batch.py:build` uses gzip with `mtime=0`, sorted tar entries and only git objects, so the same commit rebuilds identical bytes.

---

### Blockers

**B1. The "inert runtime policy" claim is wrong: `practice-policy.json` can be launched through the legacy holder path.**
- **Where:** Change and scope, lines 19-21; Risks, line 80.
- **Finding:** The design treats "holder … remain[s] false" as one of the things keeping this policy inert. It doesn't.
  - `HOLDER_ENABLED` only gates the new batch holder. In `factory/key_holder.py`, `batch_request` returns `None` when the flag is false (around line 463). The request then falls through to the legacy launch path (around line 707).
  - For a batch job, that legacy path calls `batch_money.authorize` (up to the manifest's $20), adds the job config, injects real secret names and spawns the launcher with `UNBUG_CLOUD=boat`.
  - So if this file is served by `key_holder serve` with the founder identity, on a host whose `root` and `code_sha256` match, it creates a real cloud worker.
  - `--dry-run` removes model calls but not the worker, its infrastructure cost, or the cleanup risk. Cleanup is still unresolved: E's escaped-pipe work, new-isolation-outer-wall-2 and B's verified deletion.
  - The only real barrier is procedural: the founder must not serve the file.
- **Required fix:** The design must state the true barrier in plain words. It must also do one of two things:
  - (a) make the committed policy fail to load by construction, and have preflight prove that `policy_load` refuses the committed bytes; or
  - (b) keep it loadable, but name the founder's launch approval as the only gate, and make sure the README's "held commands" cannot be pasted and run as written. That means no complete `key_holder`/launch command line using this policy path.
  
  Remove "holder remains false" from the list of reasons it is inert.

**B2. The one executable artifact, `preflight.sh`, has no specified contract.**
- **Where:** lines 15, 22-23, 85-88.
- **Finding:** This file is the line between honest blocked preparation and something that looks runnable, yet every design choice in it is left to the implementer:
  - **Inputs:** release directory path, policy path, root.
  - **Exact checks:** `batch.verify` with root, the six pins, the manifest digest, `code_sha256` against the local fingerprint, `HOLDER_ENABLED` and `DIAGNOSIS_ENABLED` both false, `--dry-run` present, replacement disabled, item 8 `launch_ready=false` and all pins null.
  - **Where the draft arithmetic check lives.** Line 87 says to check it, line 88 says no new tests.
  - **What happens when `practice-bounds.json` disagrees with the bound manifest.** The manifest has `money_limit_usd` 20 and `claude_accounts` [2]. The bounds say the case gets at most $19.99 plus S, with fallback to account 1.
  - **Exit codes and output.**
  
  The critical point: a passing preflight must not look like "go".
- **Required fix:** Specify:
  - the arguments;
  - the ordered list of checks and what each one refuses;
  - that a successful run prints something like `PREPARATION VALID — LAUNCH BLOCKED:` followed by the blocker list from the README/pins;
  - that it never exits in a way a launch wrapper could read as authorization;
  - how the known mismatch between the inert manifest and the bounds is reported. Recommended: report it as an expected blocker, not a failure and not silence.

**B3. The policy's field values and the "translated local `policy_load`" are undefined.**
- **Where:** lines 19-20, 85.
- **Finding:** The holder schema needs `root`, `batch.release` (an absolute path), `path`, `recipient`, `code_sha256` and the `batch` fields (`factory/key_holder.py:118`, `factory/batch_money.py:62-82`). The design leaves four questions open:
  - **Host:** Is this the control VM at `/home/user/unbug-bench`, like the old policy, or local?
  - **Release path:** Where is the release installed?
  - **Recipient:** "existing public recipient" is ambiguous. There are two: the policy `recipient` (`age17aef…`), which the founder-unlock check uses at `key_holder.py:511`, and the manifest `restore_recipient` (`age1ae6f…`).
  - **Translation:** Which fields does "translated" rewrite?
  
  As written, the test can validate an object that differs from the reviewed bytes in unstated ways, so "reviewed policy" proves nothing.
- **Required fix:** Give every field's exact value or where it comes from. List exactly which fields translation may rewrite (expected: `root`, `batch.release`, perhaps `path`). Require preflight to show that the committed policy and the translated copy differ only in those keys.

---

### Major

**M1. The "two distinct founder approvals" (line 6) are never defined.**
- Say what each one authorizes and where it is recorded. Presumably one is the 2026-10-31 approval of $25 for practice (activation plan report, line 59) and the other is the $100 Item 8 approval, which stream-d says is requested, not granted.
- Also say whether policy or launch approval is a separate act.
- B1's fix depends on this.

**M2. The probe's "separately approved" status is uncited (lines 30-31, 36).**
- I found no repo record of approval for a probe of at most $0.01.
- The activation plan says "Do not generate paid calls solely to probe identity" during preparation, and stream-d forbids an extra probe for Item 8.
- Cite the approval or drop the probe from the bounds. Reserving $0.01 outside the case is harmless, but calling the probe "approved" is a claim the record doesn't support.

**M3. Release location, retention and commit sequence are unspecified (lines 17-18, 86).**
- The release must be built from a clean HEAD. Right now the design file itself is untracked.
- `batch-release.json` records the build commit, so `release-pins.json` will be committed afterwards. Docs are outside the build sources (`BATCH_SOURCE`), so this works.
- State:
  - the build commit;
  - where the release directory lives (outside the repo) and whether it is kept;
  - that the diff reviewer re-checks by rebuilding at that commit and comparing all six hashes, which works because the build is deterministic.
- State that `verify(root)` will fail once A or E change trusted files (token_prices and model_router both are). That staleness is the intended fail-closed behaviour, and preflight should report it as "pins stale", not as a crash.

**M4. Schemas for `practice-bounds.json`, `item8-draft.json` and `release-pins.json` are undefined.**
- Field names, units (dollars as decimal strings, like the manifest), the null and `launch_ready` fields, and how each scenario "points to" stream-d (heading plus scenario number, not line numbers) are all left to the implementer.
- Each pins file should carry `launch_ready: false`, the build commit and the blocker list.

**M5. Heilmeier gaps.**
- **Objective:** The design is dense with insider shorthand (holder schema, S, B2/A/E, carry-over). Add a two-sentence plain objective.
- **Impact:** "Who cares and what changes" is missing.
- **Timeline:** None is given.
- **Cost and metrics:** Present: $0, and the success criterion is reviewed manifests.

**M6. The live replacement manifest's requirements are only implied.**
- The inert manifest allows only Claude account 2 and puts $20 on the case.
- The design asks for account 2 first, falling back to account 1 only on proven rate exhaustion, a natural fallback round trip, and at most $19.99 plus S.
- The bounds should state as explicit replacement-manifest requirements: `claude_accounts` [2,1] with initial account 2 once A lands, and the job commitment set to S + E. Without that, the fallback acceptance cannot be met.

---

### Nits

- **N1.** Don't call `preflight.sh` "the executable manifest" (line 22). Call it a preflight, in the README too, to avoid exactly the confusion the risk section describes.
- **N2.** The funding limits "Codex subscriptions only, OpenRouter existing credit only" are not in stream-d Item 8. Cite where they come from. A subscription does not fix the missing enforced OpenAI maximum for scenarios 4 and 6.
- **N3.** Record the stream-d commit or hash that `item8-draft.json` copies from, so later drift can be detected.
- **N4.** Commit the design file before the release build; the clean-tree check requires it.

---

### Blocked preparation vs. unsafe runnable claims

**Honest blocked preparation:**
- the A maxima stated as dependencies that aren't in this base;
- the probe marked as not executable;
- Item 8 pins and inputs null with `launch_ready=false`;
- the B2/E/A/D dependency ownership list;
- the statement that the final release and policy need a new review;
- no Murphy row closed.

**Unsafe or unproven:**
- the "inert runtime policy" claim, which rests on `HOLDER_ENABLED` (B1);
- an unspecified preflight that could pass silently (B2);
- policy bytes validated in an untranslated or unspecified form (B3);
- an "approved" probe with no cited approval (M2).

**Pass/fail: FAIL.** B1-B3 must be fixed, then a fresh goldfish should re-review.

## Elephant resolution
B1: non-loadable sentinel root; flags are not safety barriers. B2: explicit preflight contract and exit 3. B3: exact fields and two-key temporary translation. M1–M6/N1–N4 incorporated in design contract. No findings rejected; fresh review requested.

