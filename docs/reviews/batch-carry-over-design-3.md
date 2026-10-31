**Verdict: BLOCKED.** Design 3 fixes nearly all of review 2. One blocker is still open: D2-B2, the legacy path that has the holder disabled. Design 3 also adds 4 Majors and 5 Nits. The disposition says the legacy refusal was added, but the design text does not contain it.

This review was read-only at baseline 56b4c13 and the working-tree docs. I made no writes, started no workers or subagents, and made no paid calls. I read the three personas, the three standards, ENGINEERING.md, interfaces §8 (lines 505–525) and both appended addenda, plus the cited code.

## How Design 3 does on review 2's findings

| Finding | Status | Where |
|---|---|---|
| D2-B1 (latch storage, resolver, queued reserve) | Resolved, except one queue gap (D3-M2) | `imported_derivations` schema and validation at 130–141; resolver swap at 60–67; refusal of unreserved queued children at 52–58; root-only manifests at 97 |
| **D2-B2 (legacy path)** | **Not resolved** (D3-B1) | — |
| D2-B3 (D admission replay) | Resolved | Release chain at 260–270; append-ahead predicate at 296–306, which matches what review 2 asked for; the `admitted_replay` parameter is passed only by `resume_factory_bug` |
| D2-M1 (source writers after export) | Resolved | Central freeze in `locked`, with the reader guards listed at 192–202 |
| D2-M2 (second transfer) | Partly resolved | Ancestor latches pinned one level at a time (122–126), but the unlaunched-import case is unstated (D3-M3) |
| D2-M3 (restore input) | Resolved | 227–241 |
| D2-M4 (money ambiguities) | Resolved | 102–106, 163–165 |
| D2-M5 (Heilmeier gaps) | Resolved | Timeline at 317–320; the "sufficient for Item 8" contradiction is gone (38–39); addenda added |

The money envelope, the export commit point and the D contract are sound:
- Same continuing case with a new reservation.
- Empty causal sets until a separately reviewed attribution exists.
- At most 3 lifetime admissions; the fourth is `retired_factory_bug_limit`.
- The existing history grammar is reused (`diagnosis.py:259-269`, which already requires `held_batch_id != batch_id`).

## Blocker

**D3-B1. The legacy path with the holder disabled can still give a carried case fresh money or start it twice, and the resolver swap makes this wider.** Design lines 61–64, 201, 206 and 215–216.
- `HOLDER_ENABLED = False` (`batch_holder.py:26`). So the live path is `key_holder.py:705` → `batch_money.authorize`.
  - `batch_transfer.prepare` only runs from `holder.reserve`, which `enabled()` refuses. The import therefore never runs on the live path.
  - A `carry_from` target launched as `new` reaches `authorize` (`batch_money.py:145-152`). It mints the full `requested_total_usd` in schema-1 state, with no carried debit, under the continuing source case id.
  - The result is a money regrant plus a duplicate fresh start of a case that already has history.
- Line 61 sends the legacy `authorize` lookup through `resolve_job`. That removes today's `name not in record['jobs']` refusal for derived names. Line 64 requires `_lineage`, but the legacy path has no journal to check it against.
- Line 216 removes `bind`'s same-release refusal everywhere. That includes the non-holder branch (`batch.py:163-167`), which reads `root/sealed`.
- Lines 201 and 206 refuse only *exported sources*, which is the same gap review 2 flagged.
- **Fix:**
  1. Legacy `authorize` and the non-holder `bind` branch must refuse any manifest that contains `carry_from`, and any derived name.
  2. Keep the same-release check in the non-holder branch. Only the holder initial-import branch drops it.
  3. Add one test for each refusal.

## Majors

- **D3-M1. The design does not say how the target reads the frozen source.** Lines 192–194 and 209–211.
  - After export, `locked(source)` refuses everyone except "batch_transfer's read/repair transaction and read-only status".
  - But target `_source`, `_post` and `source_directory` must read the original source's ACK, `current/`, `outbox/` and generation directory.
  - The design should name the mechanism. Two options: these calls go through a `batch_transfer` reader that uses `read_export=True`, or they read the immutable files with no lock. Otherwise the implementer must choose, and the default makes every imported launch fail.
  - The same applies to `sources[-2]` at `batch_holder.py:174/219`. An imported row has `sources == [generation]` (length 1), so this index fails. The imported-base exception should name these two lines.
- **D3-M2. An imported queued child has no queue representation.** Lines 52–58, 135–138 and 212–213.
  - The design says "Queued import launches empty once through the ordinary path". But target `_load` validates a replacement queue row against the local `state['derivations'][parent_case]` (`batch_service.py:137-141`). That raises an error for an imported latch.
  - The design also says imported parents emit no queue entry, and imported entries do not enter the target. So nothing ever schedules the child.
  - Fix: either write a target queue row at import, and allow `_load` to validate replacement rows against `imported_derivations`, or say that queued children are refused until the derived-job scheduler exists.
- **D3-M3. A second transfer of an import that never launched is undefined and strands the case.** Lines 156–158 and 218–223.
  - Take A→B where B's launch fails before creation, which is plausible when the "fix" release is itself broken. B then has no local ACK for the imported generation.
  - Line 157 requires "ACKed", so B→C refuses. The owner stays charged in the debit forever, and the case can never continue.
  - Fix: either accept B's `import.json` proof plus a failed-before-creation operation as the ACK for re-export, chaining authority A→B→C, or state explicitly that this is refused and that the case retires.
  - Review 2's disposition claims an "intermediate unlaunched-checkpoint refusal", but no line in the design says this.
- **D3-M4. The resolver swap is narrower than interfaces §8, which the design says it implements.** Line 60 versus `interfaces.md:516-521`.
  - Missing from the swap: removing the root-count caps (`check_manifest` at `batch_money.py:43-44` and `key_holder.policy_load:126`) and the orphan-resume `policy_job` membership check (`key_holder.py:606`).
  - Also left as direct root lookups: `account_handoff.py:155` and `coordinator_inventory.py:72`.
  - Fix: list each of these as in scope or deferred. If one is deferred, say the derived import refuses wherever that path would see a derived name.

## Nits

- Line 290 says "status running", while line 334 says to omit status if `running` is not accepted. That leaves the choice to the implementer; pick one card convention.
- `tests/factory/test_stream_d_diagnosis.py` does not exist. The held tests live in `tests/factory/test_stream_d_held.py`; name it.
- The snapshot requires schema-2 money state. Today's live (legacy) held cases are schema 1, so no current real source can be transferred until the holder is enabled. Say so, which makes it clear these sources refuse rather than migrate.
- Say whether `resume_factory_bug` runs before or after `_dispatch`'s `INVALID` stop and the `_state` check (`diagnosis_dispatch.py:288-291`).
- Note that the source checkpoint's VM `restore_recipient` must equal the target's. A rotated control recipient would make the restore fail.

**To unblock:** fix D3-B1, then address D3-M1 to D3-M4 or reject them with reasons, and get a fresh design review per ENGINEERING §1. As the design says, the Murphy row `new-batch-service-4` stays open, and real-artifact closure and live Item 8 activation stay separate gates.

## Implementation-agent disposition

D3-B1, M1–M4 and all five nits are accepted. The Design 4 exact integration decisions section now explicitly supplies the legacy refusal, frozen-source reader/imported-base exception, imported queue schema, re-export refusal, complete resolver file list and exact nit decisions. These proposed fixes await fresh review; no blocker is self-verified.
