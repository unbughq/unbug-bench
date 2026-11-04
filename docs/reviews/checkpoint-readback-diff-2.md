# Goldfish diff review: `claude/murphy-immutable-checkpoints` @ 6417147 vs `factory-simplify` fbca505

Both personas ran in Mode: REVIEW. The readiness persona used `implementation-readiness-standard.md`. Persona grades map as Blocker = BLOCKING, Major = NON-BLOCKING, Nit = NIT.

**I did not run the tests.** Every test command needed approval in this session, and the persona is read-only. Everything below comes from reading the code at 6417147. It does not replace the full-suite run ENGINEERING §1 step 4 requires on this head.

## What I checked and found correct

**Earlier dispositions marked fixed are really fixed**
- **design-1 B1, the resume guard.** The guard is at `factory/resume-in-place.sh:34`, on its own line, before `rm -rf ~/factory` at `:35`. Test T6 is at `test_checkpoint_readback.py:239-254`.
- **design-1 B3, the T3 assertion.** T3 now asserts there is no `r2_object` in the receipt, and that the card's top-level fields are restored to the e15450 values (`:218-221`).
- **design-1 `local_durable` and `case_key` findings.** `revoke_replaced` (`run_artifacts.py:35-49`) clears both flags. It is called at `:118`, before the `case_key` work at `:126`.
- **design-2 NB1.** `work/durable-checkpoint.json` is rewritten (`run_artifacts.py:43-48`). T1 asserts the file and the copy sealed inside the archive (`:156-159`).
- **diff-1 NON-BLOCKING (stall and oversize untested).** T3b is at `:227-236`. In `flood` mode it can tell the early cut-off apart from the timeout: with `seen > size` removed, the read blocks until curl's 25 s `--max-time`, which fails the `< 10` check.
- **diff-1 nits.**
  - `test_r2_upload.py:55-58` now has a PUT-only case and a dead-PUT case.
  - The module docstring now names the authored `durable-checkpoint.json`.
  - The design's `~/factory.tgz` wording is corrected (`:171-173`).

**No other code path depends on `upload` returning a key after a PUT-only success**
- The only production caller is `run_artifacts.py:145`.
- Everything else either patches `upload` (`test_startup_smoke.py:188`, `test_practice_startup.py:76`, `test_resume.py:232`) or only reads `r2_object` from saved cards.
- `launch.sh:741` and `:175` and `restore_bundle.py:92` read the key the card names, and check its digest on restore.

**Scope**
- Code changes are limited to the design's five files: `durable_checkpoint.py`, `launch.sh`, `r2_upload.py`, `resume-in-place.sh` and `run_artifacts.py`.
- The other changes are the new test, `test_r2_upload.py`, and the design and review docs.
- Nothing touches budgets, ledgers, model routes or keys. The only "ledger" is a temporary test file the design lists (`test_checkpoint_readback.py:119`).
- `docs/murphy-register.md` is not edited, as the design and the second goldfish agreed.

**Phasing.** All five code changes land in one commit, 3b0ccd3, as the design requires.

**The tests prove what the proposed row and the design claim**
- **T1 closes `new-checkpoint-readback-1` honestly.**
  - It uses the real e15450 receipt (`460a8f21…` at `vm/bx_gdt298d7`) and the real `seal`, `tar` and `age`.
  - The archive's own `scorecard.json` and `durable-checkpoint.json` carry the revoked receipt. That proves the revocation came before the archive was written and before the PUT.
  - The revocation goes through the key condition alone, so it does not depend on how faithful the HTTP double is.
  - T1c covers the local-path condition.
- **T2 and T3 prove the version 2 claim.** `remote_durable: true` is set only after a byte-exact read-back.
- **Row 34 correctly stays open.** The double is authored, and facts 2 and 4 are not addressed for live workers.

**`resume-in-place.sh` fixture hash.** The fixture `tests/factory/fixtures/preflight-deployment-release` pins the base hash of `r2_upload.py`. `test_preflight.py:101-102` already expects the retained release to differ from the host, so the changed file breaks nothing there.

## 1. Zoom Out (Skeptical Architect)

**NIT: the proposed row cites line numbers from the base commit.** The row text (design `:323`) cites `run_artifacts.py:124` and `:128`. On fbca505 those are `staged.replace(out)` and the `upload` call. At head they are `:141` and `:145`, and the fix itself is at `:118`. The integrator pastes this row at merge, so the numbers will already be wrong. Cite head lines or the symbol names (`RunArtifacts.seal`, `revoke_replaced`).

