# Goldfish diff review: stream-b-admission-clamps, round 2 (Mode: REVIEW)

**Verdict: PASS.** There are no open blockers or majors. B1 and M1 from `docs/reviews/stream-b-admission-clamps-diff-1.md` are both fixed. Each check now has a test that fails when the check is removed. I re-ran both deletion mutations in a scratch copy to confirm this.

I read the two persona files (`zoom_out`, `implementation_readiness`), the readiness standard, `docs/ENGINEERING.md`, the design, design-1 review and diff-1 review. I also read the full code diff for `e2c2ea8..152694e`, the fix diff for `ea238f6..c3faf6f` and all of `tests/factory/test_batch_admission_clamps.py`. I worked read-only. The worktree is still clean at `152694e`, with no edits and no git changes. I ran no workers, network, paid calls or delegates.

## Suite record
- `docs/reports/stream-b-admission-clamps-suite-20261101T201211Z-bac41af7.json` names commit `c3faf6f0ef5b…`. I checked that commit's tree with `git rev-parse` and it is `60107507423d…`, which matches the record.
- The record reports 169 scripts, 0 failed, exit 0.
- The `.log.gz` SHA-256 is `9462a5a5…` and the decompressed log is `792d6be7…`. Both match the JSON. The log ends "169 test scripts run; 0 failed."
- `c3faf6f..152694e` adds only the JSON, the log and the "Review-fix validation" paragraph. That paragraph is accurate and says plainly that the earlier suite was for the first implementation, not for these fixes.

## Mutation results
I exported `c3faf6f` with `git archive` to `/tmp/gf2-clamps`. Without changes, 9 tests pass. I then applied each mutation in its own copy under `/tmp/gf2-mut/<key>` and re-ran the test file. The script is `/tmp/gf2-probe/mutate.py`.

| Mutation | Result | Failing assertion |
|---|---|---|
| M1: delete first-entry `estimated=={}` and `total_usd==baseline_usd` in `practice_check` | **FAIL** (killed) | line 182: `prepare` mismatch is no longer refused |
| M1b: drop the `practice_check` call only in `read_import` | **FAIL** (killed) | line 191: `read_import(bad)` is no longer refused |
| M2: delete the history refusal in the `_admit` receipt loop | **FAIL** (killed) | line 214: `check_refusal(..., 'k')` now finds `k` eligible |
| M3: revert to an unconditional `authorize_locked` clamp (the pre-fix behaviour) | **FAIL** (killed) | line 84: the production $5000 template is granted instead of refused |
| M4: remove the clamp entirely (sanity check) | **FAIL** (killed) | child $7.50 tests fail |
| M5: delete `_admit`'s fresh nonzero-S refusal | survives | see nit 1 |

## B1: fixed
- **Baseline check.** The mismatch case now uses S = s + $1 and E = 1000 − s. That puts S+E at $1001, above the $1000 held, so the held-versus-cap check passes and only the baseline-equality check can refuse it. M1 confirms that this check alone is what refuses it.
- **`read_import` path.** The `bad` record now uses the same S = s + $1 shape. M1b shows that this assertion independently covers the persisted-import path, which round 1 did not.
- **History check.** With the limit raised to $9000, admitting `k` fits the aggregate cap. The new `assertLess` at lines 212-213 records that fact. M2 confirms the history loop is what refuses `k`.

## M1: fixed
- `authorize_locked` now clamps only when `'practice_admission' in record` (`factory/batch_money.py:335`).
- Without the schema, `allocation_cap` returns `money_limit_usd`, so `channel` behaves exactly as it did at `e2c2ea8`.
- The new test (`test_production_oversized_template_refuses_without_partial_grant`) shows a $5000 template in a $3000 batch is refused with no state change. It also shows that `reserve` and the qualifier refuse without writing any bytes. M3 kills it.
- Line 76 still checks that a no-schema `-r2` inherits its $20 template. Production chains are therefore unchanged except for the replay ordering the design requires (see nit 2).

## Scope
- `c3faf6f` touches only the three-line guard in `batch_money.py`, the test file, the report and the diff-1 review. There is no new module, ledger or path.
- The whole range still matches the design:
  - the child gets its own S+E;
  - the cumulative aggregate includes carried history;
  - the allowlist is optional, allocations cannot change, and baselines are authenticated;
  - legacy `authorize` refuses practice manifests.
- The required disclosures are all still present and accurate:
  - an old $20 commitment above S+E refuses;
  - the queued-child money-only state is built by test code (`derive()`), so it is arithmetic evidence only and the production creation path remains a carry-over-stream gap (test docstring and report);
  - no Murphy rows are closed;
  - stale pins and the live preflight blockers stay in `docs/reports/stream-b-admission-clamps.md`.

## Blockers
None.

## Majors
None.

## Nits (optional)
1. **M5 survives.** The fresh nonzero-S refusal in `_admit` (`factory/batch_holder.py`, under `source_generation is None`) is defence in depth, not a reachable gap:
   - `check_manifest` already rejects nonzero S when there is no `carry_from`;
   - at first entry, `practice_check` requires S = 0 for any job that is not carried or is a carried never-launched child;
   - later boundaries freeze the allocation object;
   - a historically carried name that later loses its `carry_from` entry is caught by the history rule.

   The design's "refuse nonzero fresh child S" exam is covered at manifest level (`test_manifest_rejects…`, last change). Either add a direct `_admit` assertion or treat the guard as redundant and delete it.
2. **Replay ordering for all manifests.** The incidents and aggregate checks now run before the replay `return`, with or without `practice_admission`. So a production replay after a cumulative overrun now refuses where it used to return. The design asks for this ("Replay … cannot report admission after cumulative overrun"), and the full suite passes. Still, the report should state it as the one deliberate production behaviour change, so that "production chains unchanged" is not read too literally.
3. **Leftover from round 1.** The `allocation_cap` call in `_admit` is still redundant with `authorize_locked` and `channel`. It is harmless as an early refusal.

Scratch artifacts are in `/tmp/gf2-clamps`, `/tmp/gf2-mut/` and `/tmp/gf2-probe/`. None of them are in the worktree.

## Elephant disposition
PASS accepted. B1 and M1 are independently closed by this fresh Claude review,
including scratch deletion mutations and the production regression mutation.
Nit 2 is clarified in the report: replay after incidents or cumulative overrun
now refuses for all manifests, the deliberate production behavior change.
Optional redundant early checks (nits 1 and 3) are retained; no runtime changes
follow this review. No Murphy rows closed and no live qualification claimed.

