**Review: stream-d diagnosis-input design 3: PASS**

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, using the zoom_out, design_critic and implementation_readiness personas and their named standards.

**Scope:** `docs/designs/stream-d.md:1247–1413`, “Queued diagnosis inputs (review-17 follow-up),” pinned to `74d3fb4ec7e1fb6992849744720597dd5a45b4e2`, cumulative `fab9014..74d3fb4`, on `t3/stream-d-implementation` in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.

Read `stream-d-diff-17.md` and `stream-d-diagnosis-input-design-{1,2}.md` verbatim, including elephant responses. Checked the amendment against ENGINEERING, the surrounding diagnosis/held design and interfaces §8. Supporting code inspection checked feasibility and reuse. The extension helper was inspected only to validate the referenced history reader and snapshot checks.

HEAD advanced to `83ebec3` during review. The scoped design, interface and prior-review documents are unchanged between that commit and the pinned commit. The new implementation commit, excluded implementation drafts and `.stream-d-next/` are outside this review.

**Findings**

- Blockers: none.
- Majors: none.
- Nits: none.
- No finding is rejected or left unresolved within this design scope.

**Resolution of prior findings**

1. **Review-17 Ma2: immutable replay — resolved.**  
   The manifest fixes the exact input inventory and digests. Result validation and finding replay use that frozen root rather than live work. Its generation remains the original authenticated input generation across later checkpoints. Live-ledger growth therefore cannot invalidate an intact retained finding.

2. **Review-17 Ma1 and round-one B1: terminal refusal lifecycle — resolved.**  
   Both input-invalid and history-invalid stops explicitly produce false exhaustion, no pending projection and no fresh exhaustion ID, including with a retained infrastructure marker. Invalid inputs preserve diagnosis state. Damaged held history preserves the finding and public factory-bug marker while removing the derived count. Recovery cannot automatically reset either stop.

3. **Round-two B1: missing manifest after binding — resolved.**  
   Inspection precedes cleanup and finding validation. A finding, raw result, completed diagnosis state or retained diagnosis reservation prevents re-staging and requires `diagnosis_input_invalid`. Initial and repair reservation names bind the check to the exhaustion ID using existing ledger metadata. Only a genuinely unbound pending attempt may discard orphan staging and inputs. This preserves the legitimate pre-manifest crash recovery without replacing already-used evidence.

4. **Round-two Ma1: producer-specific evidence — resolved.**  
   G4/G6 late defects use the existing `late-defect.json`, checked against the authenticated card’s gate and canonical digest. Extension exhaustion requires a completed outcome, retained snapshots and agreement with the public §8 history projection. `extensions.read` provides the referenced private-history, snapshot and projection checks. Infrastructure exhaustion uses its authenticated marker; budget/stress exhaustion uses pending state and ledger. Gate-detail files are supplemental.

5. **Round-one evidence and source selection — remains resolved.**  
   The design reuses `gate_state.inventory`, retains restored bench results and requires cache references to resolve with matching hashes. Source selection follows the authenticated batch-release → worker-release chain and existing worker path mapping. It requires selected source digests without repeating tool qualification or assuming unshipped files exist.

6. **Isolation, durability and scope — sufficient.**  
   Same-filesystem staging, durable publication before invocation, quiescence, unsafe-path refusal and the diagnosis role’s readable-root restriction are explicit. The amendment introduces no runtime activation, dispatch, money authority or public RAM configuration change. Storage cost is identified as a measured fixture subtotal, not a full private-archive measurement.

**Required implementation tests**

These remain requirements, not reported results:

1. Freeze inputs, persist a finding, interrupt public completion, append live usage and replay without a model. Verify unchanged finding, frozen bytes, exhaustion ID and original generation.
2. Remove the manifest after interrupted finding persistence and after a completed hold. Repeat with raw-result-only and reservation-only evidence, including repair reservations. Assert refusal before cleanup, preserved evidence, no model work and the complete input-invalid lifecycle.
3. Prove genuine unbound pre-manifest orphan re-staging succeeds after live settlement. Unsafe parents must refuse without following them.
4. Cover malformed manifests, case/ID mismatches, missing/null/mismatched initial generation, and missing, changed or extra frozen files. Assert stopped/input-invalid, false exhaustion, None projection and no replacement ID, including with infrastructure markers.
5. Accept valid G4/G6 late-defect receipts without gate-detail files. Reject missing receipts, wrong gates and digest mismatches.
6. Accept a completed extension outcome matching the authenticated public projection and immutable snapshots. Reject missing/incomplete outcomes, projection mismatches and damaged retained snapshots.
7. Cover infrastructure exhaustion without detail files, budget/stress minimum inputs, gate-cache reference resolution, restored/current bench-copy agreement and release-source digest failures.
8. Verify replay across later authenticated source generations retains the original manifest generation.
9. Verify history-invalid behavior before and after completed hold: no projection or fresh ID, preserved finding/marker, removed derived count and continued held-dispatch refusal.
10. Verify snapshot exclusions, selected-file safety and publication ordering before any diagnosis reservation or invocation.

**Validation boundary**

PASS applies to design readiness only. No files were written, tests or workloads run, archives decrypted, or suite result claimed. No Murphy row closes. Dispatcher activation and implementation correctness still require their separate tests and diff review.

## Elephant resolution

PASS accepted. Implement and test the named snapshot and refusal cases before
dispatcher wiring. No authority, runtime enablement or Murphy closure is claimed.
