**Verdict: FAIL.** Three blocking findings are left. Two of them block increment 1, the founder migration. The third is a conflict between the manifest and stream D that blocks approval of the umbrella design. The fixes are small: each needs a sentence or a plan-schema change, not a redesign.

**What I checked:**
- I read the three persona files, `batch-service.md` (470 lines), the uncommitted interfaces §8 diff, the round-1 review, the B8/M3 adjudication, the Murphy diff and the inventory JSON.
- I recomputed the inventory claims from the JSON.
- For reuse and for the facts the design states, I checked `factory/r2_upload.py`, `factory/run.py`, `factory/batch.py`, `tools/unlock_sealed_audit.py`, `tools/open-g2-verdicts.py` and `docs/designs/stream-d.md`.
- I wrote nothing and did not run anything that changes state.

**What now holds:**
- Round-1 B1–B6 are fixed. B7 is acceptably gated: holder and restore get a reviewed addendum before increment 3, and Codex gets one before increment 4.
- M1–M9 and N1–N3 are addressed.
- I am not reopening B8. The §8 wording matches the adjudication: ordinary spend and waste are reported separately, cumulative authority includes waste, and $13 − $12 leaves $1. M3 is fixed: priority is on the request, and D keeps the active $15 rule until the parent adopts the amendment.
- The inventory claims check out: Mac has 43 and the VM has 46, the 3 VM-only checkpoints are keyed, the same 30 unwrapped prefixes are on both hosts, exactly one entry (18681d) differs, 29 match exactly, and there are 17 finals.
- Reuse is correctly named: `decrypt_one`'s Popen/pass_fds pattern, the O_NOFOLLOW open at `open-g2-verdicts.py:108`, `run.py:31` FOUNDER_RECIPIENT, and `factory/control-recipient.txt`.

## Blocking findings

### BS2-1. The 13 legacy case keys the VM can't open are out of scope, and the large sample is wrongly called a migration input
- **Severity:** Blocker (increment 1, founder plan scope)
- **Scope:** `batch-service.md` lines 224–234, 264–272 and 320–326; Murphy row new-single-path-1.
- **Evidence:**
  - `r2_upload.case_recipient` (`factory/r2_upload.py:22`) wraps every existing `casekey.age` to the founder only.
  - So the 13 keyed Mac prefixes have keys the VM can't unwrap: `1ad7fa`, `ea7425`, `f46dac`, `e5caf7`, `2b6c68`, `e3b57a`, `3826d5`, `c4a72b`, `cb5e26`, `6a8a7d`, `2a7b2a`, `22e434`, `091b3f`. The design never mentions them.
  - The design says the "largest 527,987,760-byte input is migrated and verified". That file is `case-20261017T212118Z-1ad7fa.checkpoint`, which already has a key (`casekey: true` on both hosts). It isn't in the 30-prefix plan. The largest unwrapped input is 455,502,549 bytes (`18681d` final).
  - The "zero unwrapped" check would pass while the VM still can't restore 13 prefixes. Fixing that later needs a second founder session, which defeats the one-command authority.
- **Fix:**
  1. Add a plan entry kind `rewrap_key` for each of the 13 Mac prefixes:
     - the founder identity unwraps the existing case key in memory;
     - the key is rewrapped to founder + VM into a new immutable generation `casekey.age` plus `migration.json`;
     - the archive and the original key stay untouched;
     - the founder unwrap is verified now, and the VM unwrap before activation.
  2. Or exclude those 13 explicitly in `excluded[]` with a reason, and record "VM cannot restore these" as an accepted limitation.
  3. State the recipients of the 3 VM-only keys (`c7d405`/`e15450`/`873d7f`). If they are founder-only, say plainly that they stay VM-unrestorable, or include them as `rewrap_key` entries staged through the Mac cache like the divergent checkpoint.
  4. Rewrite the large-sample sentence:
     - `1ad7fa` is already keyed, so it is a `rewrap_key` or excluded input, never re-encrypted;
     - its retirement from the active catalog pointer is a separate qualification step;
     - correct the dry-run's input-size and time figures to match.

### BS2-2. One card binds an archive that exists on neither host, and the design asserts something the plan can't satisfy
- **Severity:** Blocker (increment 1; the founder command writes `projected-card.json`)
- **Scope:** lines 231–234, 245–247, 268–272 and 316–319.
- **Evidence:**
  - Of the 30 unwrapped cards, the inventory shows 19 binding a checkpoint and 10 binding a sibling final that is present.
  - `case-20261017T114431Z-9d2b0e` has a card whose `card_archive_sha256` is `4982654d…`. No file on either host has that digest. The only file present is a checkpoint, `651038ab…`.
  - The design says "11 current cards bind a final", and qualification requires "projected cards bind correct ciphertext". For this case no correct ciphertext exists, so the implementer would have to invent the rule for `projected-card.json`.
