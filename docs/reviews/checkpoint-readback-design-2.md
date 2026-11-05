# Goldfish design review 2: `docs/designs/checkpoint-readback.md` @ 5c75123

**Verdict: PASS.** There are no blocking findings. On B2, I agree with the rejection.

I applied the three personas in `Mode: REVIEW`. Their Blocker/Major/Nit grades map to BLOCKING/NON-BLOCKING/NIT here. The design was checked against `heilmeier-standard.md` and the readiness persona against `implementation-readiness-standard.md`. The review is read-only and I wrote no files, so the elephant still needs to save it as `docs/reviews/checkpoint-readback-design-2.md`.

## Claims checked against the code

All of these are accurate:
- **PUT-only success:** `r2_upload.py:41-44`.
- **Seal:** `staged.replace(out)` is at `run_artifacts.py:124`. The `r2_object` pop and set are at `:127-128`, and the scorecard is written at `:101`, before `out` is computed at `:102`.
- **Receipt replacement and restore:** `durable_checkpoint.py:26-30, 49-50`.
- **The two barriers:** `run.py:233` (raising at `stress_progress.py:39`) and `extension_evaluator.py:437`. They are the only decision readers of `remote_durable`.
- **Launcher:** PUT-only links are presigned at `launch.sh:780-782`. The in-place restart runs the worker's installed `~/factory/run.py` (`launch.sh:640`). The restore reads the card's `r2_object` and checks its digest (`launch.sh:741, 175-183`).
- **Key binding:** `restore_bundle.py:92` binds the literal key.
- **Resume in place:** `resume-in-place.sh:27-34` copies `factory/` and never rewrites `~/.factory-r2`. Every in-place entry goes through it: `account_handoff.py:210` and `bin/factory-adopt:48`.
- **Controller publication:** `r2_publish` does a PUT, then a streamed GET with a size cap, a 1800 s bound and a digest check (`batch_holder.py:808-826`).
- **batch-service.md:** `:205` and `:214-215` say what the design quotes.
- **Fact 3 in the real card:** the receipt names `460a8f21…` (`e15450-collected-card.json:167-175`). The card's own fields name `03a1dd51…` at the same path and key (`:9229-9231`).
- **Existing tests still pass:**
  - `test_r2_upload.py:54-55` uses links with no `checkpoint_get`, so `upload` still returns `None`.
  - `test_durable_checkpoint.py` stubs `seal` and does not assert `version`.

## Design-1 findings marked fixed

| Finding | Status in revision 2 |
|---|---|
| B1: mixed versions via resume-in-place | **Fixed.** Change 5 (`:140-156`) adds the guard, and T6 tests it. No other path copies code onto a live VM: the only other `~/factory` writer is the fresh launch at `launch.sh:682-683`. |
| B3: T3 assertion | **Fixed.** The design (`:236-243`) now asserts that the receipt has no `r2_object` and that the card's top-level fields are restored. |
| Reuse of `r2_publish` | **Justified** (`:95-100`). |
| Revocation placement and when it is deleted | **Fixed** (`:124-132`). |
| `local_durable` also stale | **Fixed** (`:121`). |
| Revocation depended on `case_key` | **Fixed** (`:116-119`). |
| GET process handling | **Fixed** (`:85-91`). See the readiness nit about the 600 s seal deadline. |
| Retirement-reserve estimate | **Added** (`:316-319`). Its consequence is not drawn out; see Design Critic NB2. |
| T1 setup | **Mostly fixed.** Small gaps remain; see the readiness nit. |
| Heilmeier gaps | **The objective and effort estimate are fixed.** The timeline is still missing (NIT). |
| Earlier nits | **Fixed:** the "What it deletes" section, the `:741` wording, the attribution of the consistency claim, T4's extraction method, and the existing-tests list. |

---

## 1. Zoom Out (Skeptical Architect)

**NON-BLOCKING: an alternative with no extra transfer was not considered.**
- **Scope:** Change §1 and Risks (`:314-319`).
- **Issue:** the read-back doubles transfer time on the stop seal (`run.py:3505`), which sits inside an already tight reserve (row 16).
- **Possible alternative:** send `Content-MD5` or `x-amz-checksum-sha256` on the PUT, so R2 rejects any body that doesn't match. This verifies the bytes on the server with no second transfer.
- **Caveat:** I have not verified that R2 accepts these headers on a SigV4 presigned PUT when they aren't signed.
- **Recommendation:** in one sentence, say why the design rejects this, or adopt it. A reason that would justify the GET: row 34's Fix column says "verify", and only a read-back proves the object can be fetched.

