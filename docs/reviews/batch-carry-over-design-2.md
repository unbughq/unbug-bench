**Verdict: BLOCKED.** Design 2 has 3 Blockers, 5 Majors and 4 Nits. It fixes most of review 1, but it does not yet resolve B1 (replacement lineage). It also opens a new money-regrant hole and leaves the crash-repair rule for D admission ambiguous.

This review was read-only, at baseline 56b4c13 on t3/batch-carry-over. I made no writes, started no workers or subagents, and made no paid calls. I read the three personas, the three standards, ENGINEERING.md, interfaces §8, stream-d's held lifecycle and Item 8, and the code cited below.

## How Design 2 does on review 1's Blockers
- **B1 (replacement lineage): partly resolved, still blocking.** Target manifests can now list explicit derived jobs, and the design promises an imported one-child latch. But the latch has no storage or schema, and it depends on derived-job support that does not exist at this baseline. See D2-B1.
- **B2 (D admission): mostly resolved.** It now names:
  - `diagnosis.resume_factory_bug(c)` and where it is called;
  - the exact card fields cleared;
  - the exact history row;
  - the fourth-finding literal;
  - the order: history is written before the card.
  
  Two gaps remain: where the predecessor's release comes from, and the exact crash-repair predicate. See D2-B3.
- **B3 (schemas): mostly resolved.** It gives schemas for `carry_from`, the snapshot, `export.json`/`import.json`, the imported money row and the header debit. The latch projection (D2-B1) and the restore input (D2-M3) are still missing.
- **Review 1 Majors:** M1 (held sources ending in `diagnosis_input_invalid`) is resolved by the admission step running before `replay`. M3 (job arguments must match) is resolved at line 85. M6 (closure route) is resolved at lines 271–276. M2 is acknowledged (lines 128–129). M4 and M5 are partly resolved.

The money rule is sound. The target's total equals the source's total, built from the imported per-owner maximum of held amount and known floor plus the carried debit. That means omitted owners and finished replacements cannot regrant money, and freezing the whole source batch removes the export-versus-admission race.

## Blockers

**D2-B1. Carrying replacements and queued children cannot be built at this baseline, and the latch has no specified storage.** Design lines 51–60, 86–90, 104–108, 151–152, 163–164.
- **Derived jobs have no money, holder or bind support yet.** Every path still looks jobs up directly in `record['jobs'][name]`:
  - `batch_money.channel` (`batch_money.py:98-99`)
  - `authorize_locked` (`:274`)
  - `validate_operations` (`batch_holder.py:54-55`)
  - `reserve` (`:180`)
  - `bind` (`batch.py:138-140`)
  - `job_config.install` (`job_config.py:69`)
  
  The shared resolver swap is still future work (`batch-service.md:835-839`: "before derived work is enabled"). `resolve_job` is used only in `batch_service`/`batch_status`.
- **So a source can never hold a derived row.** `load_locked` would reject any source money state with a derived row, which contradicts line 103 ("uses the existing validated state loaders").
- **The queued-only reservation (lines 53–55) has no workable entry point.**
  - It writes a money row into the source *after* line 34 declares source money immutable.
  - It has to happen before the snapshot digest is pinned in the target manifest. But `batch_transfer.prepare` runs only from the target's `holder.reserve`, after the target release already exists.
  - It also depends on the practice S+E clamp, which does not exist yet. The design says only that the clamp "must run BEFORE".
- **The "derived-latch projection" (line 152) has no path or schema.** The target journal's `_load` rejects derivation rows unless their `eligible_generation` entry and facts exist in the *target* journal (`batch_service.py:115-126`). And `_enqueue` looks only at the target `state['derivations']` (`:271-278`). Without a defined projection, a carried parent that exhausts again derives a second child.
- **Listing derived jobs in the target `jobs` map conflicts with interfaces §8** ("Do not insert mutable derived jobs into the frozen manifest/policy", `interfaces.md:517`), and nothing amends that rule.
- **Fix:**
  1. Define where imported latches live, for example an optional target-journal map such as `imported_derivations{parent_case: <the seven fields> + source_batch}` validated against `import.json`. Name its validator, and make `_enqueue` and the "claimed replacement" check (`:276`) consult it.
  2. Either put the resolver swap into this design's file list, or declare it a prerequisite and refuse derived or queued sources until it lands.
  3. Replace the post-freeze source reservation with a named pre-snapshot operator step under the clamp, or refuse queue-only children that have no money row and say Item 8 scenario 5 stays blocked on that.
  4. Amend the interfaces §8 wording.

**D2-B2. The legacy, holder-disabled path can regrant money or duplicate a case.**
- `HOLDER_ENABLED = False`, so the live path is `key_holder` calling `batch_money.authorize` (`key_holder.py:705-708`).
- For any job in `record['jobs']` with generation `new`, `authorize` mints `requested_total_usd` fresh, in schema-1 money state that has no carried debit (`batch_money.py:145-152`). With a `carry_from` manifest, that covers carried roots and listed derived names.
- The design makes `authorize` refuse only *exported sources* (line 162).
- Line 172 also removes `bind`'s same-release refusal, but does not keep it for the non-holder branch (`batch.py:161-167`), which reads `root/sealed`.
- **Fix:** legacy `authorize` and the non-holder `bind` branch must refuse any manifest that contains `carry_from`, and any listed derived name. Add a test for each.

