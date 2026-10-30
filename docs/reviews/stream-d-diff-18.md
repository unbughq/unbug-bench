Review record: `docs/reviews/stream-d-diff-18.md`

**Verdict: FAIL — 3 blockers, 2 majors, no nits. All findings remain open.**

Fresh read-only Codex goldfish review, Mode: REVIEW, using the zoom-out and implementation-readiness personas and standards.

Reviewed commit `fcc11b851dece8c0063e0ce1af9bb64bcf439f42`, “Retain bounded extension state and immutable progress snapshots,” against parent `872151cd09e43e4b49bbe631b28dea6ad727ecce` on `t3/stream-d-implementation`.

Scope: `factory/extensions.py`, `tests/factory/test_stream_d_extensions.py`, `tests/tools/test_launch_manifest.py`, and the new “Extension state implementation boundary.” Requirements came from the passed extension eligibility/progress design, interfaces §8, and `docs/ENGINEERING.md`. Concurrent diagnosis/held-test drafts, `.stream-d-next`, and the queued-input amendment were excluded.

1. **Blocker — Pending execution can authorize an extension.**  
   Affected: `factory/extensions.py:200–223`.

   `propose()` checks that stress passed but does not reject pending stages elsewhere in the entry snapshot. A snapshot with stress passing and G1 pending passes proposal and admission, consuming extension ID 1.

   Reproduced using the committed fixture: set `snapshot(1)['stages'][1]['status'] = 'pending'`, then call the existing `begin()` helper. Admission succeeds.

   The design explicitly requires infrastructure/incomplete execution to finish retrying before entry. Reject pending entry evidence before admission, preserving the unresolved execution without consuming an ID. Add an admission regression test; the existing pending test exercises only `progress()`.

2. **Blocker — Historical progress can authorize a currently regressed case.**  
   Affected: `factory/extensions.py:212–221`.

   Further-extension eligibility compares the previous retained entry/outcome pair. The proposed current snapshot supplies only the version vector for selecting that pair; its case digest, frontier and previously passed stages are not checked against the selected outcome.

   Reproduced: complete extension 1 with frontier advancing from 3 to 4, change the current case bytes, and provide a same-version snapshot where stress passes but G1 fails. Extension 2 is admitted using the earlier successful comparison.

   This violates the requirement that earlier passes remain valid with current dependencies. Bind the proposed entry to the current evidence represented by the selected outcome/comparison, and refuse regression or unresolved differences before granting another ID. Preserve the original snapshots.

3. **Blocker — One completed diagnosis can authorize multiple extensions.**  
   Affected: `factory/extensions.py:206–223, 237–247`; the private-history schema in the new boundary.

   The proposal contains `exhaustion_id`, but admission drops it from private history. Nothing records which diagnosis authorized an extension.

   Reproduced: admit extension 1, complete it with progress, leave its completed `close_to_passing` diagnosis unchanged, then propose and admit extension 2. Both admissions use the same exhaustion ID; no later diagnosis occurs.

   A further extension requires another diagnosis. Retain the authorizing exhaustion ID privately and enforce one extension per completed diagnosis, while allowing replay of that extension. Document this binding and test both repeated admission and a genuinely new exhaustion.

4. **Major — Restored state can roll cumulative rounds backward.**  
   Affected: `factory/extensions.py:101–108, 222, 237–247`.

   `read()` validates each round only as a positive integer. `propose()` derives the next round solely from `c.card['builder_rounds']`, without checking retained history.

   Reproduced:
   - After completing extension round 9, resetting the restored card counter to 0 permits admission of extension round 1.
   - Changing retained rounds from `[9, 10]` to `[9, 1]` is accepted by `read()` without changing the public projection.

   Validate cumulative round ordering and consistency with the restored counter. A counter behind retained history must be reconciled through an explicit replay rule or refused; it must not mint a lower round and reuse an earlier `builder-N` identity.

5. **Major — Interrupted history publication cannot replay.**  
   Affected: `factory/extensions.py:123–126, 190–192, 230–236, 255–263`.

   `_write()` durably publishes private history before updating the public projection in memory. If interrupted between those steps, `read()` rejects the previous public projection rather than recognizing the committed transition.

   Reproduced by interrupting immediately after the real `atomic_json()` write:
   - An admitted private entry with the previous empty public history causes `active()` to raise `extension_history_invalid`.
   - A durable completed outcome with the previous active public projection causes replaying the identical `complete()` call to raise the same error.

   Define recovery for these precise publication windows. Reconcile only a verified committed admission/completion transition, retaining strict refusal for unrelated mismatches. Add interruption tests for both transitions.

**Verification and boundaries**

Tests ran offline from a clean `git archive` export of the exact reviewed commit:

- `rtk proxy python3 -B tests/factory/test_stream_d_extensions.py` — **5 tests passed**.
- `rtk proxy python3 -B tests/tools/test_launch_manifest.py` — **2 tests passed**.
- Two inline Python replay harnesses using the committed extension fixture reproduced the findings above. Additional checks confirmed that pending outcomes remain active and completed no-progress outcomes refuse another extension.

The fixture verifies saved practice-file hashes and loads the saved 5813be continuation ledger. Stage receipts, bindings and lease controls are openly authored. These tests establish offline state behavior, not live gate qualification.

The implementation correctly uses stress followed by actual `run.GATES` order, retains original snapshots during version comparisons, preserves snapshots through the tested repair invalidation, and enforces the normal five-ID limit. It reuses existing budget reservations and atomic JSON persistence. The documented exclusion of runner wiring, snapshot production, changed-gate evaluation and money admission is appropriate.

No full-suite result is claimed; the writer will run it at the stable next SHA. No Murphy row closes. No model, cloud, launch or decryption workload ran. No worktree files or commits were changed; this review text was not written to disk.

## Elephant resolution

All five findings accepted. Pending entry stages must refuse before an ID;
the current snapshot must match the retained compared outcome (generation
lineage may advance, but case, ordered stage bindings and evidence may not).
Private history binds each extension to a unique authorizing exhaustion ID.
Rounds are consecutive and cannot move behind durable history. Publication
replay accepts only the verified immediately preceding public admission or
completion projection, with retained reservation and snapshot checks; unrelated
mismatches still refuse. Regression tests cover all five reproduced paths.
The 83ebec3 suite was stopped as superseded; no result is claimed from it.
