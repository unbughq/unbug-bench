Code passes for this increment. The new contract text fails on one blocker: the queue hook can deadlock and has no path to settle an exhausted owner. The full suite was still running when I checked: 7 of about 138 scripts had started and none had failed. That is not a pass yet.

# Goldfish review: batch-service increment2, `9b1fcef..03b8455`

## Code verdict: PASS (pending the full suite)

**Import boundary (the earlier blocker): fixed.**
- `factory/job_config.py:42`: `from budget import BudgetError` now sits inside the worker-only `install()`, so the host `check`/`deliver` path no longer loads `budget.py`.
- I checked the full set of modules, not just this one import. In an isolated interpreter (`python3 -B -I`), `import job_config` loads only `factory/` modules `batch_money`, `job_config`, `launch_manifest` and `registry`. All four are in `launch_manifest.TRUSTED_FILES`, so nothing unpinned is loaded.
- `batch_money` imports `batch` lazily inside a function, and `batch` is pinned. `job_authority` is still imported only inside `install()`.
- The regression test `test_host_job_config_does_not_load_worker_accounting` starts a fresh process with `-B`. It fails if `budget` or `job_authority` comes back as a top-level import.
- Nit, not blocking: the test does not use `-I`, so the current directory and environment can affect `sys.path`. It still catches the regression, since a top-level import would put `budget` into `sys.modules`.
- Nit, not blocking: the stronger check would be that every loaded module is in `TRUSTED_FILES`. That is the one-line check I ran above, rather than naming two modules that must be absent.

**Worker inventory test: fixed correctly.**
- `tests/tools/test_launch_manifest.py`: the three intentional new B files are listed one by one (`batch_money.py`, `job_config.py`, `control-recipient.txt`). Batch manifests are added by globbing `factory/batches/*.json`. That matches the manifest's batch-JSON globs.
- The expected set is still built independently from the release inventory, so an unexpected stray file would still fail the test.

**Everything else** is as `docs/reviews/batch-service-diff-3.md` reported. HEAD makes no other code changes. Zero Murphy rows are closed, which is correct.

**Full suite:** `/tmp/unbug-batch-increment2-final-tests.log` was at `tests/bench/test-launch-guards.py`, 7 scripts in, with no `FAIL` lines. This verdict depends on that run finishing green.

## New contract verdict: FAIL, one blocker with a small fix

### Blocker: the queue hook can deadlock, and an exhausted owner has no way to settle
- **Where:** the Increment2b scheduling hook for D (`batch-service.md` §"Increment2b scheduling hook for D", around lines 764–793), read together with interfaces §8 "Conservative resume".
- **What goes wrong:**
  1. A replacement is blocked while the original owner's total is unknown, and the unknown total clears only through `settle()`.
  2. `settle()` runs only when the original owner resumes.
  3. The text never says which class a same-owner settle resume belongs to. "Ordinary work follows these three classes" and "Blocked requests retain their position" allow a head-of-line reading. Under that reading, the blocked replacement sits ahead of the resume that would unblock it, so neither ever runs.
  4. Separately, for a rounds/money exhaustion projection with unknown usage, nothing is defined to run `settle()` at all. Diagnosis and extension are barred while usage is unknown, and the exhausted original is not otherwise resumed. The replacement for that case therefore stays blocked forever.
- **Minimal fix, two sentences:**
  - Add: "A same-owner, same-revision settle resume (conservative resume per interfaces §8; for an exhausted owner, settle-only, with no model invocation, then checkpoint and collect) is admitted ahead of all three classes."
  - Add: "A request blocked on money or an unknown total keeps its place but does not block later eligible requests."
- This does not reopen the parent policy. It only states an ordering the policy already implies.

### Checked, no finding
- **Same-revision conservative resume:**
  - It applies only to the same owner at the same revision, with a commitment the same or lower.
  - Every unknown part must map to an unpriced invocation or `wait_id` with an admitted maximum, and the coverage must fit the held commitment.
  - The full old commitment stays held and is counted once. Other owners can use only their existing headroom, so no authority moves between owners.
  - Until the total is known, new admission, increases, old+1, replacement, diagnosis and extension are all blocked.
  - Settle runs first on resume. The RAM channel and the checkpoint advance before D's equality check, so the exact channel stays consistent with the RAM config.
  - I found no unintended authority here.
- **Exception scope:**
  - Same-source replay must stay byte-equal (interfaces §8 at line 440, and batch-service at line 727).
  - The source rebind is the only stated exception, and it is labelled planned 2b.
  - 2b history is keyed by reservation, revision and source.
  - Increment2 still refuses every source change and claims no enablement.
- **Receipt-backed decrease (e.g. $10 to $8):**
  - It requires an authenticated D receipt that matches an existing unpriced invocation ID or `wait_id`.
  - B records an idempotent `reconciled_decrease` acknowledgment with that ID, the old and new totals, the generation and the receipt digest.
  - The new total replaces the old one, with no refund event. An unbacked decrease refuses. Release still needs terminal collection plus retirement.
  - This does not contradict the "amount does not decrease" rule, which governs commitment revisions, not collected totals.
- **Qualification requirements:** they include null-total collect → retire → same-revision resume → settle → finish, plus the late-receipt decrease and its refusal without a receipt. Fault injections that we author must be labelled as such. These are required before enablement, not in this increment.
- **Queue rules, apart from the blocker:**
  - One queue and launcher.
  - Replacement first, only when there was at least one real invocation. A denied reservation counts as zero and gets no replacement; a zero-cash subscription invocation still counts.
  - At most one replacement per original, even across replays.
  - Diagnosis and extension use the original owner.
  - Extension reaches old+1 only when D projects close_to_passing and D's code accepts count, package and progress eligibility.
  - FIFO within each class. The request kinds stay disabled until D's adapter and acceptance tests pass.
  - All of this is consistent with the parent policy.
- **Nit, not blocking:** a repeated covered-wait rebind should state that the rebind starts from the current persisted source and lands on a newer acknowledged generation, so a stale A→B→A rebind refuses. It is implied by "exact restored generation" plus ordered collection ACKs, but it is not written down.

### Out of scope, as you asked
Holder async and restore, Codex, journal and outbox, the actual same-revision resume implementation, and the live practice run all stay later work.

## Summary
- **Code: PASS**, provided the full suite finishes green.
- **New contract: FAIL** on one blocker: no ordering or path for the settle resume, which allows a deadlock and leaves exhausted owners unable to settle. The fix is two sentences, and a goldfish re-check of that paragraph is enough.

I made no edits and ran no state-changing commands.

---

Elephant response: Fixed the blocker by placing covered same-revision settlement resumes ahead of replacement/diagnosis/extension; an exhausted owner resumes settlement-only, with no model call, then checkpoints/collects. Blocked requests retain FIFO position without preventing later eligible work. Also made source advancement monotonic against the current persisted source and ordered collection history; stale A→B→A refuses. Code PASS is retained; the full suite must still finish. No findings rejected and no Murphy rows closed.

