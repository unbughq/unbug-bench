**Goldfish design review: stream-d.md, "Item 6 implementation: isolated extension comparison" (lines 2356–2449)**

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md. I read the design against `factory/extensions.py`, `factory/gate_state.py`, `factory/run.py` (`GATES`, `g2`, the extension admission path at about lines 351–405), `bin/run_validity.py`, `tests/factory/test_stream_d_extensions.py` and Murphy row 9. I wrote no files.

**Verdict: FAIL.** There are 5 blocking findings.

### Overall view

The scope is right. Item 6 is a comparison service that is given an evaluator from outside. It has no default `run.gN` adapter, grants no money and does no dispatch. It never touches the live candidate, and it reuses `retain_comparison` and `progress()`. This is the correct size of API to hand to lane 7, and it does not take over item 7. The failures are gaps in the contracts and one integration hole. An implementer would have to make design decisions the standard says the plan must make.

### Blocking findings

**1. A pair built from a comparison cannot be used to admit the next extension (integration hole).**
Severity: Blocker. Scope: "Problem, scope and deletion"; `extensions.py:262-264`, `:284-294`, `:212-218`, `:53-55`.
- `propose()` only accepts a new entry snapshot whose `case_sha256`, `stages`, `frontier` and `evidence` equal the chosen pair's `outcome` exactly.
- `verify_proposal()` then reads every evidence name from the live `c.work / name`. So does `admit()`, through `_save_case` → `_save_evidence`.
- The design deliberately keeps comparison evidence out of live `c.work`. That evidence ends up only under `extension-snapshots/N/comparison-<digest>/{entry,outcome}/`, and `validate_snapshot` forbids evidence names under `extension-snapshots/`.
- Result: the first time progress is decided by a comparison rather than the original pair, the next extension fails with `extension_snapshot_changed`. The comparison either does nothing or forces a write into the live work directory, which breaks isolation.
- The design must say how the next entry relates to the retained comparison outcome. For example: `verify_proposal` and `_save_case` verify and copy evidence from the retained comparison root when the entry equals a retained pair outcome. The design must also add a test: compare → retain → propose → verify_proposal → admit, on the replayed case.

