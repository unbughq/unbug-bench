Mode: REVIEW — **BLOCKED on implementation readiness; the carry architecture is supported.**

**Blocker — `docs/designs/practice4-checkpoint-carry.md:35–63`: Make the execution scope explicit.** The plan does not name the complete file changes or define the positive artifact-acceptance test. Under the implementation-readiness standard, an implementer must currently choose these.

Smallest correction: add a short implementation checklist naming:

- New `factory/batches/b-plumbing-practice-4.json` and its decisions file, preserving the original decision text and timestamps.
- Updates to `factory/practice.py`, `factory/practice_preflight.py`, `control/unbug-practice-cleanup@.service`, `docs/designs/practice-run.md`, and the existing transfer/readiness tests.
- Keep an independently fixed `EXPECTED` literal for -4. Loading it from the same manifest would make the existing exact-contract comparison self-referential; release authentication alone does not preserve that independent restriction.
- Use the retained full `practice3-transfer-source-public.json` snapshot, original policy/release and collected smoke artifacts in an isolated copied layout. Exercise existing transfer preparation and source resolution, asserting preserved case, generation, commitment, previous model total and restore input; label authored bindings and distinguish them from unchanged retained bytes.
- A brief implementation duration and resource estimate, as required by the Heilmeier standard.

The existing transfer path authenticates the predecessor release and exact manifest bytes, pins the snapshot, preserves the case/template/commitment, and carries previous model totals and omitted liabilities. No additional transfer framework is needed. The design correctly preserves founder-decision attribution, requires separate live worker authority, retains the original caps, and claims no Murphy closure.

No edits, tests, network, provider or worker actions were performed.

---

Parent disposition: accepted and fixed the readiness blocker before implementation. The design now enumerates all files, retained inputs, positive transfer.prepare/source assertions, explicit authored layout adaptations and a 45–75 minute/four-slot resource estimate. EXPECTED remains an independent fixed literal. No finding rejected; no live authority inferred. The initial BLOCKED review is preserved verbatim.