- **Fix:**
  1. Give `kind` an enum, for example `checkpoint | final | divergent_checkpoint | rewrap_key | card_bound_absent`.
  2. For `card_bound_absent`:
     - migrate the checkpoint that is present;
     - keep the original card byte-for-byte;
     - the projected card records `bound_archive: absent` (old digest) and does not bind as current;
     - the dry-run prints it;
     - qualification expects exactly this exception, listed in the plan by digest.
  3. Change "11" to "10 present + 1 absent".
  4. Record this as a Murphy observation, or add it to row new-batch-service-1.

### BS2-3. The manifest's per-job `max_cost` contradicts stream D's single money source
- **Severity:** Blocker (umbrella and interfaces §8 contract; not the increment-1 code)
- **Scope:** `batch-service.md` schema at lines ~100–104 (`"max_calls":10,"max_cost":3`) and "Jobs retain merged batch.bind validation"; `factory/batch.py:161–173`; `stream-d.md:508–512` and `:546–574`.
- **Evidence:**
  - `batch.bind` requires `job['max_cost']` and always appends `--max-cost` to the launch args.
  - D says the single source of effective money is `committed_total_usd`, "not argv". D removes `max_cost` enforcement for authenticated factory jobs and accepts `--max-cost` only as deprecated historical input.
  - So the umbrella has two per-job money bounds with no rule for which wins.
  - Under the merged bind, a §8 revision that raises `committed_total_usd` above the frozen `max_cost` is silently capped by argv. If D wins instead, `max_cost` is dead schema.
- **Fix (one sentence):** state one of these.
  - (a) The manifest has no `max_cost`. In increment 2, `batch.bind` stops reading it and stops emitting `--max-cost` for batch jobs, and D's `job_authority` is the only money bound. `max_calls` stays.
  - (b) `max_cost` is retained only as non-enforcing historical metadata.

  Change the schema example to match, and add `batch.bind`'s cap emission to the Deletes list.

## Major (fix before the founder run; doesn't block the review)

- **M-a. The VM recipient isn't proven before the founder's one prompt.**
  - The plan pins `restore_recipient` from the tracked `factory/control-recipient.txt`. The VM proves it can unwrap only after migration.
  - A mismatch costs a second founder session, even though only the keys need rewrapping.
  - **Fix:** the agent derives the public key on the VM (`age-keygen -y` over `control.key`, which prints the public key only), records it in the survey and plan, and requires it to equal `control-recipient.txt` before freezing the plan digest.

## Nits

- **N-a. Murphy table and row text.**
  - The diff puts a blank line before row new-batch-service-1, which breaks the markdown table.
  - That row also says the pointer "selects only the card-bound version", but neither `18681d` checkpoint variant is card-bound: the card binds the final `90fa…`. Say instead that both checkpoints stay historical and the active pointer follows the card-bound final.
- **N-b. Two state roots.** §8 puts money at `~/.unbug-control/batch-money/<batch>/jobs/` while the journal and lock live in `~/.unbug-control/batches/<batch>/`. Use one root, or say why there are two.
- **N-c. The subprocess deadline formula is missing.** Line ~293 gives "size-scaled (minimum 1200s)". State the formula, for example reusing the existing 2,017 s transfer-bound formula.

**Pass condition for round 3:**
- BS2-1 and BS2-2 fixed in the plan schema and text unblock increment 1.
- BS2-3 fixed is also needed to approve the umbrella and §8.
- Increments 3 and 4 stay gated on their addenda, as written.


## Elephant response

BS2-1: added all16 founder-only existing key prefixes as key-only rewrap entries
(13 Mac +3 VM-only); archive/key originals untouched. Corrected large keyed
sample vs455MB largest unkeyed input and separate time/space estimates.
BS2-2: added explicit card_bound_absent plan type and immutable projection
absence marker, forbidden current activation, exact expected qualification
exception; recorded new-batch-service-2 before implementation. Corrected counts
to19 checkpoints+10 present finals+1 absent.
BS2-3: removed manifest max_cost; increment2 deletes batch.bind monetary cap
emission, D's job_authority is sole money bound; max_calls remains.
M-a: liveVM public recipient was derived read-only and matches tracked file;
survey/plan now pin that proof before founder prompt. Nits: table fixed,
intentional D-compatible projection path uses same batch lock, exact subprocess
deadline formula stated. No new findings rejected.
