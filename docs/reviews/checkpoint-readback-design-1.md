# Goldfish design review: `docs/designs/checkpoint-readback.md` @ 368a2ab

**Verdict: FAIL.** There are 3 blocking findings. Each one is a small edit to the design; none requires rethinking it.

I gave each persona `Mode: REVIEW`. The personas grade findings as Blocker/Major/Nit; here those map to **BLOCKING/NON-BLOCKING/NIT**. The review is read-only: I wrote no files, so it still needs saving to `docs/reviews/checkpoint-readback-design-1.md`.

**Claims I checked and found accurate:**
- The PUT-only success claim (`r2_upload.py:41-44`).
- The key naming (`run_artifacts.py:127-128`).
- The two barriers read `remote_durable` (`run.py:233`, `extension_evaluator.py:437`) and nothing else reads it.
- Both upload links are presigned at `launch.sh:780`.
- `restore_bundle.py:92` binds to the key.
- `checkpoint_progress` replaces the receipt before it seals (`durable_checkpoint.py:26-37`).
- `r2_publish` streams a GET and compares the digest (`batch_holder.py:808-826`).
- batch-service.md says what the design quotes (`:206-216`).
- Fact 3 holds in all three real cards. In e15450 the receipt says `460a8f21…` (`:173-175`) but the card's own fields say `03a1dd51…` at the same key (`:9229-9231`). canary6-round8 (`:8267-8269` vs `:8445/8500`) and c7d405 (`:6323-6325` vs `:6393/6450`) show the same thing. The stop seal that overwrites the object is at `run.py:3505`.

---

## 1. Zoom Out (Skeptical Architect)

**NON-BLOCKING: the controller already has this read-back; the design writes it a second time.**
- **Scope:** Change §1.
- **Evidence:** `batch_holder.py:818-824` already does PUT, then a streamed GET, a size cap, a SHA-256 check, a 1800 s bound, and keeps URLs out of errors. The design builds the same thing again on the worker with curl.
- **Why it matters:** two copies of one guarantee will drift apart.
- **Recommendation:** put one verifier in `r2_upload` that takes a URL and a file path, and call it from both sides. If they must stay separate, say why: the worker has no presign step, and `batch_holder` is too heavy to import on the worker.

**NON-BLOCKING: the revocation is general machinery for one call site, and nothing makes a decision from what it fixes.**
- **Scope:** Change §3.
- **Evidence:**
  - The only checkpoint seal outside `checkpoint_progress` is `run.py:3505`.
  - The design itself says no reader trusts an old receipt (§4). A grep confirms it: the only readers are `run.py:233` and `extension_evaluator.py:437`, and both read the receipt that was just written.
- **Why it matters:** fact 3 is a false record in the saved card, not a false barrier decision.
- **Recommendation:** either revoke at `run.py:3505` and drop `target()`, or justify keeping the general version in `seal`. Either way, say that this code is deleted when (a), immutable per-generation keys, lands. batch-service.md:206-207 says to "never overwrite vm/ID links".

**NIT: the "What it deletes" section deletes nothing.**
- It rewrites one path and adds GET links, `target()`, revocation and a receipt version.
- It also says `launch.sh:175` binds to the literal key. It doesn't: it reads whatever `r2_object` the card has (`launch.sh:741`). Only `restore_bundle.py:92` binds to the literal key.

**Positive:** the design keeps to the root problem. It does not claim the row closes, and it lists the remaining work plainly.

---

## 2. Design Critic

**BLOCKING: the "not a mixed state" claim is false.**
- **Scope:** "Behaviour change" section.
- **Evidence:**
  - `factory/resume-in-place.sh:27-34` copies the host's current `factory/` tree onto a parked VM and restarts `run.py`. It never rewrites `~/.factory-r2`.
  - So a VM launched before this change, then resumed in place, runs the new `r2_upload` with old links that have no `checkpoint_get`.
  - Every checkpoint then reports not remote durable. `stress_progress.publication` raises `InvalidInfra('stress checkpoint not remotely durable')` (`stress_progress.py:39`) and keeps retrying until infrastructure is exhausted. The case stops.
