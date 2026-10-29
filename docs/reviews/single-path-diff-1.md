# Goldfish diff review 1: single launch path slice

Reviewer: fresh Claude Opus 5.5 (T3 delegated, clean room, read-only), personas zoom_out + implementation_readiness, Mode: REVIEW. The writer was Codex gpt-6.1-sol, so the reviewer is from a different model family.

**Result: FAIL**, on 2 blocking findings. Full suite: 131 scripts, 0 failures.

1. **BLOCKING, `factory/launch.sh:634`.** The checkpoint upload runs under boat-call's default 120 s timeout. Real checkpoints are 278–528 MB, so real resumes will time out. The test fakes never check this timeout.
2. **BLOCKING, `factory/launch.sh:181-183`.** The plaintext fallback is removed for every `--restore`. 30 of the 43 checkpoints in `sealed/` have no `.casekey.age`, so they become unrestorable. This is a security-property change that was never signed off.
3. **NIT, `run_artifacts.py:98-103`.** A `case_recipient` failure is swallowed for non-batch runs. Dry runs now generate keys.
4. **NIT, `batch.py:78-82`.** `launcher_sha256` duplicates the fingerprint and nothing reads it.
5. **NIT, `test_batch_launch.py:269`.** The replay test doesn't assert which error was raised.
6. **NIT, `test_batch_launch.py:41-52`.** The test proves usage is not reset, but not that it accumulates.
7. **NIT, `key_holder.py:289-311`.** `lifecycle_complete` adds a third "done" state.
8. **NIT, `batch.py:106-120`.** `prepare` unpacks and re-gzips the bundle.
9. **NIT, `factory-single-path.md`.** Contains stale process text. The change isn't on its own branch.

(Condensed by the elephant from the reviewer's verbatim report. The full text is in the T3 review task "Goldfish diff review: single launch path slice".)

## Elephant resolution

- **Finding 2:** the hard casekey requirement is limited to batch jobs. Legacy checkpoints keep their path until stream B migrates them with the approved scoped VM restore key (founder rules: salvage finished work; proportionate security).
- **Finding 1, plus nits 3–6 and 9:** sent to the slice author to fix on branch `slice/single-path`.
- **Nits 7–8:** fix if each takes under about 30 lines, otherwise list as a follow-up.

## Slice author response

The slice is on `slice/single-path`, cut from `factory-simplify` at `4a10966`.

1. **Fixed.** Wrapped checkpoints use worker-side R2 ciphertext download when signing is available. Local ciphertext upload, R2 download and legacy streaming use an explicit size-scaled timeout. The real largest local checkpoint is 527,987,760 bytes; the executable transport test checks its 2,017-second bound rather than the 120-second boat default. No real archive is decrypted by this qualification.
2. **Fixed.** Only batch restores require a wrapped case key. Legacy unwrapped checkpoints retain the original streaming path until stream B migrates them using the approved scoped VM key. The read-only real inventory test covers all 43 checkpoints, including all 30 without casekeys. The existing public audit fixture also executes the legacy path. The design documents the exception and migration boundary and no longer requests this authority again.
3. **Fixed.** A batch case-key failure raises. Dry runs again bypass `case_recipient`; a sealing regression checks both behaviors and that no archive is published on failure.
4. **Fixed.** Deleted the unused `launcher_sha256` record field and its duplicate digest computation. The complete batch release digest remains the approval identity.
5. **Fixed.** Checkpoint replay has a specific public refusal, `checkpoint already used; reconcile before retrying`. The public integration test asserts it for fresh, resumed and post-service-restart replay.
6. **Fixed.** Each public resume appends a distinct, priced event from the real saved e15450 card to the retained c7d405 ledger. The test checks cumulative calls, cost and event prefix across both resumes and the second service's reservation budget.
7. **Fixed within the small-change bound.** Durable controller completion reconciles to the existing `completed_ok` state. Deleted the `lifecycle_complete` flag and admission exceptions. Reservation generations stay consumed, and no process exit code is invented.
8. **Fixed within the small-change bound.** The existing deployment adapter accepts a batch record and writes it in its initial archive pass. Deleted the unpack/re-gzip pass from `batch.prepare`; refreshed the adapter's shared helper pin.
9. **Fixed.** Removed uncommitted/shared-checkout process status and obsolete approval-request text from the design. The branch owns the slice; EXAM.md and its README link remain outside it.

Focused validation passed: real restore inventory (3 tests), public batch integration (2 tests), public restore guard checks, sealing/resume (5 tests), and deployment adapter (21 tests). These responses are not a passing Goldfish verdict; a fresh branch diff review is still required.

Full validation: `uv run --with numpy --with scipy python -B tests/run.py` — **132 scripts, 0 failures**. Local ignored log: `results/infrastructure/2026-10-29-single-path-review-fixes/full-suite.log`. No real holder, worker or case was launched; real ciphertext qualification read metadata and sizes only. EXAM.md and its README link are excluded from the slice commit.
