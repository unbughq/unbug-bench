# Design review 2 (goldfish): `docs/designs/stream-b-delayed-creation.md`

**Verdict: PASS for the narrower increment.** B1–B3 and M1–M3 from review 1 are resolved in the design text. No blocking finding is open. Two Major findings should be fixed in the text or carried into the diff review. The full cleanup supervisor, the cumulative USD 5 proof, the legacy b275 disposition and both activation gates are still blocked, and the design correctly claims none of them.

**Setup:** Mode REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md and implementation-readiness-standard.md. Worktree `t3-ded79ec5` at `0c4eb3a`; the design, review and reports are untracked.

**Read:**
- `docs/ENGINEERING.md`, the three persona files, both standards, the design and review 1
- `bin/boat-spend` (all of it) and `bin/boat-launch-guards.sh` (`guard_new` 70–95, `guard_exit` 255–285)
- `factory/batch_holder.py` lines 335–360
- `tests/factory/test_isolation_timeouts.py` lines 340–428 and its fixture README, `list.json` and `billing.json`
- `docs/designs/isolation-timeouts.md` (the expiry passages), and a grep of `docs/murphy-register.md`
- the retained provider pages and `sources.json`; I re-hashed all three pages and the SHA256 values match

**Not done:** no edits, VM access, secrets, workers, paid calls, push or subagents, and no suite run.

---

## Blocker dispositions

### B1 (provider evidence misstated): RESOLVED in the text; the provider prerequisite stays open
- I checked the design's claims (lines 53–60) against the retained pages and they hold:
  - The timer counts "from creation or from the last resume, not from your last activity" (auto-stop.md:14).
  - "Your own jobs do not move the deadline" (auto-stop.md:111).
  - A running prompt is the only automatic extension (auto-stop.md:16).
  - The stop starts "within about 5 seconds" (auto-stop.md:109).
  - "A stopped sandbox costs nothing in VM time" (billing.md:140).
- The design now treats the per-worker bound as able to support a dollar bound "if its exceptional behaviour is qualified". It does not record the TTL as proof of the cap. That is correct.
- The residual list (lines 62–73) covers all of review 1's gaps a–f, plus retained storage and the per-member caps.
- The design does not claim closure. Admission still has to refuse.

### B2 (legacy launch tied to provider evidence): RESOLVED in the text; the b275 disposition stays open
- I checked the local route against code:
  - `guard_new` opens `new.$serial` before `boat new` runs (guards.sh:75).
  - `_reconcile_one` returns early on any `new.*` and treats a missing `ids` file as empty, under both locks (batch_holder.py:345–354).
- Lines 94–95 state plainly that the block is a review/policy rule and that no admission check scans non-journal launches. That answers review 1's question.
- Lines 103–111 require fresh read-only VM evidence and deployed-launcher provenance. They also say an mtime comparison alone is not enough. That is stricter than review 1 asked, which is good.
- The design claims no disposition. Correct.

### B3 (inventory-based release kept in code): RESOLVED, and this is now the scope
- The target is exact: `bin/boat-spend:112–124`, the expired-hold `list --all` query and the move to `reconciled_expired`.
- I found no other code or test that depends on it. The only `expires_at` and `reconciled_expired` uses outside `boat-spend` are the one test (`test_isolation_timeouts.py:411–418`) and `isolation-timeouts.md`.
- The inverted test is a real regression. `fixtures/isolation-timeouts/list.json` is a saved, complete, empty inventory (`hasMore:false`, `sandboxes:[]`) and `billing.json` is a saved receipt. The old code would therefore release the hold under this exact input, and the new code must refuse.
- Fail-closed is confirmed. `guard_exit` skips `--finish` while any `new.*.pending` file exists (guards.sh:261–273). With the expiry release gone, an unknown create keeps its full hold.

### M1 (no cumulative-cap baseline): RESOLVED
Lines 77–80 say `--check` does NOT enforce settled + holds + new <= USD 5, and that this is future work.

### M2 (wallet is not a cap): RESOLVED
- Lines 75–76 say the wallet is not a cap. The retained page backs this: it can go "below zero during the grace period" (billing.md:33, 250–255), and "A personal account has no dollar cap" (billing.md:131).
- Per-member caps are listed as a question still to qualify (lines 72–73).

### M3 (design choices left to the implementer): RESOLVED
Lines 113–122 now say the section is a direction, not a plan. They list the undecided choices and forbid building dormant machinery.