**Positive:**
- The diff matches the design's scope and adds nothing speculative.
- The only new helpers are `_links`, `target` and `revoke_replaced`, and `revoke_replaced` states when it should be deleted.
- No reuse was missed. `batch_holder.r2_publish` stays controller-only, for the reason given in the design. `hashlib.file_digest` follows the existing use in `restore_bundle.py`.

## 2. Implementation Readiness

**NIT: T3b holds up teardown for about 30 s.**
- Both `stall` and `flood` handlers end in `time.sleep(30)` (`test_checkpoint_readback.py:66-72`).
- `tearDown` calls `server_close()` (`:124`). `ThreadingMixIn.server_close` joins every handler thread, daemon threads included, while `block_on_close` is True (`/usr/lib/python3.12/socketserver.py:700-710`).
- The test still passes, but each run takes about 30 s longer and holds a shared `TEST_SLOTS` slot for that time.
- Fix: set `block_on_close = False` on `Store`, or make the sleep wait on an event that `tearDown` sets.

**NIT: T3b's comment claims slightly more than the test proves.**
- The comment at `:229-230` says `flood` "proves the early size cut-off and kill".
- The mutation the elephant checked removes only `seen > size`. If the `finally: p.kill()` at `r2_upload.py:68` were removed, curl would most likely still exit at once on EPIPE when `Popen.__exit__` closes the pipe. So the timing cannot tell whether the kill ran.
- The size cut-off is also checked once per 1 MiB block (`r2_upload.py:60-62`). A small overrun followed by a stall ends only at the timeout. The design's "stops as soon as it receives more bytes" (`:82`) is true only to within one block.
- Both cases fail closed, so this is wording only.

**NIT: the design's test section no longer matches the tests.**
- Design `:291-294` still says `test_r2_upload.py` "pass[es] unchanged". 6417147 changed it.
- The design's test list (`:232-289`) does not mention T3b. It is recorded only in the diff-1 dispositions.

**NIT: `revoke_replaced` rewrites the work file under a condition the design doesn't state.**
- It rewrites `work/durable-checkpoint.json` only when the file's `sha256` equals the receipt's (`run_artifacts.py:46`). The design says only "(if it exists)" (`:136-137`).
- This is the safer choice, and in normal operation `checkpoint_progress` keeps the two in step. The design should say so.

**NIT: the new `test_r2_upload.py` case can't show which step failed.**
- At `:56-58` both the PUT and GET links point at `127.0.0.1:9`, so the result is `None` whether the PUT or the GET fails.
- The nit is fixed as the elephant described it. The precise failed-PUT proof remains T3 `put500`.

## Overall verdict: **PASS**

There are no blocking or non-blocking findings. Every disposition marked fixed in design-1, design-2 and diff-1 is present in the code and tests. T1 proves exactly the proposed `new-checkpoint-readback-1` row and no more, and row 34 correctly stays open. All remaining items are nits.

The full suite on 6417147 still has to be run (ENGINEERING §1 step 4). I could not run any tests in this session.

---

## Elephant dispositions (recorded after the verbatim review above)

The reviewer was a fresh `claude -p` process with read-only `Read,Grep,Glob`
tools.

**Verdict: PASS.** There are no blocking or non-blocking findings. The
following nits were applied in the commit after 6417147. That commit touches
only tests and docs; no factory code changed.
- **Row line numbers.** The proposed row now cites `RunArtifacts.seal` and
  `revoke_replaced` by symbol, not by base line numbers.
- **T3b teardown.** `Store.block_on_close = False`, so the sleeping handlers
  never hold up teardown or a shared slot.
- **T3b comment.** It now claims only that the per-block size cut-off ended
  the read, and says that kill versus EPIPE is not distinguished.
- **Design test section.** It now records T3b and the changed
  `test_r2_upload.py`.
- **Design wording.** It now states the `sha256` condition on rewriting
  `work/durable-checkpoint.json`.
- **`test_r2_upload.py` dead-endpoint case cannot say which step failed:
  accepted as is.** T3 `put500` remains the precise failed-PUT proof, as the
  reviewer notes.

The full offline suite was run on the final head after these nit fixes. The
result is recorded in the PR body.
