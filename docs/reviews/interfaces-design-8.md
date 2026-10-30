# Batch-service design review, round 3

**Verdict: FAIL, with one blocker left.** It is small and only affects increment 1. The umbrella design and interfaces §8 pass. With BS3-1 fixed, increment 1 is ready to implement. Increments 3 and 4 stay gated on their addenda, as the design says (lines 508–512). This review does not claim those increments are ready.

## What I checked
- Read the three persona files, both standards, ENGINEERING, `batch-service.md` (512 lines), interfaces §8, the Murphy diff, all three earlier reviews, the inventory and the frozen plan. I edited nothing and ran nothing that changes state.
- **Pinned digests match.** The inventory's sha256 is `c59a0754…`, which equals `plan.survey_sha256`. The plan's own sha256 is `bac461d8…`.
- **The VM recipient proof holds.** `vm_restore_recipient` in the plan, `restore_recipient` in the plan, the survey and `factory/control-recipient.txt` are all `age1ae6f86…m6ch`. The founder recipient equals `run.py:31`.
- **I recomputed the plan's counts.** There are 64 entries:
  - 29 checkpoint, 17 final, 1 divergent_checkpoint, 1 card_bound_absent, 16 rewrap_key, 0 excluded.
  - That is 48 unique archive variants across 30 prefixes, totalling 3,251,961,841 bytes. This matches line 286.
  - The active sources are 19 checkpoints and 10 finals. Each binds its card, and each prefix has at most one.
  - 9d2b0e has no active source, which is correct.
  - No prefix appears both as a rewrap and as an archive migration.
- **BS2-1 is fixed in the plan.**
  - There are 13 Mac rewraps plus 3 VM-only rewraps (c7d405, e15450, 873d7f). The VM-only keys and cards are staged in the Mac cache.
  - Every rewrap's archives are present on the VM, and the selected archive equals the card's binding.
  - Each key digest is the same on both hosts, with one stanza each.
  - 1ad7fa (527,987,760 bytes) is a key-only rewrap. Line 362 states this correctly.
- **BS2-2 is fixed.** 9d2b0e is `card_bound_absent` with `active_source:false`, and the "19 + 10 + 1" figure is right. Murphy row new-batch-service-2 is present, and the table renders.
- **BS2-3 is fixed.**
  - The example schema has no `max_cost`.
  - Lines 108–112 and 504 delete the bind's money-cap emission, which ships in increment 2.
  - Lines 351–356 of §8 make D's `job_authority` the only money bound.
  - The shared-lock projection path is explained.
  - The deadline formula is exact: 1739 s for the largest unkeyed 455 MB input, and 2016 s for the 528 MB verification.
- **B8 is not reopened.** The §8 wording matches the adjudication: a $13 commitment with $12 spent leaves $1, and waste is reported on its own line.
- **Everything the design says it reuses exists:**
  - `registry.atomic_json` (`factory/registry.py:18`);
  - `unlock_sealed_audit.decrypt_one` and `verify_archives` (`:213`);
  - the O_NOFOLLOW open at `open-g2-verdicts.py:108`;
  - `transfer.py`, `collect.sh`, `control_resume.py`, `codex_login.py`;
  - `r2_upload.case_recipient` (`factory/r2_upload.py:7`).

  None of the new modules (`batch_service.py`, `batch-policy.py`, `migrate-legacy-checkpoints.py`) duplicates something already there.
- **Heilmeier:** objectives, current state, approach, risks, cost, timeline and deletions are all present (lines 10–22 and 476–506). **Zoom-out:** no YAGNI or dead-end findings.

## Blocking finding

### BS3-1. The rewrap path has no specified output and no tests
- **Severity:** Blocker for increment 1 only.
- **Scope:** lines 259–273, 307–312, 356–358, 371–375 and 436–438.
- **What's wrong:**
  - Line 307 gives the output layout only for archive-migration entries: `generations/<case>/<new-ciphertext-sha>/` containing `archive.age` and the rest.
  - For the 16 rewrap entries, line 269 says only "publishes immutable key migration record referencing unchanged ciphertext". The implementer would have to choose:
    - the directory name (rewraps produce no new ciphertext);
    - whether there is one generation per prefix or one per archive (11 rewrap prefixes have two archives);
    - the members (`projected-card.json`? no `archive.age`?);
    - which digest replay uses to detect an entry that's already complete.
  - Qualification line 358, "projected cards bind correct ciphertext", doesn't fit rewraps, whose original card binds the unchanged archive.
  - Neither test list (lines 371–375 and 436–438) covers `rewrap_key`, a VM-only rewrap staged in the cache, or `card_bound_absent`.
