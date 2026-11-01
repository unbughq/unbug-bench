I'm returning **BLOCKED**: the design has 3 Blockers, 6 Majors and 4 Nits. The full review text is below. It covers all three personas (zoom_out, design_critic, implementation_readiness) and all three standards (zoom-out, Heilmeier, implementation-readiness). I made no writes, started no workers or subagents, and made no paid calls.

---

# Design review 1: `docs/designs/batch-carry-over.md` (baseline 56b4c13, branch t3/batch-carry-over)

**Verdict: BLOCKED** (3 Blockers, 6 Majors, 4 Nits)

## Is it ready to build?

No. The transfer (one owner, export marker, carrying spend forward) is the right shape, and it reuses the existing paths: `batch.bind`, the holder, `job_config.install` and `restore_ledger`. Lines 139–146 honestly say what is missing at this baseline:
- the finding producer writes empty `eligible_operation_ids` / `failure_receipts` (`factory/diagnosis.py:326-330,347`);
- the dispatcher replays every finding as a hold (`factory/diagnosis_dispatch.py:256-266`);
- `budget._spending` accepts only schema-v1 factory_bug waste with `fix_commit` (`factory/budget.py:505-511`).

What blocks it:
- **No D seam is specified.** D is the stream that owns diagnosis and the factory-bug resume counter. The design names what D's resume step must do but never defines it.
- **The design ties resume to waste accounting.** It says the resume path waits for a separate, still-unwritten causal-receipt contract.
- **Two claims contradict the code.** The design says a replacement can carry forward and that no extra replacement appears after import. The manifest rules and the replacement journal refute both.

**Smallest concrete prerequisite (my recommendation).** Split the work into three increments. Only the first two are needed for the task's five requirements: same owner, cumulative spend, 3 lifetime resumes, authenticated history and one launch path.

1. **P0 (B, transfer only).** Build the export/import, `carry_from` and the money/holder/installer changes. Enable it only for deadline-stopped sources that are not held. Refuse any source whose card has `factory_bug`, `factory_bug_resume_count`, `terminal_stop: factory_bug_held` or a completed factory_bug `diagnosis_state`. No D code changes. This proves the owner, spend and history transfer offline, but does not close the row.
2. **P1 (D, resume admission, in `factory/diagnosis.py`).** One function, called from `diagnosis_dispatch._dispatch` before `replay()`:
   - it checks the retained finding against the *predecessor* binding taken from `job-money-history.json`;
   - it appends one history row in the existing `factory-bug-resumes.json` schema (`diagnosis.py:259-271`);
   - it clears the hold markers, or retires the case when 3 rows already exist.
   
   The eligible set stays empty. That means nothing historical is reclassified and `budget.py` does not change. stream-d explicitly allows this (`stream-d.md:400-407`: "the diagnosis can still hold a bug, but no historical charge is reclassified … This closes ordinary-budget headroom until those proofs exist"). Total spend is the same either way, because reclassifying waste never frees money.
3. **P2 (D, later).** Causal attempt→operation links in `infra-attempts.json`, schema-v2 waste in `budget._spending`, and growth from late settlement. This is needed for Item 8 scenario 5 ("charge waste once", `stream-d.md:3599`) and for the infra-waste line target in ENGINEERING §3. It is not needed for P0, P1 or the closure of new-batch-service-4 as the Murphy row is worded (`docs/murphy-register.md:67`).

---

## Blockers

### B1. A carried replacement cannot exist as written, and the one-child limit is not carried over
- **Severity:** Blocker
- **Scope:** lines 22–25 and 32–34 (`carry_from`: "Target job name must equal source job name"); `factory/batch_money.py:52`; `factory/batch_service.py:24-29,159`; interfaces §8 "Replacement derivation" (`interfaces.md:474-520`).
- **Finding:**
  - A replacement's job is a derived name `J-rN`. `check_manifest` rejects any root job matching `-r[0-9]+$`. Derived jobs resolve only through the holder journal's recorded derivation (`resolve_job`, "unrecorded derived job").
  - So a target manifest cannot contain `carry_from` for `J-r1` under the rule that target and source names match.
  - Separately, the one-child-per-parent latch is the per-batch holder journal (`interfaces.md:488-490`). A parent carried into a new batch has no derivation record there. On its next exhaustion it would derive a second child. That contradicts line 24 ("Neither import nor release change grants another replacement") and the "at most one child across all generations" rule (`interfaces.md:502-503`).
  - Item 8 needs both ("B's carry-over scope must cover both", `stream-d.md:3438-3440`).
