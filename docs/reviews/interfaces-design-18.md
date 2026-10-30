PASS

**Mode: REVIEW**, zoom_out + design_critic + implementation_readiness. Scope: `35659f0..HEAD` (873bcab), `docs/designs/batch-service.md:849-971`, `docs/designs/interfaces.md:339-480`. Read-only. I saved no files and ran no models, cloud or crypto.

**Prior blockers**
- **B1 (no facts sentinel): fixed.** `facts` is now `null` or `{exhaustion, actual_model_work, pending_projection}`, and only `null` means "unplanned". A stored `None` projection now replays, and "Stored facts win on replay" stops D being called again.
- **B2 (iff vs unknown-total resume): fixed.** "Queue an ordinary same-owner resume when pending_projection is present or the exhausted total is unknown." It no longer contradicts "always gets the same-owner settlement resume, even when pending_projection is None", and it matches interfaces §8, where unknown-total exhausted resumes take settlement priority.
- **M1 (unknown total never known): resolved, no cap added.** §8 refuses an unknown part with no mapped admitted maximum. A settlement-only resume makes no model call and cannot raise the commitment. So the loop is bounded by the commitment already held and by the deadline. This is consistent with "No extra attempt or call-count cap".
- **M2 (referenced ciphertext): fixed.** A referenced digest now requires `statement.age`/`search.age` and matching bytes. If the file is missing, collection refuses. Both suffixes are in `COLLECTION_SUFFIXES` (`factory/launch_manifest.py:107`).
- **N1: fixed.** A missing `case_budget` or a missing total means unknown, never zero.
- **N2: fixed.** With no archive field, the bound archive is the unique one whose digest matches. This matches `factory/collection.py:28-43`.
- **N3: fixed.** There are now named tests for the contradictory `true`-with-false-predicate case and for an expired deadline with injected `now`, and neither can create a request.

**New findings (no blockers)**
- **Nit: the B1 replay test isn't named.** `:957-960`: "unknown exhausted total with absent projection" and "replay without re-calling a changed draft module" are listed as separate tests. No test is named for replaying stored facts whose `pending_projection` is `None`, which is the exact B1 regression. Suggest naming it.
- **Nit: one contradiction direction is untested.** `:924-925` handles `replacement_eligible:false` with both predicates true by queuing no child, without refusing. The opposite case refuses. That asymmetry is a decision already made, not left open. But this direction has no named test, so it could drift unnoticed.
- **Nit (zoom_out reuse): an existing ciphertext check could be reused.** `factory/restore_sync.py:83,96-97` already compares `statement_cipher_sha256` with the `.statement.age` hash. The new collect check could share that comparison rather than restate it. This is optional, because the existing code is assert-based and works in the restore context.

**Heilmeier:** the objective, scope, risks, tests and next work are stated. Cost and timeline are implied by the increment (no money transitions, no VM changes), which is acceptable for a core increment. **Readiness:** the file targets, journal schema, API signatures, ordering, dedup keys and refusals are all specified, and the implementer has no design choices left to make.

Files checked: `/Users/bugsincode/.codex/RTK.md`, `docs/ENGINEERING.md`, `tools/egm/agents/{zoom_out,design_critic,implementation_readiness}.md`, `tools/egm/document_standards/{heilmeier-standard,implementation-readiness-standard}.md`, `docs/reviews/batch-service-design-9.md`, `factory/collection.py`, `factory/launch_manifest.py:107-148`, `factory/budget.py:410-425`, `factory/restore_sync.py:65-97`.

---

Elephant resolution: PASS accepted. Implement both named nit regressions: replay
with pending_projection None, and explicit replacement_eligible false with both
predicates true. Keep the small explicit digest check in the new verifier;
restore_sync's assert-based, context-specific path is not imported. No blocking
finding rejected; no enablement, VM change, spend or Murphy closure.

