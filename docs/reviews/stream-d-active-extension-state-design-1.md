**FAIL: 0 blockers, 2 majors, 2 nits.** The core rule is sound, but the design doesn't say what happens to one public fact, and the test plan skips one of the two failures it names. Below is my summary, then the text ready to save.

- **What holds:** checking the old diagnosis against the history as it stood just before admission (dropping only the active last row) keeps the legitimate state valid. It does not create a new exhaustion: `record_exhaustion` still checks the full history and won't mint an ID while an extension is active. The private check (same exhaustion ID, checked against the verified history rather than the card's possibly stale copy) handles a public history that is one write behind. Completed histories and the next new ID still work.
- **Major 1:** once the state is valid, `diagnosis.exhaustion()` becomes True for an active card whose stop is `infrastructure_exhausted` or `budget_exhausted`. Today it is False. `batch_service` then queues a "settlement" resume when the money total is unknown. The design never mentions this, which leaves the implementer a decision and touches the money/queue question.
- **Major 2:** the design names the dispatcher refusal as a symptom, but the test plan only tests `finalize_accounting`. Nothing proves the dispatcher now replays to `extension_comparison_pending`.

---

```markdown
# Review: stream-d active-extension-state design 1. FAIL (0 blockers, 2 majors, 2 nits)

Mode: REVIEW, a fresh read-only goldfish. Personas: zoom_out, design_critic and
implementation_readiness. Standards: Heilmeier, implementation readiness, zoom-out.
Scope: 40e6b7e..2c97742 (`docs/designs/stream-d-active-extension-state.md` plus the
parent pointer in `stream-d-worker-dispatch.md`). No production code changed.

## Files read
- docs/ENGINEERING.md; tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md;
  the three standards.
- factory/diagnosis.py: `extension_history`, `_trigger`, `_state`, `exhaustion`,
  `pending_projection`, `record_exhaustion`, `_held_context`, `_verify_input_records`,
  `_input_stop_evidence`, `queued_inputs`, and the FileNotFoundError-only readers.
- factory/extensions.py: `public`, `read`, `propose`, `verify_proposal`, `admit`, `complete`,
  `retain_comparison`.
- factory/run.py: `pending_call` (323–375), `inherit_recovery_history`, `finalize_accounting`,
  and where `exhaustion_occurred` is set.
- factory/diagnosis_dispatch.py: `stop`, `apply`, `replay`, `carry_context`, `_dispatch`.
- factory/batch_service.py: `_facts`, `_project`, `_replacement`, `_enqueue`.
- tests/factory/test_stream_d_extensions.py, and test_stream_d_runtime.py:228–247
  (the held/active control).
- docs/reviews/stream-d-extension-admission-design-2.md.

## What holds
- **The earlier-history check is correct and narrow.** The exception applies only when the
  state is completed, the outcome is `close_to_passing` and the last public row is active.
  The public schema allows an active row only in the last position, so dropping that row
  gives exactly the history as it stood before admission.
  - An `extension_incomplete` diagnosis with no earlier completed row still fails, because
    the earlier history is empty.
  - A late-defect diagnosis still needs a valid gate, a positive round limit and
    `builder_rounds >= rounds`. The active-row condition is met by construction.
  - Pending diagnoses, `factory_bug` and `not_converging` keep checking against the full
    history, so the factory_bug/active control (runtime:228–247) is unchanged.
- **No new exhaustion while an extension is active.** `_trigger` is unchanged.
  `record_exhaustion` still checks the full history and returns at its active-row guard
  (diagnosis.py:132–133), even with `new_exhaustion=True` and an infrastructure stop.
  `pending_projection` returns None before it reads the state.
- **The completed lifecycle still works.** After `complete`, all three possible original
  stops still pass against the full history, so the diagnosis stays valid.
  - `propose` refuses `extension_diagnosis_already_used`.
  - A new literal `extension_incomplete` with `exhaustion_occurred=True` mints one pending
    ID through the existing path. A second finalization keeps that ID (diagnosis.py:119).
- **The private ID check handles a lagging public history.** It runs on `projected`, which is
  rebuilt from verified private rows. That covers a crash after the durable history write but
  before the card was updated (pending_call:361; the existing interruption test).
  - In the lagging case, `builder_rounds` may still hold `round-1`. That count was already
    at or above the round limit when the diagnosis was made, so late-defect origins still pass.
  - `admit` replay, `complete`, `active`, `propose` and the dispatcher's `extensions.read`
    all go through `read`, so they all get the check.
- **Frozen diagnosis inputs are unaffected.** `_verify_input_records` and
  `_input_stop_evidence` read the frozen card from before admission. Its last private row
  is completed, so the new check never fires there.
- **No new field, schema or launch authority.** The design is the right size and adds no
  speculative mechanism.

## Major 1: the design doesn't decide the public `exhaustion()` value while an extension is active
Affected: the "Public state rule" section; diagnosis.py:71–84; batch_service.py:76–86 and 248–280.

Today every active card has an invalid `_state`, so `exhaustion()` returns False at
diagnosis.py:80. With the new rule the state is valid, and `exhaustion()` returns
`infrastructure_exhausted(card) or _trigger(card, stop, full_history)`. That is True when the
stop is `infrastructure_exhausted` (a stop the design's own test list uses) or
`budget_exhausted`, or when an infrastructure marker is retained under
`extension_comparison_pending`.

`pending_projection` stays None, so no replacement is queued. But `_enqueue` line 278
(`facts['exhaustion'] and unknown`) now queues a `resume/<case>/<generation>` request
labelled "settlement" for an active-extension card with an unknown money total. Before this
change, no such request was queued.

The design says this is "not money authority" and "pending_projection stays None", but never
mentions `exhaustion()` or the batch facts. That leaves the implementer a decision and changes
a queue fact next to money. Fix: state the intended value and test it.
- **Recommended:** keep today's result by returning False from `exhaustion()` when the last
  public row is active (the same guard `pending_projection` already has), and assert the
  facts are unchanged.
- **Alternative:** accept the settlement resume explicitly, and add `_project`/`_enqueue`
  assertions for an active card with both a known and an unknown total.

Smaller related change: during an active extension, `propose` now refuses with
`extension_already_active` instead of `extension_diagnosis_required`. That is more accurate.
List it as intended so a later test doesn't treat it as a regression.

## Major 2: the dispatcher failure is named but not tested
Affected: the "Tests and artifacts" section.

The problem statement names two failures: a cleanup error in `finalize_accounting`, and the
dispatcher refusing "before it even reads the private extension history"
(diagnosis_dispatch.py:286). The test plan only exercises `finalize_accounting`.

The dispatcher path now continues through carry → `extensions.read` (with the new check) →
`queued_inputs` → `_verify_input_records` on the frozen inputs → `replay` → `apply`. It should
stop at `extension_comparison_pending`, not `diagnosis_input_invalid`.

Fix: for both origins, add a replay with the retained decision through the existing
`test_stream_d_dispatch` harness (real practice bytes, 5813be ledger), with the extension
active.
- Assert the stop label, the unchanged diagnosis and history, and that no reviewer or writer
  runs.
- Add one control where the card's diagnosis UUID no longer matches the active row. It must
  refuse and leave the private history and snapshots unchanged.
- This also proves that the second-extension origin's frozen `extension_incomplete` evidence
  (which reads the frozen work tree) still verifies after a later admission.

## Nits
- **N1. The narrowed exception still has an unclassified case.** After narrowing to
  FileNotFoundError, a directory or wrong-type file at `extension-history.json` or the ledger
  path raises IsADirectoryError or ENOTDIR, which would propagate as infrastructure. There are
  two precedents: the diagnosis readers (FileNotFoundError only) and `verify_proposal` (treats
  ELOOP/ENOTDIR/ENXIO/EISDIR as semantic). Name which one applies here, and add one directory
  control to the malformed-record tests.
- **N2. The order of the new check inside `read` is not stated.** Every refusal in `read`
  happens before `c.card['extension_history']` is assigned, so any order is safe. Stating
  "after the lag check, before the assignment" removes the last implementer choice.

## Scope confirmation
These items stay open, and the design doesn't block them: the original B1 active continuation,
B2 isolation, M5 stage evidence, M6 routing, and the crash window where the history is written
before the writer receipt (durable writer intent). No Murphy row closes. `DIAGNOSIS_ENABLED`
stays false. The existing money checks (reservation before admission, batch money above the
ordinary limit) are untouched.

## Validation boundary
Static reading only. I wrote nothing and ran no tests, suite, launch, models or decryption.
`.stream-d-next/` was excluded. The parent full suite on 9ec3a12 was running separately and its
result was not seen. All behaviour claims come from reading the code at 2c97742.

## Elephant response *(to be completed by the elephant)*
```


## Elephant response

Both majors are accepted. The revised design explicitly returns false from exhaustion for every active public history and tests dispatcher replay for both origins. N1 follows the existing diagnosis reader precedent: wrong-type paths propagate as infrastructure, with a directory control. N2 places the binding check after the lag check and before public assignment. No findings are rejected.