**2. The workspace and stage-receipt data contracts are not defined (zero-decision rule).**
Severity: Blocker. Scope: "Isolated execution and receipts".
- The evaluator signature `(workspace, stage)` names no type and no fields.
- Gate binding is said to be `gate_state.fingerprint`, and versions come from `scientific_version`. Both need an object shaped like `c`: `c.case`, `c.args`, `c.seed`, `c.factory_slot`, `c.card['roles']`, `c.models`, plus a `bench` path (`gate_state.py:145-180`, `:192-212`).
- The design must state:
  - whether the workspace is that object;
  - which `bench` path the version and binding are computed against (the read-only source, or lane 7's isolated results bench);
  - whether the copied configuration comes from the live card at compare time or from the time of entry.
- The receipt itself also needs to be specified:
  - its file name and location;
  - its exact JSON fields;
  - how the evaluator's `evidence_paths` map to snapshot evidence names that pass `validate_snapshot` (relative, no `..`, no `case/` or `extension-snapshots/` prefix).
- This receipt writer/reader is also what lane 7 will need for the original entry/outcome snapshots. No producer of those exists today; only tests call `extensions.complete`. The design must say it is the shared API.

**3. The pending-versus-fail classifier is unspecified and contradicts item 5.**
Severity: Blocker. Scope: "Pass/fail requires … no operational/inconclusive detail"; item 5's "G10 evidence semantics".
- Item 5 defines an ineligible capped or unknown attempt at G16/G17 as a scientific gate **fail** (`verdict_valid:false, review_inconclusive:true`), routed to ordinary writer repair.
- Item 6 turns any "inconclusive" detail into **pending**, and pending work is re-executed on retry with no limit.
- So a case whose calibrator keeps hitting its cap never resolves. `propose` raises `extension_comparison_pending` every time, which is a hold on the case rather than a retirement. That runs against the "no human pit stop" target.
- The design must list exactly which detail keys or exception types mean pending. That covers `InvalidInfra` and `InfrastructureExhausted`, `review_inconclusive`, malformed evidence and anything else. It must reconcile that list with item 5's G16/G17/G10 classification, and say which item (4 or 7) counts and bounds retries of a pending pair.

**4. The "changed case bytes means pending" rule hits a gate that legitimately writes to the case.**
Severity: Blocker. Scope: "A gate that changes case bytes is rejected as pending".
- The G2 path rewrites `case/freshness.jsonl` (`run.py:551-553`). Freshness top-ups write the same file.
- The codebase already treats this file as mutable:
  - `gate_state.inputs` excludes it from every gate except G8/G9 (`gate_state.py:150`);
  - `run.py:809-811` hashes the case without it.
- `extensions.tree` and `case_sha256` include it.
- G2 is listed as a mandatory fresh execution, so it runs in every comparison. If that run touches freshness, the comparison is pending forever.
- The design must decide what happens. Options: G2 runs without top-up or repair in the comparison; freshness is carried as evidence; or the digest rule is changed. Then it must test that decision on the replayed case.

**5. Which receipts may be reused is not pinned down.**
Severity: Blocker. Scope: "Only current, fully bound receipts can be reused…".
Several decisions are left to the implementer:
- Whether G1 and G17 are reusable. Neither is in `gate_state.REUSABLE`, and neither is on the mandatory-fresh list.
- Whether comparison reuse keeps the G16 `calibration_binding` check and the G8/G9 `compatible_panel` fallback from `gate_state.load` (`:267-279`). Skipping the calibration check would let a G16 pass be reused after the calibration attempts changed.
- Whether reusing **fail** receipts is new behaviour. `gate_state` never reuses a fail.
- Whether original entry/outcome rows are reuse sources, or only "the newest retained comparison".

The design should state one rule. For example: reuse only when the receipt's `scientific_version` equals the pinned version, its full fingerprint and evidence verify, and it passes the same gate-specific checks `gate_state.load` applies, with an explicit list of stages and sources.

### Nits and non-blocking points

1. **Heilmeier gaps for this increment.** The section has no cost, timeline or risk statement.
   - At minimum, say who pays for the re-evaluation forced when versions drift: the infra-waste line or the batch extension bound. Point to item 7 for enforcement.
   - Give a rough size: number of paid stages per side after reuse, and the increment's size.
2. **Redundant sentence.** "Each gate's transitive scientific inventory determines dependency invalidation" duplicates what per-gate `scientific_version` already does. Say "reuse iff the version is equal" so nobody builds a second dependency analysis.
3. **Where scratch workspaces live.** Place them outside `c.work`, or under a dot-prefixed name. Otherwise `gate_state.inventory`'s `c.work/review-*` glob could pick them up as live evidence after a crash.
4. **Single writer.** `read()` → `_write()` on `extension-history.json` has no lock. State that `compare` and `retain_comparison` run in the case's single owning worker, never alongside `admit` or `complete`.
5. **Unbounded growth.** Retained pending pairs make the `comparisons` list and the evidence directories grow without limit. Note the bound, or which item sets it.
6. **"Deletion" is really an addition.** The new `retain_comparison` roots parameter adds a path. Also say that `_save_evidence`'s symlink check becomes relative to the given root, not to `c.work`.
7. **Missing tests.** Add: G2/freshness case mutation, a G16 inconclusive classification, G16 calibration-binding reuse refusal, and the next admission from a comparison outcome (finding 1).
8. **Lane boundary is fine.** No production caller until item 7 is acceptable. Keep the public surface to `compare`, the receipt writer/reader, and the extended `retain_comparison`. Add nothing more for lane 7's benefit.

Murphy rows: the claim "supports row 9, closes none" is consistent with the register and the ordered plan.

## Elephant response

All five blocking findings accepted. The revised item-6 design defines retained-outcome evidence resolution for admission, exact workspace/receipt APIs, pending classification and retry ownership, G2 evidence overlay semantics, and a conservative explicit reuse policy. All requested tests are included. Nits 1–8 are accepted through cost/risk and single-writer notes, external scratch directories, explicit bounds ownership, and root-relative symlink verification. No finding is rejected.

