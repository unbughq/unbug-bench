**Verdict: FAIL.** The review below has 8 blocking findings. Five of them block increment 1, the founder migration. The other three block later increments or final completion.

I read three things against the three personas and the Zoom-Out, Heilmeier and Implementation-Readiness standards, plus `docs/ENGINEERING.md`:
- `docs/designs/batch-service.md`
- the proposed `docs/designs/interfaces.md` §8 (uncommitted diff)
- the files they reference

I checked reuse in `factory/key_holder.py`, `r2_upload.py`, `launch.sh`, `batch.py`, `codex_login.py`, `budget.py`, `restore_bundle.py`, `statement_round.py`, `registry.py`, `tools/open-g2-verdicts.py`, `tools/unlock_sealed_audit.py`, `bin/setup-secrets` and `tests/factory/test_restore_inventory.py`. I edited nothing and ran nothing that changes state. The existing interface reviews go up to 5, so the next number is **interfaces-design-6.md**.

---

# Batch service design review 1 (interfaces design review 6)

**Scope:** stream B control VM lifecycle, scoped restore key, the one-time founder legacy migration, Codex renewal, the money channel (interfaces §8), status, and the practice end-to-end test. Design baseline is ac33267.

**Verdict: FAIL.** 8 blocking findings, 9 major, 3 nits.

**Increments vs final completion:**
- **Increment 1 (migration command plus dual wrapping)** can be built once B1–B5 are fixed. B6–B8 don't apply to it.
- **Increments 2–5 and final completion** also need B6–B8. Majors M1–M9 should be fixed before increment 3 starts.
- No Murphy row closes in any increment until the practice end-to-end test passes on real artifacts. The design already says this, and it is correct.

## Blocking findings

### B1. The migration doesn't say which store is the source of truth, and the two stores already differ
- **Severity:** Blocker (increment 1, operational)
- **Affected scope:** "Scoped key and one-time legacy migration" (lines 155–191) and line 271.
- **Problem:**
  - Murphy row new-single-path-1 records the real store as 43 checkpoints, 30 of them unwrapped.
  - The VM survey at line 271 found 46 checkpoints, 30 unwrapped.
  - The command runs on the Mac and then "copies ciphertext and wrapped keys to VM". The design never says:
    - which directory the command reads. `batch.restore_inventory` prefers the git common directory's `sealed/` and falls back to the checkout's `sealed/`;
    - whether the 30 unwrapped archives are the same 30 on both hosts;
    - what happens to the 3 checkpoints that exist only on the VM;
    - how the VM copies are replaced while the VM holder and resume timer are live.
- **Fix:**
  1. The dry-run writes a plan file listing, for each archive, its path, size, ciphertext sha256 and card sha256, for **both** the Mac store and the VM store.
  2. The founder run accepts only a plan whose digest matches, and the command takes that digest as its argument.
  3. Name the exact Mac path the command reads.
  4. Make the VM sync its own step, run by the agent rather than the founder, with dispatch stopped first:
     - stop the holder and resume timer only after proving no worker is active;
     - write new files beside the old ones;
     - verify them;
     - record command, prior hash, new hash and how to reverse each step in `docs/reports/batch-service-vm.md`.
  5. Explain the 46-vs-43 gap in the plan.

### B2. Editing cards and archives in place breaks existing card-hash bindings, and duplicates the generation store
- **Severity:** Blocker (increment 1)
- **Affected scope:** lines 172–180 ("Replace ciphertext with os.replace, set public card.sha256, clear stale r2_object …"), and the `.pre-vmkey` rollback at 189–191.
- **Problem:**
  - Other code pins the exact bytes of a historical card:
    - `factory/restore_bundle.py:95, 188, 266, 308` (`public_card_sha256`);
    - `factory/statement_round.py:185`, which raises `'stale card'` when the registry's `card_sha256` doesn't match.
  - Rewriting a card's `sha256` field changes the card's own hash. That silently invalidates every one of these bindings. The design doesn't list them.
  - The swap also contradicts the design's own fix for row 27: immutable `generations/<case>/<sha256>/` directories plus one atomic pointer.
  - The in-place swap needs a migration journal, partial-swap replay, `.pre-vmkey` backups and a rollback procedure. That is the staging and rescue machinery that ENGINEERING §4 says to delete.