- **Why it blocks:** these 16 entries are the round-2 fix, and they run inside the founder's single session. A wrong rewrap is the one mistake that forces a second founder session.
- **Minimal fix (about three sentences, no redesign):**
  1. **Layout.** One rewrap generation per prefix, at `generations/<case>/key-<old key_sha256>/`. It contains `casekey.age` (founder + VM), `original-card.json` (byte-for-byte), `migration.json` (the old key digest, every `archives[]` digest and size unchanged, recipients, validation booleans) and `manifest.json`. It has no `archive.age` and no projected card. Replay skips the entry when the manifest and the old key digest verify.
  2. **Verification.** The founder unwrap of the new `casekey.age` must equal, byte-for-byte, the in-memory unwrap of the old key. Qualification on the VM unwraps with the VM identity and stream-decrypts every listed archive to EOF.
  3. **Tests (throwaway keys).**
     - A legacy single-stanza case key is rewrapped. Both the throwaway founder and VM identities recover identical bytes. The old key and archive bytes are unchanged, and the new key decrypts the unchanged archive.
     - An entry whose inputs come from the cache rather than `mac_root`.
     - A `card_bound_absent` entry: the original card is preserved, the projected card carries `bound_archive.status=="absent"`, and the entry can't be selected as active.
     - Replay skips a completed rewrap.

## Major (fix before the founder run; doesn't block approval)
- **M3-a. The new generation archives aren't gitignored.**
  - `.gitignore:7` ignores only `sealed/*.tar.gz.age`.
  - `git check-ignore` reports `sealed/generations/<case>/<sha>/archive.age` as trackable.
  - About 3.25 GB of ciphertext would sit in the Git common checkout (`plan.output_root`).
  - **Fix:** in increment 1, add `sealed/generations/**/archive.age`.
  - Cards and `casekey.age` under `sealed/` are already tracked today, so leaving them trackable follows the existing practice.
- **M3-b. The VM recipient for new cases has no source or timing.**
  - Increment 1 says "dual wrapping" (line 436), and line 212 changes `case_recipient`. But line 213 says workers get the VM recipient "from the pinned manifest", and the manifest only arrives in increment 2.
  - `case_recipient` (`r2_upload.py:21`) still wraps to the founder only.
  - Any case sealed after the plan freeze stays founder-only and falls outside the single founder session.
  - **Fix:** say either that increment 1 changes only the migration output, or that it reads the tracked `factory/control-recipient.txt`, later checked equal to `manifest.restore_recipient`. Also state that a founder-only key sealed after the freeze is a known input for the next plan, not a silent gap.

## Nits
- **Line 35** says "job priority/authority from interfaces §8", which contradicts line 114 and §8 (priority belongs to the request). Drop "priority".
- **Lines 263 and 273.** A single stanza doesn't prove a key is founder-only, and the design admits this. Say what happens when the founder unwrap fails: that entry fails with exit 1, is reported as VM-unrestorable, and every other entry still completes.

## Pass condition
Round 4 passes once the BS3-1 fix is in the text. M3-a and M3-b should be fixed in the same edit, because both are one-liners. The umbrella design and §8 need no further changes.


## Elephant response

BS3-1 fixed with exact immutable key-<old-key-sha> layout/members/replay key,
byte-for-byte founder key unwrap proof, VM all-archive EOF verification and
throwaway tests for rewrap/cache inputs/replay/card-bound-absent. M3-a explicitly
adds archive.age ignore in increment1. M3-b clarifies migration-only first
increment; normal seal wrapping ships in increment2 before enablement. New
post-freeze founder-only keys require a new explicit plan. Nits: priority wording
fixed, unwrap failure fails one entry safely while others continue. No rejection.