- **Recommendation:** pick one and write it down.
  - **(a)** Carried derived jobs enter the target only through an imported derivation record: parent case/job, root, ordinal, child case/job and source generation, verified against the source journal. Every imported parent also imports its derivation latch.
  - **(b)** Replacement carry-over is out of scope for this increment. Refuse it explicitly, and say Item 8 scenario 5 stays blocked.
  
  Either way, add a test: a carried parent that exhausts again derives no second child.

### B2. D's resume seam is under-specified, and resume is tied to an undefined waste contract
- **Severity:** Blocker (fails the zero-decision rule; leaves the task's 3-resume requirement unreachable)
- **Scope:** lines 117–146.
- **Finding:** the design gives a sketch: "a worker function after job_config.install and before diagnosis_dispatch replay." The implementer would still have to choose all of the following:
  1. **File, name and signature.** Which predecessor binding the function receives, and from where. The finding stores `held_batch_id` / `held_release_sha256`. Today `_read_factory_bug_finding` requires both to equal the *current* batch and release (`diagnosis.py:328-329`). The design says "authenticate against the OLD binding" but does not say that check changes, or how the old binding is obtained. The only authenticated candidate is the `job-money-history.json` transition `old` entry (`job_config.py:106-114`).
  2. **Ordering against `carry_context`.** `run.py:3229` and `diagnosis_dispatch._dispatch` both copy `CARRY` keys, including `factory_bug`, `factory_bug_resume_count` and `diagnosis_state` (`diagnosis_dispatch.py:28,275-282`), from the checkpoint card back into `c.card`. Without a defined order, the hold comes back.
  3. **What "clear the active hold" means.** Exactly which fields: `terminal_stop`, `status`, the `factory_bug` card key, the `diagnosis_state` outcome, `infrastructure_gate`. `require_model_work` (`diagnosis.py:385-390`, called from `model_runtime.py:61-62`) refuses on *any* of `terminal_stop`, the `factory_bug` key or a completed factory_bug state. The design never names this guard, even though stream-d says B's addendum "must explicitly update that guard" (`stream-d.md:1483-1485`).
  4. **The history row's values.** `resume_id` creation, `source_generation` = `c.source_generation` (the input checkpoint), and which of `batch_id` / `job_id` / `reservation_id` come from the RAM config. The validator already requires `held_batch_id != batch_id` (`diagnosis.py:268`).
  5. **The literal `terminal_stop` and public card fields** for the fourth-finding retirement.
  6. **The write order** of history append vs. clearing the hold vs. checkpoint publication, and how replay recovers after a crash between them.
  
  Lines 142–143 also say "A reviewed D causal-receipt/replay contract is required before enabling the resume path." No such contract exists or is drafted. Taken literally, this design can never enable resume. stream-d already allows resume with an empty eligible set (see P1 above).
- **Recommendation:** specify P1 completely (items 1–6) in this design, or in a named D addendum reviewed before implementation. Move the causal-receipt / schema-v2 waste requirement to P2, and gate only Item 8 scenario 5's "waste once" acceptance on it. Keep line 144's ban on fabricated receipts.

### B3. The new durable state has no schema
- **Severity:** Blocker (zero-decision rule)
- **Scope:** lines 65–83 and 87–94.
- **Finding:** each of these needs fields, path, owner-only mode and a canonical digest rule, and none is given:
  - **Export marker** (line 65): path under `~/.unbug-control/batches/<source>/…`, exact field set, where admission paths read it.
  - **Target import receipt** (line 76): path, fields, what it hashes.
  - **Money-state representation** of "one imported initial floor and an authenticated prior source chain" (lines 79–80). Today `batch_money` rows carry `sources`, `acks` and `authority`, and `_post` requires `row['sources'] == [None]` for fresh work or an `acks[...]` entry for a resume (`batch_holder.py:161-175`). An imported row has neither. The implementer would have to invent the row shape, the meaning of `sources[0]`, and how `_source()` / `source_directory()` (`batch_holder.py:140-158,531-541`) return the *source* batch's `generations/<case>/<gen>` directory instead of the target's.
  - **Installer rules.** `job_config.install` refuses a changed `batch` / `batch_deadline` and any change to `committed_total_usd` (`job_config.py:86-87,101`), and sets revision to `saved+known` (`:102-103`). The design allows an increase and revision old+1, but does not give the replacement predicate, the history transition shape, or how the history key (`reservation/revision/source`) stays collision-free across batches.
- **Recommendation:** add an "Exact contracts" section with JSON shapes for the marker, the receipt, the imported money row and the cross-batch `job-money-history.json` transition. For each existing check being replaced, give the function and line, plus the new predicate. Reuse `carry_over.digest` for every canonical digest.

---

## Majors

### M1. A transfer-only launch of a held case leaves it stuck needing manual repair, not held
- **Scope:** lines 139–141 ("the dispatcher always holds").
- **Finding:** in the target batch, `replay()` → `restore_factory_bug` → `_read_factory_bug_finding` fails the `held_batch_id == authority.batch` check. That raises `diagnosis_finding_invalid`, and `dispatch()` maps it to `invalid(c)` (`diagnosis_dispatch.py:330-339`). This is a "check case" terminal stop that no code clears (`stream-d.md:1482`). Shipping P0 before P1 without a refusal would leave every carried held case stuck until an operator repairs it.
- **Recommendation:** fix the description. Require `carry_from` validation to refuse held sources until P1 merges, and test it.

### M2. Item 8 needs carry-over shapes this design rules out
- **Scope:** lines 8–9, 51–52, 82; `stream-d.md:3436-3449,3599,3600`.
- **Finding:**
  - Scenario 5's replacement is queued and "not launched under the fault". It has no acknowledged generation, card, ACK or deletion receipt. The design requires all of these (lines 44–46) and forbids an empty checkpoint (line 82).
  - Scenario 6 carries the original, after an extension, to the plumbing and science-replay releases. That source is neither held nor deadline-stopped, and may be sealed (line 51: "sealed cases cannot be revived").
  - The design admits the item-8 money clamp gap (lines 96–102) but not these two.
- **Recommendation:** state that this design does not unblock Item 8 scenarios 5 and 6. List the missing shapes (queued-only replacement; a running or sealed case rolling onto a plumbing or gate-version release, per ENGINEERING §3), or extend the scope.

### M3. Non-money job arguments can silently change across the transfer
- **Scope:** lines 29–36.
- **Finding:** `bind` takes `args` (including `--source` and `--rotation-slot`, which bind role families) from the target manifest job (`batch.py:138-151`). Nothing requires them to equal the source job's. Item 8 says "never silently change a saved candidate's role binding" (`stream-d.md:3533`).
- **Recommendation:** require the target job's non-money arguments to equal the source manifest's job byte for byte. Refuse any difference. Test it.

### M4. stream-d's owner rule is overridden but left unedited
- **Scope:** lines 21–22 and 156–158; `stream-d.md:452-455`.
- **Finding:** stream-d says cross-batch "same-owner … not reuse of the previous batch/job/reservation money owner. B issues the new owner normally." The batch-service backlog (`batch-service.md:1366`) and Murphy row 67 say "same owner". Deferring the doc edits to "when the implementation lands" means implementers and reviewers read two contradicting reviewed contracts, and D's validators are written against stream-d.
- **Recommendation:** update stream-d at lines 452–455 and 476–479 ("movement of an already-admitted resume into another batch belongs to B's reviewed cross-batch addendum"), and interfaces §8 ("D checks batch/job/case/deadline" becomes the transition predicate). Do it in this design change, before implementation, and have it reviewed with it.

### M5. Heilmeier gaps
- **Scope:** the whole document.
- **Finding:**
  - no plain-language objective (the "Problem" section is mostly identifiers);
  - no cost, which should be at least $0 model spend for offline work, and the real-artifact closure cost tied to Item 8's $100 request;
  - no timeline;
  - no mid-term exam that separates the P0, P1 and P2 checkpoints;
  - risks are spread through the text rather than listed.
- **Recommendation:** add short sections for all five. The mid-term exams are P0's offline transfer tests and P1's 1st/2nd/3rd/4th admission tests on real 5813be bytes. The final exam is the Item 8 scenario 5 real held transition.

### M6. Row closure depends on a run that itself needs this design
- **Scope:** lines 162–168 and 183–186.
- **Finding:** no real held or deadline-stopped card exists. I confirmed that `factory_bug_held` appears only in test code that writes states from saved 5813be usage. The only planned producer is Item 8 scenario 5, which itself needs this carry-over, plus B1 and M2. The design does not say this, so "close only when …" has no reachable route.
- **Recommendation:** name scenario 5 (and a deadline-stopped practice job) as the closure evidence, and the order: implement P0 and P1 offline with the row open, then close it on the scenario 5 artifacts. For each authored fixture in `test_batch_holder`, say which assertion it does *not* prove.

---

## Nits

- **N1.** Line 11: case identity also comes from the batch ID in `batch.bind` (`batch.py:141`) and `check_manifest` (`batch_money.py:53`), not only "batch_money". All three places need the `carry_from` exception.
- **N2.** Lines 153–154: `batch_carry_over.py` sits next to D's unrelated `carry_over.py` (legacy import). Pick a name that cannot be confused with it (e.g. `batch_transfer.py`), or put the code in `batch_holder.py`, which already owns source resolution. A separate module is justified only by B's integration seams.
- **N3.** Line 96: "Item 8 additionally requires …" is accurate, but it should cite `stream-d.md:3463-3477` (S+E, no regrant) so a fresh reader can check it.
- **N4.** Line 3 says the baseline is "factory-simplify 56b4c13"; the review runs on t3/batch-carry-over at 56b4c13. Say which branch the implementation is cut from (ENGINEERING §1 step 1).

---

## What holds up (no action)

- The export-first, one-way transfer, the lock order by batch ID, and the list of admission paths are complete against the code. The list covers `reserve` and its provider-wait path (`batch_holder.py:177-224,428`), `_post` (`:161`) and the legacy `authorize` (`key_holder.py:707`).
- The money rule uses lifetime totals: commitment ≥ collected floor, charged once at max(commitment, floor). It never grants a fresh budget. This matches interfaces §8 and §"Legacy import record".
- Keeping the operation UUID5 (`batch_holder.py:61`) makes lost replies idempotent.
- It reuses `_source`, `_snapshot`, `restore_ledger` and `job_config.install` rather than adding a second launcher, which satisfies the one-launch-path rule (ENGINEERING §4).
- Its refusals are honest. It does not invent receipts or historical waste, and it does not claim the Murphy row is closed.

**To unblock:** resolve B1–B3. Address M1–M6 or reject them with reasons. Then run a fresh design review per ENGINEERING §1.

## Implementation-agent disposition

The review is retained verbatim above. B1, B2 and B3 are accepted and remain open; no blocking finding is rejected or claimed fixed. M1–M6 and N1–N4 remain open. No implementation or activation is authorized by this review.

The proposed P0/P1/P2 split is review advice, not a task-scope change. The task explicitly includes ENGINEERING section 3's infra-waste rule, so completing P0/P1 without P2 would not complete the assigned work. A transport-only patch must not be presented as a factory-bug resume fix. Required D seam: predecessor-authenticated admission before diagnosis replay, durable lifetime counting with replay recovery, and code-backed replay-operation attribution compatible with settlement. Required B seam: carry imported replacement derivation/latch and queued-only owner authority without regranting the Item 8 allocation.