- **Fix (simplest):** don't change any original file.
  1. Write each migrated archive under a new, digest-named path, next to a new `casekey.age` and an immutable `migration.json`. That file records `{case, old_archive_sha256, old_card_sha256, new_archive_sha256, casekey_sha256, recipients}`.
  2. Consumers resolve through that binding, or through the generation pointer once increment 2 exists.
  3. This removes the swap journal, partial-swap replay, `.pre-vmkey` and rollback. "Rollback" becomes "ignore the new files".
- **If the founder still wants in-place swaps:**
  - grep every `card_sha256` / `public_card_sha256` consumer;
  - prove that none of them references the 30 archives, or update each one in the same locked step;
  - write that list into the design.

### B3. Nothing proves the first-pass re-encryption is complete before it is accepted
- **Severity:** Blocker (increment 1, cryptographic correctness)
- **Affected scope:** lines 166–171.
- **Problem:**
  - The first pass streams `age -d` (founder identity) through Python into `age -e`. The second pass decrypts the new archive with the case key and checks that its hash equals the first pass's hash.
  - If `age -d` stops early (corrupt or truncated tail, killed process, `EPIPE`), `age -e` still produces a **valid, authenticated, truncated** archive. Both hashes are taken over the same truncated bytes, so they match.
  - The legacy cards bind only the ciphertext, so there is no independent hash of the original plaintext to compare against.
  - The only proof of completeness is that `age -d` finished: it authenticates the last chunk only at the end of the stream. "Successful founder and case decryptions" is too vague to guarantee this check is made.
- **Fix:** spell out the acceptance rule.
  1. Accept the first pass only if all of these hold:
     - Python read the decrypt output to EOF;
     - `age -d` exited 0, checked after EOF;
     - `age -e` exited 0;
     - the staged file was fsynced.

     Any other outcome deletes the staged file and marks the archive failed.
  2. The second pass must also read to EOF, exit 0, and produce an equal hash and byte count.
  3. Add a structural check of the plaintext in the first pass: stream it through `gzip`/`tar` validation without extracting. This catches a legacy archive that is authenticated but malformed.
  4. Required process details:
     - The identity occupies `age -d`'s stdin, so pass ciphertext as `/dev/fd/N` using `pass_fds`. Reuse `tools/unlock_sealed_audit.decrypt_one`'s Popen pattern rather than writing a new one.
     - Write `age -e -o <staged>` straight to disk. Python only relays bounded chunks between the two age processes and runs both pipe ends at once, so there is no deadlock.
     - Open each input with `O_NOFOLLOW` and hash it against the plan digest **before** the prompt. Then decrypt from that same file descriptor, so the file can't be swapped between check and use. `open-g2-verdicts.py:104–108` already does this.
     - Copy the hardening from `unlock_sealed_audit.main()`: `RLIMIT_CORE=0`, `umask 077`, and require a TTY plus `GetPassWarning` as an error.
     - On `KeyboardInterrupt` or SIGTERM: kill the children, clear the identity and case-key buffers, and delete the staged files.

### B4. Recipients aren't pinned, and the founder identity isn't checked against them
- **Severity:** Blocker (increment 1, cryptographic correctness)
- **Affected scope:** lines 151–153 and 164–171.
- **Problem:**
  - The design seals to "founder + VM" and "founder + case" but never says where those public keys come from.
  - Line 169 checks that two header stanzas exist, and line 171 admits that stanza count doesn't prove who the recipients are.