- **Recommendation:** pick a fix and add the file to the change list. Either `resume-in-place.sh` presigns and rewrites the links, or it refuses VMs whose links file has no GET links.

**BLOCKING: the stale receipt is a new real failure but has no register row.**
- **Scope:** "Murphy rows" section.
- **Evidence:**
  - Row 34's text (`murphy-register.md:46`) does not describe a receipt that stays `remote_durable: true` after its object is overwritten. Three real saved cards show exactly that.
  - ENGINEERING.md:99-102 says a new failure seen in a real run becomes a row before it is fixed. It also says branches add rows as `new-<topic>-<n>`. That answers the design's reason for not touching the register: a conflict with another branch is expected, and the rule already plans for it.
- **Recommendation:** add `new-checkpoint-readback-1` on this branch. T1 uses the real card and the real `seal`, and the revocation does not depend on how faithful the authored R2 double is. So T1 could close this new row, even though row 34 stays open.

**NON-BLOCKING: `local_durable` is stale too, and the revocation leaves it alone.**
- **Evidence:**
  - The receipt's `archive` (`e15450…json:174`) is the same file as the card's later archive (`:9230`). `staged.replace(out)` (`run_artifacts.py:124`) replaces it on every checkpoint seal, whether or not an upload happens.
  - The design only flips `remote_durable`. It only does so when an upload will be attempted.
- **Recommendation:** mark the whole receipt superseded on any checkpoint seal that replaces its `archive` path.

**NON-BLOCKING: the extra GET lengthens the stop seal inside the retirement reserve, and that cost isn't measured.**
- **Evidence:**
  - Row 16 (`murphy-register.md:28`) says the reserve is 30 minutes, and the R2 upload alone may already take 30 minutes. The GET can add up to another 1800 s to the stop seal at `run.py:3505`.
  - The design says "row 16 owns" this and gives no number. Row new-single-path-1 records a real 527,987,760-byte archive, which could be used to estimate the cost.
  - If the GET pushes the stop seal past retirement, the last upload never happens.
- **Recommendation:** estimate PUT+GET time for that archive, or let the stop seal record a PUT-only result when the remaining time is short.

**NON-BLOCKING: the design misses parts of the Heilmeier standard.**
- It gives no timeline and no effort or cost estimate (it only mentions R2 egress).
- The Objective is written in project jargon ("receipt revocation", "remote durable", "barriers").
- The headings ENGINEERING.md:23-28 requires are all present.

**NIT:** the statement that R2 is strongly consistent for read-after-write has no citation. A stale read would fail closed anyway, so this is a NIT.

---

## 3. Implementation Readiness

**BLOCKING: T3's assertion "no `r2_object` on the card" cannot pass with the real card.**
- **Evidence:**
  - `checkpoint_progress` saves the card's `sha256`, `archive` and `r2_object` before sealing and puts them back afterwards (`durable_checkpoint.py:29-30, 49-50`). The existing `tests/factory/test_durable_checkpoint.py:39,54` checks that this happens.
  - The e15450 card has `r2_object` at the top level (`:9231`), so after any T3 failure the card still has it.
- **What to do:** an implementer has to choose between changing the restore behaviour, which breaks the existing test, and changing the assertion. Choose in the design. The likely intent is: the receipt has no `r2_object`, and the card's top-level fields still equal the e15450 values.

**NON-BLOCKING: when to revoke depends on a value computed after the revocation point.**
- **Evidence:**
  - The design says to revoke before `scorecard.json` is written (`run_artifacts.py:101`), and only if an upload will be attempted.
  - Whether an upload happens depends on `case_key` (`:128`), which is only computed at `:109-115`.
- **Recommendation:** state the choice. Either move the `case_recipient` call earlier, or revoke whenever `target()` matches the receipt's key, regardless of `case_key`. The second is safe and needs no reordering.

**NON-BLOCKING: the design doesn't say how the GET subprocess runs.**
- **Evidence:** `seal` runs under `@processes.deadline(600)` (`run_artifacts.py:57`). Only `processes.run` respects that deadline. Today `r2_upload` uses plain `subprocess.run`.
- **Why it matters:** the choice decides whether the GET can be cut off at 600 s. This touches row 43.
- **Recommendation:** name the call, for example `Popen` with a monotonic bound and process-group kill.

