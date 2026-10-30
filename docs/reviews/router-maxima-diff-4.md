# router-maxima diff review 4: cross-family goldfish, zoom-out and readiness

**Verdict: PASS.** 0 Blockers, 0 Majors, 2 Nits. Diff-3's M1, N1 and N2 are all fixed in the documentation only. The full suite passed on the frozen implementation, so this pass is not conditional on anything pending.

**Scope:** HEAD `9e9145f3713df6dc9c51a2b305432e4dceae0828`, implementation and tests `0a91d8abb7fee8c275af50ae641ab8ff94418c2b`, integrated base `6abe1690d2cc65078a64b347d923cd0aba6be655`. I read files only. I edited nothing, compiled nothing, ran no tests and made no provider or case calls.

## Source equivalence (checked myself)

- **No code changed after the freeze.** `git diff --name-only 0a91d8a HEAD -- factory tests bin tools` is empty, and `git diff --name-only 0a91d8a HEAD -- . ':!docs'` is empty too.
- **Only four docs changed after the freeze:**
  - `docs/designs/interfaces.md` (§7, +10 lines)
  - `docs/designs/router.md` (integration section, +17 lines)
  - `docs/reviews/router-maxima-validation.md` (+11 lines)
  - `docs/reviews/router-maxima-diff-3.md` (new review record)
- **The base is an ancestor.** `git merge-base HEAD 6abe169` is `6abe169`, so the rebase stands.
- **Tests do not read these docs.** No file in factory, tests, bin or tools references `docs/designs` or `docs/reviews`. A docs-only change therefore cannot change any test result.

## Full-suite validation (checked myself)

- **Result:** `/tmp/router-maxima-full-0a91d8a.json` records exit_code 0, command `uv run --with numpy --with scipy python -B tests/run.py`, tested_sha `0a91d8abb7fee8c275af50ae641ab8ff94418c2b`, integration_base `6abe169`, started 2026-10-30T02:45:16.984398Z, finished 03:01:42.286237Z.
- **Log:** it ends with `139 test scripts run; 0 failed.` A grep for FAIL, ERROR or Traceback finds nothing.
- **Archived copies:** `docs/reviews/router-maxima-full-0a91d8a.log.gz` decompresses to SHA-256 `6e4ce934…f8d2fe`, which matches the live log and the `log_sha256` field. The `.gz` file hashes to `27c0ec41…0b31`, which matches `archived_log_sha256`. The archival JSON also records script_count 139 and failed_scripts 0.
- **Interrupted runs stay labelled as interrupted:**
  - fcc0030: 1 failure; only a test was corrected afterwards.
  - de33c1b: interrupted.
  - d6e1f80: `interrupted_superseded`, exit 130.

  None of them is relabelled as a pass.
- **Validation doc:** the append matches the metadata above, and it keeps rotation packages unqualified and B's practice exam required.

## Diff-3 findings

### M1: one $50 call uses up the whole default $50 commitment — FIXED

All three places diff-3 asked for are covered: router.md's integration section, interfaces §7 and the validation doc. I checked each claim against `factory/budget.py`:

- **"From zero spend, one invocation fits; after any positive charge, another does not."** `reserve_invocation` refuses with `money_wait` when `usd(total) + pending + maximum > limit` (budget.py:159-160).
  - From zero: 0 + 0 + 50 ≤ 50, so the first call is admitted.
  - After a settled charge x > 0: x + 50 > 50, so the next call is refused.
  - While the first call is still pending: `outstanding_reservations` adds 50 − booked, so the total stays at 50 and a second call is refused.

  The router.md example ("$3+$50 authority … money_wait at a $50 commitment") is correct. "That invocation may itself contain many provider requests" is correct and needed, because one CLI invocation is one reservation.