**NIT: nothing reads `version: 2`** (`:133-139`). It costs little and documents what saved cards mean. Keep it, but describe it as documentation, not as an interface.

**Positive:**
- The design stays on the root problem and does not claim row 34 closes.
- "What it deletes" is now honest.
- The deletion condition for the revocation is stated.

## 2. Design Critic

**NON-BLOCKING NB1: two other stale copies of the claim survive, and T2/T3 recreate one of them.**
- **First copy: `work/durable-checkpoint.json`.**
  - `checkpoint_progress` writes it (`durable_checkpoint.py:52`).
  - `seal` tars it into the new archive.
  - The operator views read it: `tools/factory_dashboard.py:32-34`, and `tools/factory_board.py:189`, where it feeds "saved".
  - The revocation changes only `c.card`, so after the stop seal this file still says that `460a8f21…` is remote durable.
- **Second copy: the card's top-level `sha256`/`archive`/`r2_object`.**
  - `checkpoint_progress` puts the previous values back after sealing (`durable_checkpoint.py:29-30, 49-50`).
  - After a resume, those values name the checkpoint path and key that the seal just overwrote. That breaks the code's own rule, "only a copy of exactly this archive may be named" (`run_artifacts.py:127`).
  - T2 and T3 replay exactly this: they leave `r2_object = vm/bx_gdt298d7/checkpoint.tar.gz.age` with `sha256 = 03a1dd51…`, while the double holds new bytes.
- **Impact:** restores fail closed on the digest check (`launch.sh:179-183`), and neither copy drives a barrier, so this is not blocking.
- **Recommendation:**
  - Have the revocation also rewrite `durable-checkpoint.json` when it matches the same condition.
  - State that the stale top-level fields are part of fact 2, which is still open.
  - Word the proposed row as "the card's `durable_checkpoint` receipt", so its closure by T1 doesn't overclaim.

**NON-BLOCKING NB2: the reserve estimate shows a consequence the design doesn't state.**
- 527,987,760 B at 256 KiB/s is about 2014 s. That is more than the fixed 1800 s bound on both the PUT and the GET (`r2_upload.py:41-42`; design `:85-88`).
- So at the floor rate, the largest archive is never remote durable.
- The stop seal's worst case also grows from about 30 to about 60 minutes, against row 16's 30-minute reserve.
- **Recommendation:** say both facts plainly in Risks, so row 16's owner inherits a known number.

**NON-BLOCKING NB3: one bad GET link would stop every case at once.**
- The GET presign has never run live (open item (c)).
- If the launcher's GET links were wrong in any way, every worker would fail its barriers. Stress publication would then exhaust its infrastructure retries in every case (`stress_progress.py:39`). That is a batch-wide stop, against target property 1.
- **Recommendation:** make a live PUT+GET read-back an activation gate. The no-model smoke (row `new-smoke-1`) is a natural place for it.

**NIT:** the R2 read-after-write claim (`:325-327`) is attributed but has no link. It fails closed either way.

**NIT:** Heilmeier asks for a timeline. "About 60 lines" gives effort only.

## 3. Implementation Readiness

**NIT: T1's `RunArtifacts` list leaves out required dataclass fields** (`run_artifacts.py:37-46`): `home`, `sealed`, `pilot_wall` and `factory_slots`.

**NIT: the GET's stderr handling is unspecified.**
- `Popen(..., stdout=PIPE)` lets curl's stderr go to the runner's output.
- State `stderr=DEVNULL` (or a captured, discarded pipe) so T5's stdout/stderr check is deterministic.
- Also state that curl is killed when the size bound is exceeded.

**NIT: the GET ignores the seal's 600 s deadline, and the design doesn't say so.**
- `@processes.deadline(600)` is a context variable that only `processes.run` honours (`bin/processes.py:198-205, 277-280`).
- The GET's 1800 s bound means it runs outside that envelope, just as the PUT does today. Say that this is deliberate, so it doesn't look like a missed row-43 bound.

