**Verdict: PASS.** No blockers are left open. B1, M1, N1 and N2 are each resolved in the text.

# Goldfish design review 2: stream D, "Remaining increments after 4f291fb", completed writer validation parity

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: zoom-out, Heilmeier, implementation-readiness.
Scope: `docs/designs/stream-d.md:1568–1663`, uncommitted in worktree `t3-21bef30c`. Checked against:
- `factory/run.py:1015–1360`;
- `tests/factory/test_stream_d_runtime.py:40–95` and `:466–590`;
- `docs/reviews/stream-d-completion-design-1.md`.

## Resolution of the prior findings

**B1 (placement): resolved.**
- The design now puts both new checks inside `if modern_writer_unit and not awaiting_stress`, guarded by `resume_writer_validation`, right after the completed output-hash check. In code, that is after `factory/run.py:1175–1176` and before `problems`/`source`/`report` load at 1177–1182.
- That anchor runs before:
  - the shared `if report and problems:` block at 1256, where `loop_freshness` runs at 1262 and `early_review` at 1277;
  - the resumed-G1 branch at 1344.
- The design also says outright "Do not put the check in the later resumed-G1 branch".
- Output hash still goes first. Once that check passes, `case_hash(c) == receipt['output_sha256']`. So comparing the before hash to either `case_hash(c)` or `output_sha256` gives the same result, and the implementer has no choice to make.
- The test that catches wrong placement is specified:
  - It builds a completed round-two repair from a saved stress report that has blocking findings, so `findings_report` is non-null and `report and problems` would be true.
  - After the completion kill, it patches `loop_freshness`, `confirm_hits` and `early_review` to fail if called.
  - It runs both the unchanged-repair refusal and the malformed-intent refusal under that setup.
- With the check placed wrongly at 1344, that test would hit `loop_freshness` at 1262 and fail. The test discriminates.

**M1 (round-one setup): resolved.**
- The design names `prev = {'failed_gate': 'G1', 'failed_detail': ...}`, shared by the uninterrupted and the killed run.
- At line 1076 this makes `problems` non-empty, so `repair_requested` is true at 1297.
- On resume, `skip_writer` stays false at line 1081 because `failed_gate` is set. The receipt branch then sets `start_round = n` and `skip_writer = True` (1173–1174), so round 1 is kept and no second writer runs.

**N1: resolved.** `diagnosis_pending` is named as a case-level hold, and the text says it is not a batch-wide halt.

**N2: resolved.** Strict intent validation is limited to completed writer receipts. Pending receipts keep the `.get` defaults at 1304–1305.

## What passes

- **Zoom-out.** The fix closes a real semantic gap: the uninterrupted path checks for an unchanged repair at line 1323, and the restored path does not. The fix adds one guard at the existing receipt-load point. It adds no schema, toggle or subsystem. Legacy V1 is untouched, because `modern_writer_unit` needs `schema_version == 2`.
- **Heilmeier.**
  - The objective, current gap, cost (none, and a stress call is saved) and risk (malformed V2 receipts fail closed) are all stated.
  - Row 10 is correctly left open.
  - Increments 2–7 each name target rows and close nothing before the qualification increment 7, which matches the Murphy closure rule.
- **Implementation readiness.**
  - The file, anchor, refusal reason (`invalid_recovery_receipt`), field types (boolean intent, SHA-256 before hash) and the not-to-do list (no writer call, no renumbering, no reservation, no provider-wait reinterpretation) are all specified.
  - The test harness already supports every specified control: kill at checkpoint as in `test_writer_completion_checkpoints_…` at 468, and a blocking-findings stress report as in `stress_rebind('finished')` at 539.
  - Each test case is named: unchanged requested repair (uninterrupted and killed), changed repair, unchanged no-repair first writer, malformed or missing intent, and output-hash precedence.

## Nits (optional)

1. **Fold the corrections in.** The "First-increment design review corrections" paragraph sits after Change and Tests, separated by a double blank line. A reader of Change alone still sees only "before resumed G1/early validation". Merging the anchor sentence into Change and the round-one and round-two controls into Tests would leave one authoritative reading.
2. **Round-two prerequisites.** Two details are implied but not stated:
   - the round-two control needs `args.rounds >= 2` (as `stress_rebind` sets at test line 540);
   - in-loop `loop_freshness` must stay permitted before the kill, because it is legitimately called after the round-1 stress.

   "After the completion kill, patch …" covers the second detail. One sentence could make both explicit.

## Elephant response

PASS accepted. No blockers or rejections. Optional editorial consolidation deferred; the corrections explicitly govern placement. Tests set rounds to 2 and permit freshness before the kill.