- **"Ordinary writer diagnosis."** This matches D's design rule `spent_usd + next_writer_invocation_max > ordinary_limit_usd` (stream-d.md:65-71). Saying "ordinary" correctly leaves out the bypass inside an active extension. This rule is still D2 design: `next_writer`/`ordinary_limit` appears nowhere in `factory/*.py`. The docs frame it as an enablement prerequisite, not as current behaviour, so nothing is overclaimed.
- **"Two concurrent nested owners need $100 plus settled usage."** Correct: each reserves 50.
- **Handoff.** The prerequisite is owned by founder, D and B. They either size commitments and revisions to settled + outstanding + new maxima, or approve a lower route profile against the 153-receipt fit table, before D2 is enabled. The docs state that A chooses neither, and say "First-call success is not package availability." No cap, authority, budget or route profile changed, which `git diff` confirms.

### N1: D2 must reserve the exact route-owned Lease maximum — FIXED

The docs require exactly the `valid_lease`-checked `lease.max_usd`, rounded upward to nine places, and never a smaller amount chosen by the caller. The rounding matches `quantize(Decimal('.000000001'), rounding=ROUND_CEILING)` at budget.py:146. `reserve_invocation` still takes `maximum_usd` as a parameter and does not compare it to `lease.max_usd`. The docs correctly make that comparison a D2 wiring duty; this slice does not claim to enforce it.

### N2: D ignores `cap_used` when settling unknown usage — FIXED

The docs match `_settle_leaf` (budget.py:232-234). The estimated gap is `maximum_usd − booked` when `final_usage_known` is false. `cap_used` and the gate's held W are never read.

### Earlier reviews

- design-2 to design-4 and diff-1/diff-2: their dispositions stand unchanged. Diff-2's code PASS applied to the old d6 base and was superseded by the integration rebase.
- Diff-3's code and integration verification (byte-identical D/B files, preserved B section 8, the authority contract test, the 10-probe native matrix) has nothing new to recheck, because no source changed after `0a91d8a`.
- Murphy rows 2, 3, 4, 20, 47 and 48 are still `open` in `docs/murphy-register.md`, and nothing claims to close them.
- No finding has been rejected.

## Nits (optional)

1. **`docs/designs/interfaces.md` §7, first sentence of the new paragraph.** "only one separately reserved invocation fits from zero spend once positively charged" is ambiguous: "once positively charged" can attach to the wrong noun. router.md says the same thing clearly. Suggested wording: "from zero spend only one such invocation fits; after it records any positive charge, a further one cannot."
2. **Uncommitted review records.** At review time three files are uncommitted on top of frozen HEAD `9e9145f`:
   - `docs/reviews/router-maxima-validation.md` (modified: the full-suite append)
   - `docs/reviews/router-maxima-full-0a91d8a.log.gz` (untracked)
   - `docs/reviews/router-maxima-full-0a91d8a.json` (untracked)

   I verified their content above. Commit them together with this review as `router-maxima-diff-4.md`, and list every review file in the `Reviewed-by:` trailers, as ENGINEERING.md requires. Do not merge or push without the founder.

## Handoff

Code and docs PASS, and the full suite is green on `0a91d8a`. D2 enablement is blocked until founder, D and B either size authority to settled + outstanding + new maxima, or approve a lower route profile. B's real practice-case qualification is still a separate, later authorization.

## Author response

PASS accepted. No blocking finding remains; none was rejected. Optional N1 uses the reviewer's suggested clearer wording in interfaces §7. N2 is fulfilled by committing the complete terminal log, hash metadata, validation append and this verbatim review together, with all eight review-record paths in Reviewed-by trailers. No merge or push.

Final validation: required command uv run --with numpy --with scipy python -B tests/run.py completed at 2026-10-30T03:01:42.286237Z, exit0, 139 scripts and 0 failures, tested implementation 0a91d8abb7fee8c275af50ae641ab8ff94418c2b, integrated base 6abe1690d2cc65078a64b347d923cd0aba6be655. Log and SHA256 metadata are router-maxima-full-0a91d8a.log.gz and router-maxima-full-0a91d8a.json. All subsequent changes are docs/review/evidence only; factory/tests/bin/tools remain byte-identical to the tested implementation. D2 sizing/profile enablement and B's later real practice qualification remain prerequisites, not completed production claims. Murphy rows 2,3,4,20,47,48 remain OPEN.