- **Fix:**
  1. Founder recipient: read it from the same pinned source `r2_upload.case_recipient` uses today (the launch config's `c.recipient`).
  2. VM recipient: read it from `factory/control-recipient.txt`, and require it to equal the manifest's restore recipient.
  3. Before any decryption, derive the public key of the entered identity (`age-keygen -y` over stdin) and require it to equal the pinned founder recipient. Otherwise stop, without printing either value.
  4. Prove the recipients by successful decryption:
     - founder identity unwraps the key — already in the design;
     - case key decrypts the archive — already in the design;
     - the VM unwraps the key — only "later" in the design. This is the only check that proves the VM recipient.
  5. State that a VM-recipient mismatch is fixed by **rewrapping the keys only**, never by re-encrypting the archives. That cheap fix is a benefit of using a per-case key.

### B5. Founder runbook gaps make the one-shot command operationally unsafe
- **Severity:** Blocker (increment 1, operational)
- **Affected scope:** lines 155–162 and 181–191.
- **Missing pieces:**
  1. **Disk-space preflight.** Staged copies roughly double the largest archive set, and the 527,987,760-byte sample alone is large. The dry-run has to report the space needed and refuse to start if it isn't free.
  2. **Mac sleep.** Wrap the run in `caffeinate -i`, the same way the holder does.
  3. **Key naming.** The design says "per-case key", but the existing layout names keys per archive prefix (`<prefix>.casekey.age`; see `test_restore_inventory.py:49`). Say one key per archive file. Also explain why 22 cases have 30 archives.
  4. **The large sample.** Row new-single-path-1 asks for "retirement of the historical large sample". The design doesn't say whether that means migrate it or move it out of the canonical store. Decide.
  5. **Output.** Say what the founder sees, which exit codes mean what, and the one command to re-run after a partial failure. Re-running asks for the identity again, and that is fine.
  6. **Who does the VM copy.** Say whether the founder or the agent runs the VM copy, R2 verification and qualification. None of these steps needs the founder key, so they belong to the agent, per B1.

### B6. Nothing defines what makes a batch manifest "authorized"
- **Severity:** Blocker (increments 2–5)
- **Affected scope:** lines 32–36 and interfaces §8 paragraph 1.
- **Problem:**
  - The manifest is the root of both money authority and restore-key scope.
  - The design never says:
    - which file the manifest is;
    - who writes it;
    - how the holder or service pins it;
    - how an amendment is authorized.
  - "Authorized manifest" is undefined. A process that can write `~/.unbug-control/batches/<batch>/` could therefore raise limits.
- **Fix:**
  1. The manifest is a tracked file inside the frozen batch release.
  2. Its sha256 is pinned in the holder policy, the same way `batch.bind` checks `batch_release_sha256`.
  3. An amendment is a new manifest digest, accepted only through a named command, and it must obey §8's no-lowering and no-revival rules.
  4. Spell out the schema with file path, types and examples. Include the `target_slots` and router-config fields, which §8 names but doesn't define.

### B7. The holder's enqueue and receipt protocol and the per-reason caps are unspecified
- **Severity:** Blocker (increment 3)
- **Affected scope:** lines 48–64 and 79–84.
- **Problem:**
  - "Holder enqueue returns that durable operation ID immediately … moves expensive validation/inventory/provisioning off its socket accept loop" is a large refactor of `key_holder.py`, the 455–672 request loop. The design doesn't give:
    - the request fields;
    - the response;
    - a status or reconcile operation;
    - the receipt file path and schema;
    - how "inventory shared with holder for ≤15 seconds" is passed between processes.
  - The journal schema has one `attempts` field. interfaces §4 caps relaunches **per case per reason**, and the credit cap is per verified top-up. One counter can't enforce both.
- **Fix:**
  1. Add a holder protocol table: operation name, request JSON, response JSON, receipt path, idempotency key (`operation_id`), and each error.
  2. Name the shared inventory cache file and its freshness check.
  3. Replace `attempts` with `relaunches: {reason: count}` plus `credit_topups_consumed: [receipt_id]`.
  4. Doing the holder refactor as an addendum design reviewed before increment 3 is acceptable.

### B8. Interfaces §8 charges infrastructure waste to the case budget, against ENGINEERING §3 and §4
- **Severity:** Blocker (interfaces §8, increment 2)
- **Affected scope:** interfaces §8 paragraph 3 ("cumulative authority including already-spent money and infrastructure waste") and paragraph 4 ("the model bound includes D's model infrastructure-waste charges").
- **Problem:**
  - ENGINEERING §3 puts a factory-bug resume "with the cost on the infra-waste line".
  - interfaces §4.4 puts relaunch VM time on the infra-waste line.
  - §8 folds waste into the per-case commitment and admission check. A factory bug would then use up the case's own allowance and could retire a healthy case as `retired_batch_bound`.
- **Fix:**
  - Per-case commitment covers only the case's model spend.
  - Add `infra_waste_limit_usd` to the manifest as its own line. Admission checks the case line, the waste line, and the overall batch cap separately.
  - `case_budget.total_spent_usd` minus `infrastructure_waste_usd` is the case figure. Use it only when both values are known; otherwise block, as the design already says.

## Major findings

### M1. Heilmeier gaps
- **Affected scope:** whole document.
- **Problem:** the standard requires every item below to be answered explicitly. The design is written as telegraphic shorthand (for example "label-only exhaustion is a D factory-bug candidate", or "state=launched plus no successor collected means running"). A new reader can't answer:
  - the objective in plain words;
  - the cost of the implementation work;
  - a timeline;
  - mid-term exams per increment.
- **Fix:** add a short plain-language section with:
  - what the founder gets: "a batch runs to the end with the Mac off";
  - the current state;
  - the cost, as agent sessions plus the $3 model / $1 infra qualification cap;
  - a target date per increment;
  - a one-line exam per increment.

  Keep the dense spec underneath.

### M2. The design doesn't say who uses the migrated archives
- **Affected scope:** lines 103–106 and 155.
- **Problem:**
  - The 22 historical cases are "excluded from the manifest", and cross-batch import is refused.
  - `batch.bind` rejects cards from other releases (`batch.py:156–157`).
  - Once migrated, the VM can decrypt 30 archives that no stated flow restores. That widens what the VM can read with no stated use.
  - The only stated goal is row new-single-path-1's "zero unwrapped" check. Moving the 30 archives, without decrypting them, to `sealed/legacy-founder-only/` outside the canonical restore directory would meet that goal.
- **Fix:** the founder authorized the migration, so name the consumer in one sentence (for example "a future authorized manifest may restore them"). If there isn't one, take the quarantine route and drop increment 1.

### M3. §8 priority: "extension" is listed as a job, but a case has exactly one money owner
- **Affected scope:** interfaces §8 paragraphs 1 and 3.
- **Problem:** jobs carry the priorities `replacement | diagnosis | extension | ordinary`, yet "a case has one job money owner". An extension or diagnosis of the same case would be a second job, which contradicts that rule.
- **Fix:**
  - Attach the priority to the **revision request** (`money_wait`), not to the job.
  - Map ENGINEERING §3's $15 per extension to `requested_total_usd = previous + 15`.
  - Have D enforce the cap of at most 5 extensions.

### M4. Credentials the VM needs are never provisioned, and the Codex refresh path isn't verified
- **Affected scope:** lines 195–214.
- **Problem:**
  - `factory/codex_login.py:1` says "Never refresh here".
  - Today the only renewal is the interactive browser login in `bin/setup-secrets codex`, run on the Mac.
  - The design's "existing pinned Codex login refresh facility" isn't shown to exist.
  - R2 credentials come from `secrets.age` (`launch.sh:126, 142`), and `setup-secrets` says R2 "stays on this Mac".
- **Fix:**
  1. Name the exact non-interactive refresh mechanism of the pinned Codex 0.162.1 CLI, and record a probe that proves it.
  2. Name the file that receives the rotated bundle (a `secrets.age` member, or a separate owner-only file) and the recipients it is re-sealed to.
  3. Add a rollout step where the founder installs a scoped R2 token plus a refresh-capable Codex login on the VM once.
  4. If refresh can't be proved, row 20 stays partial, and the design says so.

### M5. The design doesn't list what it deletes
- **Affected scope:** whole document.
- **Problem:** ENGINEERING §1 step 2 and §4 "delete before adding" require this list. The design keeps `restore_sync.py`, with its hardcoded destination (row 26), and doesn't say what happens to:
  - `ttl_continuation.py` (three attempts / 24 hours);
  - `coordinator_inventory` operator observations;
  - the `.pre-vmkey` path.
- **Fix:** add a "Deletes" section naming each file or function and when it is removed.

### M6. Too much in one design
- **Affected scope:** increments 1–5.
- **Problem:** 15 rows, a holder refactor, a store, money, renewal and status all sit in one approval.
- **Fix:** keep this as the umbrella design. Require short addendum designs, each reviewed, for increment 3 (holder protocol, B7) and increment 4 (renewal, M4) before they are implemented.

### M7. Increment 1's tests don't use real artifacts
- **Affected scope:** lines 182 and 235–237.
- **Problem:** throwaway keys are right, but generated plaintext breaks the real-artifacts rule.
- **Fix:** test with a real public bundle or real card layout, encrypted to a **throwaway founder recipient** so it has the legacy shape. Add test cases for:
  - truncated ciphertext (B3);
  - `age -d` killed mid-stream;
  - ENOSPC while staging;
  - identity that doesn't match the pinned recipient (B4);
  - plan-digest mismatch (B1).

### M8. The relaxation of the control-identity refusal needs one exact condition
- **Affected scope:** lines 145–150 and `key_holder.py:571`.
- **Problem:** "verified casekey/generation/release/retirement/money authority" is a list of ideas, not a condition.
- **Fix:** write the exact predicate that replaces `if control_identity and job['mode'] != 'new'`, naming each field and its source (pinned manifest digest, current pointer, retirement receipt, §8 revision). Add a test proving that audits and caller-chosen paths are still refused.

### M9. Practice end-to-end prerequisites
- **Affected scope:** lines 257–266.
- **Problem:** the design doesn't say what happens if the qualification run hits its $3 model / $1 infra cap halfway.
- **Fix:** state the cleanup and verdict for a stop at the cap: worker deleted, deletion proved, recorded as failed and unscored, cost on the infra-waste line.

## Nits
- **N1.** Row 20 is listed both as owned (line 20) and as needing shared proof (line 21). Pick one.
- **N2.** The outbox retry sequence "15/30/60s then 5min" isn't explicit about whether it ever stops retrying. Say "forever, until batch_deadline".
- **N3.** Line 222 says `bin/unbug status`, but status.md says `unbug status`. State the install path.

## Assessment of the founder migration authority (per your request)
- **Sound as specified:**
  - one Mac command;
  - identity entered once through hidden getpass and passed only to age's stdin;
  - no argv, environment variable or file holding the key;
  - streamed re-encryption with no plaintext written to disk;
  - a per-archive key wrapped to founder + VM;
  - the founder key never leaves the Mac;
  - tests with throwaway keys only;
  - existing code to reuse: `open-g2-verdicts.py` and `unlock_sealed_audit.decrypt_one`.
- **Not yet correct:**
  - the acceptance rule that proves a stream is complete (B3);
  - recipient pinning (B4);
  - source-store identity and the VM sync step (B1);
  - in-place swaps, which break card-hash bindings (B2);
  - the founder runbook (B5).
- **Recommendation:** replace the "backup + atomic swap" model with immutable migrated outputs plus a binding record. It is simpler and safer, and it removes the rollback machinery. If the founder keeps the swaps, the card-binding inventory in B2 is mandatory.

**Pass condition for round 2:** B1–B5 fixed for increment 1. B6–B8 also fixed for approval of the whole design.


## Elephant response

B1 fixed by digest-pinned cross-host survey/union plan with exact Mac source,
VM-only exclusions and divergent-generation preservation; new Murphy row recorded.
B2 fixed with founder-approved immutable generations and atomic catalog activation
after VM qualification; originals/card pins untouched, rollback moves pointer.
B3 fixed with explicit EOF/zero exit for both crypto processes, structural
validation, same opened descriptor, streaming roundtrips and safe child cleanup.
B4 pins recipient sources/identity match and requires VM unwrap before activation.
B5 adds space/sleep/output/replay/large-sample/agent-owned VM runbook.
B6 names tracked manifest, policy hash authority, install/amend command and schema.
B7 holder protocol/restore predicate is an explicitly mandatory fresh-reviewed
addendum before increment3 (the review expressly permits this); deterministic
operation IDs, inventory path and per-reason/top-up counters are specified.
B8 rejection upheld by different-family second goldfish in
batch-service-money-adjudication-1.md. Clarified ordinary vs cumulative authority;
no separate waste cap, no erased money.
M1–M9 addressed: delivery/time/exams/deletions and gated detailed addenda; priority
on revision requests, D's active ENGINEERING policy unchanged; refresh API cited
with pinned-version/provisioning explicitly unproved and gated; synthetic crypto
tests use saved public metadata and close no rows; cap hit always cleanup,
failed/unscored qualification. Nits corrected. No real VM writes or spending.