**NON-BLOCKING: T1's setup is underspecified.**
- **Evidence:**
  - With `c.args.dry_run` true, `case_key` is `None` (`run_artifacts.py:109`). Then nothing uploads and nothing is revoked, so T1 would pass without testing anything.
  - With `batch_release_sha256` set, `seal` needs `control-recipient.txt` (`:105-108`).
  - `seal` calls `upload()` without a links path (`:128`), so the test has to point `HOME` at the double's links file.
- **Recommendation:** list the `c` attributes T1 needs, and how it injects the links file and `retain_delivery`.

**NIT:** `curl --retry 3` writing to stdout appends a retried transfer after the partial bytes already sent. The size or hash check then fails, so it fails closed, but the retry does nothing useful. Retry in Python with a fresh hash, or drop `--retry` on the GET.

**NIT:** T4 does not say how the launcher's `python3 -c` line is extracted from `launch.sh`. The "Existing tests" list also misses `test_r2_upload.py:53-55`, which still passes.

---

## Overall verdict: **FAIL**

The 3 blocking findings:
1. **False rollout claim:** `resume-in-place.sh` puts new code next to old links, and the barriers then stop the case.
2. **Missing register row:** the stale-receipt failure from real runs needs a `new-<topic>-<n>` row on this branch, per ENGINEERING.md §2.
3. **Wrong T3 assertion:** as written it contradicts `checkpoint_progress`'s locked restore behaviour, so it can't pass on the real card.

---

## Elephant dispositions (recorded after the verbatim review above)

The reviewer was a fresh `claude -p` process (Claude family), with read-only
tools `Read,Grep,Glob`. Git tools were withheld because this worktree's
isolation guard refuses any command that could launch git indirectly. It read
committed files directly.

**Blocking findings**
- **B1, mixed state via `resume-in-place.sh`: fixed.** Design §Change 5 adds
  a guard before `rm -rf ~/factory`. It refuses old links that have no GET
  links. Test T6 covers it.
- **B2, register row for the stale receipt: rejected by the elephant, pending
  a second goldfish.**
  - Reason: this branch's assignment explicitly forbids touching files that
    the owned branches change. `docs/murphy-register.md` is changed by
    `claude/practice4-release-prep`.
  - Mitigation: the design records the proposed `new-checkpoint-readback-1`
    row verbatim, for the integrator to add at merge.
  - The adjudication is recorded in `checkpoint-readback-design-2.md`.
- **B3, T3's assertion contradicts `checkpoint_progress`'s restore: fixed.**
  T3 now asserts that the receipt has no `r2_object` and that the card's
  top-level fields are restored to the real e15450 values.

**Non-blocking findings and nits**
- **Read-back duplicated from `batch_holder.r2_publish`: kept separate,
  reason stated in the design.** `r2_publish` is controller-only (local
  presign, urllib, holder import). The worker has only presigned links and a
  curl transport. Both verifiers apply the same rule.
- **Revocation placement: kept in `seal`, justified.** The design names
  `run.py:3505` as today's only caller and says when the revocation is
  deleted.
- **`local_durable` stale too: fixed.** The whole receipt is revoked, on a
  local-path match or a key match.
- **The revocation condition depended on `case_key`: fixed.** It is now
  independent of `case_key`.
- **GET process handling: fixed.** `Popen`, a monotonic bound with kill, and
  no `--retry`.
- **Retirement-reserve cost: estimate added.** The bound itself stays with
  row 16, owned elsewhere.
- **T1 setup underspecified: fixed.** The `c` attributes, HOME injection, the
  proxy bypass and the `retain_delivery` guard are now spelled out. T1c was
  added for the local-path condition.
- **Heilmeier gaps: fixed.** The design now has a plain objective and an
  effort estimate.
- **Nits: fixed.** "What it deletes" is corrected, including the
  `launch.sh:741` wording. The R2 consistency claim is now attributed and
  marked unverified. T4's extraction method is named. `test_r2_upload.py` is
  added to the existing-tests list.