### Nits from review 1
- **N1:** fixed. The full path is used at line 91.
- **N2:** fixed. Cost and timeline are at lines 136–142.
- **N3:** carried as a follow-up candidate (lines 145–147).
- **N4:** fixed. Lines 82–84 match the text at create.md:110–118.

---

## New findings

### M4. Major: the historical `reconciled_expired` compatibility test has no stated expected behaviour
**Scope:** lines 29–32 and 41.

"Also cover historical reconciled_expired compatibility explicitly" does not say what the test should assert, which breaks the zero-decision rule. The unchanged code already does three things with such an entry:
- leaves it out of the admission sum (only `status=='reserved'` is summed, line 125–126);
- rejects a re-check of the same record with "completed reservation cannot be reused" (line 130–131);
- lets ordinary `--finish` overwrite its status to `finished` (lines 151–153 and 173–175), keeping `reconciled_at`.

The last point conflicts with the wording "not silently reclassified". **Fix:** state these three behaviours as the test's assertions. Say that `--finish` turning `reconciled_expired` into `finished` is intended, because it comes from a verified-deletion finish and `reconciled_at` survives. Otherwise, say why it is not intended.

### M5. Major: the deployment precondition inventories only `reconciled_expired` entries, not stale `reserved` holds
**Scope:** lines 25–32.

After this change, any `reserved` hold already in the live VM ledger whose `expires_at` has passed can no longer be released by idle inventory. If its launch has a `new.*.pending` file, or never reaches `guard_exit`, it is never released at all, and no manual release path exists. Non-batch Boat callers of `boat-spend` (`guard_init` → `--check`, for example `exam-launch`) are not behind the disabled holder gate (line 17). The deployed change can therefore permanently shrink available Boat admission.

That is acceptable fail-closed behaviour, but the pre-deployment inventory must also list the current `reserved` holds, their `expires_at`, and whether each launch has a pending-creation marker. The capacity impact can then be judged before rollout, not found as a pit stop afterwards. This is read-only parent work and needs no new code.

### Nits
- **N5.** Lines 37–38 should name all four passages in `isolation-timeouts.md` to supersede, so none is missed: item 6 (lines 112–114), the ledger-status schema (line 122–123), the TTL-backstop sentence at line 291, and lines 309–313.
- **N6.** Optional, to strengthen the test:
  - Assert that the fake CLI never receives `list --all` during `--check`. That proves the query itself is gone, not just the status change.
  - After the normal `--finish`, assert that the previously refused admission now succeeds. That proves the retained hold was the only thing blocking it.
- **N7.** The design should name its review file in the diff review's `Reviewed-by:` trailers, and the rename of this design's topic should not orphan `stream-b-delayed-creation-design-1.md`. This is bookkeeping only.

---

## Heilmeier and readiness check
- **Objective, current state, new approach, impact, risks, cost, timeline, exams:** all present. The objective (lines 7–17) is dense but understandable.
- **Target scope:** one code file (`bin/boat-spend`), one test (`tests/factory/test_isolation_timeouts.py`) and one doc (`docs/designs/isolation-timeouts.md`). Explicit and buildable in a single phase.
- **Test plan:** names the steps in order: admit, concurrent refusal, expire, empty complete inventory, refusal again in a fresh process, unchanged hold, normal finish. Plus the existing unknown-create regression. It runs on real saved receipts with authored crash timing, and says so. The only gap is M4.
- **Real-artifact rule:** met for local accounting. The design correctly says this proves neither live provider cleanup nor the USD 5 bound.

## Murphy rows
None closes, and none should. Rows 6, 27, 28, 35 and 51 and the open batch-service rows stay open. No register row cites the deleted path as its closing test. No live failure was observed, so no new row is needed.

## Readiness verdict
- **Design review: PASS.** No blocking finding is open. M4 and M5 should be fixed in the design before coding, or at the latest verified in the diff review: M4 decides the test's assertions, and M5 is a precondition for deployment, not for merging.
- **Implementation readiness of the deletion increment: READY** once M4's assertions are fixed.
- **Still blocked, and not closed by documentation:**
  - the cleanup supervisor and intent journal;
  - cumulative USD 5 admission, which needs the provider gaps a–f plus storage and per-member caps answered;
  - the b275 legacy disposition, which needs fresh VM provenance;
  - both activation gates, which stay false.

## Elephant response

Accepted M4/M5 and N5/N6. Historical compatibility assertions and deployment inventory are specified before implementation. All four old-design passages will be superseded; regression also proves no list query and admission after finish. No finding rejected. Fresh diff review will verify these changes. Both design review files remain under the original topic.