**NIT: T6 extraction details.**
- The guard sits inside the double-quoted remote string, so T6 must decode it the same way `test_account_handoff.py:258-259` does.
- The guard must be on its own line. Otherwise the existing `startswith('rm -rf ~/factory && tar ')` extraction (`test_account_handoff.py:256-257`) breaks.

**NIT: T4 / Change §2 don't fix the argument order** of the extended `python3 -c` program on `launch.sh:781`. Name it, for example `id put_ckpt get_ckpt put_final get_final`.

**NIT: phasing.** All five changes have to land in one commit. If the `r2_upload` change lands before the launcher change, every upload is refused. Say so, since the standard asks for phases that each leave the code stable.

---

## B2 adjudication: **AGREE-WITH-REJECTION**

The finding is dropped. My reasons:

1. **The purpose of the rule is met.**
   - ENGINEERING §2 asks that a new real failure be recorded as a row before it is fixed, under a `new-<topic>-<n>` name.
   - The design records the complete row, verbatim and named `new-checkpoint-readback-1`, in a committed file on this branch (`:289-300`), before any fix code exists.
   - Row numbers are only assigned on `factory-simplify` at merge anyway (§2). The only thing that moves to merge time is where the text physically sits, and the merge commit is the official record of the closure.
2. **The constraint is a real coordination limit, not a convenience.**
   - The founder's coordinating agent explicitly forbade this branch from editing files that owned branches change, and `claude/practice4-release-prep` changes the register.
   - ENGINEERING §1 sets direction through the founder, and §1 step 1 keeps parallel work isolated.
   - A goldfish should not make the elephant break an explicit assignment to fix where text is located.
3. **The premise overlaps an existing row.**
   - Row 34 already lists "Each worker overwrites one checkpoint object". The stale receipt is a direct symptom of that.
   - A separate row is good bookkeeping, but its absence on this branch does not hide the failure.

**Conditions (non-blocking, for the integrator and the diff goldfish):**
- The merge commit adds the row and row 34's Today-cell text verbatim, and lists this review in a `Reviewed-by:` trailer.
- The diff goldfish checks T1 against the row text.
- Narrow the row text to the card receipt (Design Critic NB1), or have the revocation cover `durable-checkpoint.json` as well. Otherwise the "closed" claim says more than T1 proves.

---

## Overall verdict: **PASS**

No blocking findings remain. Before implementation, the elephant should look at three non-blocking findings:
- **NB1:** stale copies of the claim in `durable-checkpoint.json` and in the card's restored top-level fields.
- **NB2:** the reserve arithmetic shows the largest archive times out at the floor rate.
- **NB3:** a live PUT+GET read-back should gate activation.

---

## Elephant dispositions (recorded after the verbatim review above)

The reviewer was a fresh `claude -p` process with read-only `Read,Grep,Glob`
tools.

**Verdict: PASS.** The second goldfish rules AGREE-WITH-REJECTION on design-1
B2, so that finding is dropped. Its conditions are carried into the PR body:
the integrator adds the rows verbatim and lists this review in `Reviewed-by:`.

**Non-blocking findings**
- **NB1, fixed.**
  - The revocation now also rewrites `work/durable-checkpoint.json`.
  - The proposed row text is narrowed to the receipt and that file.
  - The stale top-level card fields are stated as part of fact 2, which is
    still open.
- **NB2, fixed.** Risks now states the 2014 s > 1800 s consequence and the
  doubled stop-seal worst case, for row 16's owner.
- **NB3, fixed.** Risks now names a live PUT+GET read-back as an activation
  gate. It is carried into the PR as a remaining blocker.
- **Zoom-out alternative (checksum header): rejected, with the reason in
  Change 2.** Only a read-back proves the object can be fetched through the
  signed-link path a restore uses, and unsigned checksum headers on a
  presigned R2 PUT are unverified.
- **Zoom-out `version: 2` nit:** kept, as documentation of what saved
  receipts mean.

**Readiness nits: all fixed in the design.**
- The `RunArtifacts` fields are listed.
- `stderr=DEVNULL`, and curl is killed when the size bound is exceeded.
- The 600 s deadline exclusion is stated.
- T6 places the guard on its own line and decodes it.
- The argument order is named.
- Single-commit phasing is stated.

**Other nits.**
- Timeline: implementation is a single change on this branch.
- R2 consistency link: left as an attributed and unverified statement, since
  it fails closed either way.
