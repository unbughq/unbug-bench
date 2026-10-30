**FAIL.** There are two blockers, both in the queue transition, and each needs about one sentence added to the design. The rest of the increment is well scoped. Its reuse claims match the code, the gate design holds no hidden authority, and nothing in it bypasses the gate.

### Blockers

**B1: an unknown-total parent can leave a child that never unblocks** (`batch-service.md:908-922`)
- The text queues a child when `exhaustion ∧ actual_model_work` holds and no projection says `replacement_eligible:false`. It queues the same-owner (settlement) resume only if `pending_projection` is present.
- Suppose D returns `exhaustion=True`, `actual_model_work=True`, `pending_projection=None`, and the card's total is null. The child is queued and marked `unknown_total`, but nothing that could settle the total is ever queued. The child stays blocked forever.
- This contradicts the stated contract in `:784-791` and interfaces §8 (`:370-375`): an unknown-total exhausted parent is put in the settlement class.
- The fix is one rule. Either an unknown total always queues the same-owner settlement resume whatever the projection says, or that combination refuses the entry as a D contract violation.
- Add the combination to the "absent projection" test.

**B2: what `plan` does on replay is undefined** (`:897-913`)
- "Persist D's returned facts" and "preserve the original API projection verbatim" do not say what happens when `plan` runs on an entry that already holds facts. This happens after a restart, or when the draft D answers differently.
- The implementer has to choose between three behaviours:
  - return the stored facts without calling D;
  - call D again and refuse if the answers differ;
  - overwrite.
- Pick one. Refusing on a mismatch, with the stored facts winning and no new requests, fits the immutable-snapshot rule. Also add the `state` value an entry moves to once its facts are persisted. Today only `'pending'` is defined.

### Majors (must be pinned down; each is one phrase)

- **M1: the null/known total field is not named** (`:921-923`). Name `case_budget.total_spent_usd` (interfaces `:341`) as the only field B reads. Otherwise the implementer may read spend from somewhere else.
- **M2: the ciphertext digest fields are not named** (`:870`).
  - The card's `statement_sha256` is the digest of the plaintext (`run_artifacts.py:83`). Comparing `statement.age` against it would refuse every real card.
  - The ciphertext digests are `statement_cipher_sha256` (`:87`) and `public_search.cipher_sha256` (`:95`). Name these.
  - None of the 51 saved cards in `sealed/` carries the statement field, even though 37 `.statement.age` files exist. So the "unreferenced → copy unchecked" path is the common case and needs a test.

### Nits

- **Two journal shapes.** The new `journal.json` schema (`:880-882`) and the earlier entry shape (`:40-46`, keyed `fresh` with fields like `operation_id`) describe the same path. Say that schema 1 supersedes the earlier shape for this increment.
- **Check what `verify` returns.** `collection.verify` silently skips probe and startup cards. `collect` should also assert that `verify` returns exactly `{case}`.
- **Siblings.** "Preserve all available allowlisted siblings" (`:871`) would copy the alternative archive that the card does not bind into the "verified" snapshot. Either exclude it or say that it counts as a conflicting generation.
- **Root names ending in `-rN`.** `batch_money.check_manifest` still accepts a root named `j-r1`, which collides with J's first child. State that `collect`/`plan` call `resolve_job` for every job, root jobs included, so the grammar refusal always applies.
- **Contradictory D answers.** For example, `replacement_eligible:true` while `actual_model_work=False`. The text produces no child; say whether that combination should instead refuse as a contract violation.
- **Deadline clock.** For the deadline refusal, take `now=` the same way `batch_money.authorize` does.

### What I checked

**Files read:** the persona and standard files, `ENGINEERING.md`, and the diff `6abe169..49f5fac` (`batch-service.md`, +99 lines, and `interfaces.md` §8, +19 lines). I checked these against the earlier contract at `batch-service.md:764-845` and interfaces `:336-405`.

**Reuse holds against the code:**
- `batch_money.manifest`/`locked`, `collection.verify`, `transfer.digest`, `registry.atomic_json` and `launch_manifest.collection_files`/`COLLECTION_SUFFIXES` all exist with the signatures the design assumes.
- `factory/*.py` is already in `WORKER_GLOBS`.
- `TRUSTED_FILES` and the explicit worker list in `tests/tools/test_launch_manifest.py:80-86` are the right two places to edit.

**Gate and authority:**
- The tracked `False` constant has no environment flag, imports D lazily, and nothing in production imports D.
- No money transition, launch, grant or dispatch API is added.
- The fresh-only authorizer (`batch_money.py:141`) and the root-only holder/bind/installer lookups are explicitly left unchanged.
- `resolve_job` is a pure template resolver, not a grant.

**Time-of-check races and replay:**
- `collect` copies into a stage, hashes and fsyncs, then verifies the staged copy and publishes by atomic rename.
- An existing generation must match exactly.
- A crash between the rename and the journal write is repaired by replaying `collect`.
- Replay and planning re-verify the snapshot.
- D's projection never arrives as a caller argument.

**Lineage:**
- Derivations are keyed by the immediate parent's case, with ordinal parent+1, persisted before any request.
- The same child is returned across generations and extensions; a changed lineage or a claimed ID refuses.
- This gives J → J-r1 → J-r2.

**Test plan:**
- The authored API and batch-binding answers are labelled as contract-only.
- Missing D is stated as an enablement blocker, never a passing D integration claim.
- No Murphy rows are claimed closed.
- There is precedent for real cards with authored archive digests (`tests/factory/test_invalid_runs.py:287-300`). Archives are git-ignored; 13 real casekeys are tracked.

**YAGNI:** the scope stops before outbox, pointers, holder, restore and dispatch, which is acceptable for a staged core. No new service, launcher, dependency or ledger is added.

I made no edits and ran nothing beyond read-only git and file inspection. The writer should save this verbatim to `docs/reviews/batch-service-design-7.md` and `docs/reviews/interfaces-design-15.md`.

---

Elephant response: all findings accepted. Always queue an exhausted unknown-total owner's settlement resume even without pending_projection. Keep launch state pending; persist facts atomically with queue changes and replay them without calling D again. Name the one total field and both ciphertext digest fields. Exclude the unbound alternative archive; require verify=={case}; enforce root grammar on every resolver call; strict contradictory eligibility refuses; now= is injectable. No rejected findings or row closures.

