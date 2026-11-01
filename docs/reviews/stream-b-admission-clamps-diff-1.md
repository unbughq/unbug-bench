## Verdict: FAIL. 1 blocker and 1 major are open.

The clamp logic is correct, and I found no way past the cap in the code as committed. The failure is about evidence and scope. The baseline-equality check and the history check both matter for safety, yet no committed test fails when either is removed. Separately, the "no schema means no change" claim is false for production manifests.

I worked read-only in a scratch export at `/tmp/gf-clamps`. The worktree is untouched: no edits, git changes, workers, network or paid calls.

### What I checked and what held
- **Targeted tests:** `test_batch_admission_clamps.py` passes on a fresh export (8 tests).
- **Suite record:** the compressed and uncompressed log SHA-256 hashes match the JSON. The source tree hash matches `72cd3d9^{tree}`. The log ends "169 test scripts run; 0 failed". `ea238f6` adds only the suite JSON, the log and the report section.
- **Replay ordering:** incidents and the aggregate are now checked before the replay `return`. If I remove that check, a test fails, so it is properly covered.
- **Child authority:** a $20 root template gives the child only $7.50. `channel` rejects an oversized persisted authority, and `r2` is refused at every entry (`_admit`, `authorize_locked`, `channel`, `check_manifest`).
- **Legacy path:** legacy `authorize` refuses practice manifests.
- **Carry continuity:** removing or changing `practice_admission` at a boundary refuses. Held authority must stay at or below S+E. Carried debit is kept through two releases.
- **Disclosures:** the queued-child money row is still built by the authored helper `derive()`, which calls `authorize_locked`. That is disclosed honestly in the test docstring and the report. The $20 refuse-not-lower limitation and the beta template retention are disclosed too.
- **Preflight:** the report records the stale-pin refusal (exit 1, "PINS STALE"). It does not rewrite pins. It lists the 7 frozen blocker groups and keeps live items (6) and (7) apart from this offline clamp. No Murphy rows are claimed closed, which is correct.

### Blocker
**B1. Two of the money-safety checks have no test that fails without them** (`factory/batch_transfer.py` `practice_check`, `factory/batch_holder.py` `_admit` history loop, `tests/factory/test_batch_admission_clamps.py`).

I ran two mutations against the committed suite. Both left all 8 tests passing:
- **M1:** deleting the first-entry check that S equals the authenticated `previous.total_usd` with no estimates.
  - The "mismatch" case in `test_first_entry_authenticates_baseline_and_keeps_authority` sets S=0 but leaves E at 1000−s. So held $1000 is already above the cap, and the held-vs-cap check refuses it before the baseline check matters.
  - The `read_import` "bad" check fails the same way.
  - The check really does matter. In my probe the real S was 52.79. A forged S of 992.50 with E of 7.50 is refused by the committed code. With M1 applied, `prepare` accepts it, which allows about $947 of new spend against an approved $7.50.
- **M2:** deleting the history refusal (`if name in receipt['snapshot']['money']['jobs']`).
  - In `test_two_releases…`, `k` is refused anyway because aggregate $2007.5 plus $1000 is over the $3000 limit.
  - My probe raised the limit to $9000. With the check, `k` is refused. With M2 applied, it is admitted fresh.

The design names "baseline mismatch" and "re-admission of an omitted historical name" as required exams. As written, those exams don't test either check.

**Fix (tests only):**
- In the mismatch case, change S while keeping S+E at least as large as held, e.g. S=s+1 and E=1000−s.
- Give the history test enough headroom that the money check alone would allow re-admitting `k`.

### Major
**M1. The clamp changes behaviour for production manifests that have no `practice_admission`** (`factory/batch_money.py`, `authorize_locked` clamp).

Without the schema, `allocation_cap` returns `money_limit_usd`. A template that asks for more than the batch limit is now cut down and granted. In my probe, a $5000 template in a $3000 batch was granted $3000. At `e2c2ea8` the same request was refused, because aggregate plus wanted exceeded the limit.

The batch cap is never exceeded, but this contradicts "absent schema retains current behavior" and "production chains unchanged". It also hands one job the whole batch, below what its template asked for.

**Fix:** clamp only when `'practice_admission' in record`, and add a no-schema test where the template exceeds the limit. `channel` is unaffected, because its no-schema cap equals the old limit check.

### Nits
- The `allocation_cap` call in `_admit` is redundant with `authorize_locked` and `channel`. The `r2` holder test passes without it. It is harmless as an early refusal.
- `test_exact_cumulative_cap…` puts carried debit into in-memory state rather than taking it from a real import. That is fine for arithmetic, but it should not be cited as carry evidence. The report doesn't cite it that way.
- One line in the report says "Full-suite record and fresh diff review follow", while the next section already records the suite. That is a small staleness.

### Remaining preflight blockers (unchanged and correctly recorded)
- Stale release pins (PINS STALE)
- B cleanup and lifecycle cost
- B2 baseline-S input authentication
- A's route maxima and shared paid cap
- E settlement and timing
- D/B live outcome and carry qualification, plus the queued-child creation path owned by the carry-over stream
- Account-2 attribution (item 6)
- Live launch/deletion evidence (item 7)
- Final pins review

`launch_ready` stays false.

To reproduce the mutations, run `/tmp/gf_probe.py` against `/tmp/gf-clamps`.

## Elephant disposition
B1 and M1 accepted. Baseline mismatch now keeps S+E above held, and the
historical-name test has ample aggregate headroom across both releases. Add a
no-schema oversized-template regression and restrict grant clamping to practice
manifests. The stale report sentence is corrected. No blocker is rejected;
closure requires a fresh goldfish review after the full-suite rerun.