**D2-B3. D admission crash replay and authentication are not deterministic.** Design lines 206–211 and 233–236.
- **Predecessor release.** Transitions in `job-money-history.json` hold `{old,new,config_sha256,source_generation}` and no release (`job_config.py:106-107`). "Authenticate held_release_sha256 against that historical binding" therefore has no source. Name it: the pinned `carry_from.policy.batch.sha256`, which must equal `checkpoint_card.batch_release_sha256`. For the multi-release chain, say how intermediate releases are authenticated (through each predecessor manifest's own pinned `carry_from`), or refuse spans longer than one transfer.
- **The append-ahead repair predicate** ("matching last finding/current binding") is ambiguous on the one state it exists for.
  - A checkpoint taken after history is appended but before the card is cleared is restored from a *new* input generation.
  - So `row.source_generation` never equals the current input. A literal reading strands the case as `factory_bug_history_invalid`.
  - Specify the exact predicate:
    - same `finding_id`, case, `held_batch_id`, `batch_id`, `job_id`, `reservation_id` and release;
    - `row.source_generation` equals the `old.source_generation` of the latest same-reservation transition in this run;
    - the public count equals the history length minus 1.
  - Also say that `_factory_bug_history` (`diagnosis.py:272-274`) accepts this only when called from `resume_factory_bug`, never from `persist_`/`restore_factory_bug`. Otherwise the current count check fails before any repair can run.

## Majors
- **D2-M1. Source writers after export are not all listed** (lines 156–158). Only launch retries, `authorize`, `reserve`, `_post` and `dispatch` refuse. These other source writers can still change source state after export:
  - `batch_service.plan` (it writes facts and derivations, `:302-308`) and `batch_service.collect`;
  - holder `collect`, `record_exit`, `record_child`, `reconcile`, `schedule_waits`, `orphaned`, `unpublished`, `publish_replay` and `resume_controller`.
  
  If they write, the source drifts from the pinned snapshot, and the "exact export repairs" step (line 152) then refuses forever, stranding the target. All of them must refuse under the source lock once `export.json` exists.
- **D2-M2. The second transfer is unspecified** (lines 104–106, 174–179). There are two gaps:
  - A job imported into B but never run there has no B operation or ACK. Its saved authority still belongs to A, so line 125 ("ACKed, bound to its operation authority") and the worker check against the "pinned old manifest" (line 193, which pins B) both fail. Say whether this is accepted (the `import.json` proof stands in for the ACK, and the predecessor authority chain is A→B→C) or refused.
  - "Recursive ancestor latches" needs a concrete one-level rule: each import was validated when it happened, so the next snapshot pins the source's latch projection and its `import.json`.
- **D2-M3. The restore input is undefined.** `launch.sh:748-749` passes only `--release-sha256 <target>` to `restore_ledger`, which hard-requires the release to match (`restore_ledger.py:131-135`). The design says it "accepts that exact original release" from `carry_from`, but it never says how `restore_ledger` finds the target manifest. The RAM config delivered at `launch.sh:716` is a candidate. Define the new argument or file and how it is verified.
- **D2-M4. Two ambiguities in the money rows.**
  - "Identical commitment" (lines 86 and 122): it is unclear whether the target manifest's `requested_total_usd` must equal the source authority's `committed_total_usd` or the source manifest's value, which can differ after a revision.
  - `overrun` is hard-coded to false (line 136), but `load_locked` requires `overrun == floor > held` (`batch_money.py:232`). Overrun sources must refuse.
  - Also state the import-time check that the source total fits within the target limit.
- **D2-M5. Heilmeier gaps.** There is no timeline (line 249 says "no live timetable"). Lines 37–38 claim the batch freeze "is sufficient for Item 8's sequential releases", which contradicts lines 58–60 and 128–129 (scenarios 5 and 6 are still blocked). The doc edits that review 1 M4 asked for are deferred: `interfaces.md:795` and `stream-d.md:476-479,488` still say that cross-batch support is "blocked on B's addendum".

## Nits
- `retired_factory_bug_limit` (line 216) is a new literal. It needs a status and attention mapping (`batch_status`) and a doc entry. Confirm that the top-level `status: running` literal (line 227) exists in the card grammar.
- Name the test files: new `tests/test_batch_transfer.py` and the diagnosis held tests.
- State that clearing the markers through the authenticated admission path is the guard update `stream-d.md:1484` requires, and not a bypass.
- Line 3: name the merge target (`factory-simplify`).

**To unblock:** resolve D2-B1, D2-B2 and D2-B3. Then address D2-M1 to D2-M5 or reject them with reasons, and get a fresh design review per ENGINEERING §1. The Murphy-row closure and Item 8 activation stay open, as the design says.

## Implementation-agent disposition for design 3

All three blockers and all five majors are accepted. Design 3 specifies imported_derivations and resolver integration; refuses unreserved queue-only imports instead of reserving after snapshot pinning; retains root-only manifests; explicitly refuses carry_from in legacy authorize/bind; and gives the release-chain and append-ahead history predicates. It specifies global source freeze guards, intermediate unlaunched-checkpoint refusal, authenticated restore config arguments, no-overrun/import-bound checks, and predecessor manifest bytes. Interface and stream-D addendum references are included. The nits are incorporated. These are proposed fixes pending a fresh reviewer, not self-verified closure.
