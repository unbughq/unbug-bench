# Review: stream-d diagnosis-input design 2: FAIL

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`, using zoom_out, design_critic and implementation_readiness.

**Scope:** `docs/designs/stream-d.md:1213–1349` at `872151cd09e43e4b49bbe631b28dea6ad727ecce`, cumulative `fab9014..872151c`, in `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`. Checked against the surrounding diagnosis/held design, interfaces §8, ENGINEERING and the named standards. Read both prior review records and elephant responses verbatim.

Uncommitted implementation drafts, `.stream-d-next/` and unrelated edits appearing during review are excluded. Line references below refer to the pinned commit.

## What holds

- The named `diagnosis_input_invalid` lifecycle addresses prior B1: stopped card, preserved diagnosis state, false exhaustion, no pending projection, no fresh ID and no automatic reset.
- History-invalid handling explicitly covers pending infrastructure and completed holds while retaining the finding and held-dispatch protection.
- An intact frozen snapshot fixes review-17’s live-ledger replay problem. Its generation identifies the restored ancestor; later checkpoints do not rebind it.
- The gate inventory mapping is feasible. `gate_state.inventory` supplies work and bench evidence, and `gate_state.load` already supports restored bench evidence under `work/bench-results`.
- The source mapping matches existing code: `job_config.read_file` verifies the batch-release → worker-release chain; `worker_release.source_files` supplies file digests; worker verification maps factory paths to the installed factory root and bin paths under BENCH.
- Same-filesystem staging, durable publication, quiescence, isolation requirements and measured storage subtotal are explicit. No dispatcher, money authority or public configuration change is introduced.

## Blockers

**B1. Missing manifest is treated as an orphan even when a retained finding proves the inputs were already used.**

**Scope:** `stream-d.md:1284–1301`, refusal lifecycle at `1306–1317`.

The unconditional rule says that absent `input.json` means delete inputs and re-stage current bytes. Absence alone does not prove that no invocation was bound.

Consider a retained `finding.json` after interrupted public completion, followed by loss of `input.json`. The rule permits deleting the original input tree and rebuilding it from a growing live ledger or later source generation. The retained finding then fails validation against the replacement inputs. The existing replay path calls `validate_result` again (`factory/diagnosis.py:304–324`); the design does not explicitly route this missing-manifest-with-finding case through `diagnosis_input_invalid`.

This contradicts immutable replay and leaves the implementer to decide whether to rebuild, refuse or retry.

**Required change:** restrict orphan re-staging to an unbound initial attempt. Before cleanup, inspect retained evidence for that exhaustion. A finding, raw judgment or completed diagnosis state with no manifest must cause `diagnosis_input_invalid`, preserving remaining inputs and findings. Specify that this refusal precedes both re-staging and finding validation. Keep re-staging for the genuine pre-manifest crash window.

**Required tests:**

- Freeze inputs, persist a finding, interrupt public completion, remove `input.json`, append to the live ledger, then attempt replay.
- Assert no input replacement, finding mutation or model call; preserve the exhaustion ID; require stopped/input-invalid, false exhaustion and a None projection.
- Repeat after a completed hold.
- Retain the separate pre-manifest orphan test proving re-staging still succeeds.

## Majors

**Ma1. The required gate-detail filename rejects legitimate substantive gate exhaustion.**

**Scope:** `stream-d.md:1258–1267`.

The minimum requires `gate-details/<gate>.json` for every gate-mapped trigger, with an exception only for infrastructure crashes. Existing gate producers do not universally write that file.

For example:

- `run.g4` returns its result without writing `gate-details/G4.json` (`factory/run.py:2174–2180`).
- `run.g6` likewise returns substantive failure information without that file (`2224–2239`).
- At the round limit, `validate_and_repair` routes these failures through `late_recovery.stop_defect` (`2719–2721`).
- That producer writes `late-defect.json`, binds it through `card.late_defect.record_sha256`, and removes the public detailed result (`factory/late_recovery.py:99–114`).

Consequently, an ordinary valid `late_defect_needs_ruling:G4` checkpoint can contain the intended authenticated diagnosis evidence yet be stopped as `diagnosis_input_invalid`. The infrastructure exception cannot help.

**Required change:** define the minimum by trigger and its existing evidence producer. For `late_defect_needs_ruling:<gate>`, require the copied `late-defect.json`, matching gate and canonical digest from the authenticated card’s `late_defect` marker. Treat `gate-details/<gate>.json` as additional evidence unless that producer guarantees it. Explicitly identify the corresponding completed-outcome evidence for `extension_incomplete`; retain the infrastructure-marker exception. Reuse retained receipts instead of introducing a universal gate-detail producer.

**Required tests:**

- A round-exhausted G4/G6 late-defect checkpoint with valid bound `late-defect.json` and no gate-detail file must freeze successfully.
- Missing receipt, wrong gate or digest mismatch must produce the defined terminal input-invalid state.
- Preserve coverage for gate-cache reference resolution and the infrastructure crash exception.

This major blocks design readiness because following the current instructions produces incorrect behavior for an existing valid path.

## Nits

None.

## Readiness and validation

The amendment is appropriately scoped and reuses existing infrastructure. Most prior findings are resolved, but B1 leaves a lifecycle decision unspecified and Ma1 imposes a prerequisite existing producers do not satisfy. The zero-decision standard therefore does not pass.

These findings come from static design and code inspection. No tests or workloads were run, no files were written, and no full-suite result is claimed. No Murphy row closes.

## Elephant resolution

B1 and Ma1 accepted. Re-staging is limited to a genuinely unbound pending
attempt; retained findings, raw judgments, a completed state or a diagnosis
reservation require a missing manifest to fail as diagnosis_input_invalid
before any cleanup or finding validation. Required evidence now follows each
existing stop producer: late-defect receipt, completed extension outcome, or
infrastructure marker. Gate-details files are supplemental. No finding is
rejected. The initial Claude attempt for this round failed at the API rate
limit before producing findings; this fresh Codex fallback supplied the review.
