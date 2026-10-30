**PASS**: 0 blockers, 0 majors, 6 nits. Both design-4 majors and all four design-4 nits are fixed, and the earlier resolutions still hold. I found no contradiction. The new text opens a few small crash and edge seams, listed below as nits. I wrote, committed and ran nothing. The review text below is ready to save verbatim as `docs/reviews/stream-d-worker-dispatch-design-5.md`.

---

# Review: stream-d worker dispatch design 5 (diagnosis-only sub-increment). PASS (0 blockers, 0 majors, 6 nits)

**Reviewer:** fresh goldfish, read-only, `Mode: REVIEW`. I read `docs/ENGINEERING.md` first. Personas: `zoom_out`, `design_critic`, `implementation_readiness`. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`, `zoom-out-standard.md`.

**Scope:**
- `docs/designs/stream-d-worker-dispatch.md` at `449005ccc0c3a04d85ccf558cd381408fb73463b` ("Pin model-free decision recovery and audit-only cleanup"), branch `t3/stream-d-implementation`, worktree `/Users/bugsincode/.t3/worktrees/unbug-bench/t3-21bef30c`.
- The queued-input addendum in `docs/designs/stream-d.md` (lines 1433–1440). The diff since `1b1bfc5` adds `audit-*.json` to the orphan binding there.
- I left out the untracked `.stream-d-next/`.
- `git diff --stat 210eb39 HEAD` touches only `docs/`. No factory source or test changed since the recorded 150-script and diff-24 inputs.

**Read verbatim, with elephant responses:** `stream-d-worker-dispatch-design-1.md` (including its round-2 revision note), `-design-2.md`, `-design-3.md` (including the stale-tree exception paragraph) and `-design-4.md` (including its resolution).

**Code checked for feasibility only:**
- `model_runtime.py:46,70`: `model_dispatch_lock` is an in-process `threading.RLock`.
- `runner_supervisor.py:30–90`: `kill_tree` on runner exit.
- The `start_new_session` usage across `factory/` and `bin/`.

**Out of scope, as briefed:** design-1 B1, B2 and the extension parts of M5/M6 stay **accepted, open and explicitly unqualified**. The design still says so (lines 22–29 and 404–491). I do not score them as resolved and raise no finding against those sketches.

## Design-4 findings: disposition

- **Major 1 (valid row → decision): resolved.**
  - The durable order is now explicit: raw bytes, then the journal row marked valid/malformed with its digest, then the decision (valid only), then the finding (factory bug only), then public state (lines 255–257).
  - A valid row whose referenced bytes are retained but which has no decision is finished model-free **before** the activation gate. It re-validates against the original frozen inputs root and makes no role, lease or reservation (lines 257–260).
  - Missing referenced bytes, or validation failure on a row marked valid, gives `diagnosis_input_invalid`, not a retry (lines 260–261).
  - A malformed row with no next repair row needs activation and normal admission (lines 261–263).
  - An unreferenced raw file or a pending row cannot produce a decision (lines 263–264).
  - Gate-false tests for both outcomes are listed (lines 581–583).
  - This fits the gate paragraph's "model-free outcome replay/application" phase (line 511) and the unknown-total pending branch. That branch still skips `queued_inputs`, so a valid row stranded there completes on the first resume after the ACK. That is consistent.
- **Major 2 (audit-only collects): resolved.**
  - Only the post-role collect, in the same process that got a successful `prepare` for that logical row, can raise `input_invalid` from the exposed copy (lines 318–320).
  - Orphan, stale-tree, interrupted-call and predecessor collects are audit-only. Their status and map digest are recorded with the audit bytes and never change `diagnosis_state` or `terminal_stop` (lines 320–325, 345–346).
  - The frozen root is still verified separately through `queued_inputs` (line 325).
  - The crash-mid-`prepare` test is listed: the ID is preserved, a false gate gives `diagnosis_pending`, and a patched-true gate re-prepares the same row (lines 583–585). A resumed row runs `prepare` again in the new process (lines 305–306), so the enforcing collect stays well-defined after a crash.
- **N1 (malformed-route re-detection before the gate): incorporated** (lines 238–239).
- **N2 (empty predecessor collect): incorporated.** A `missing` status with zero bytes writes no audit bytes and no metadata (lines 343–345).
- **N3 (stale trees outside the current ID or dispatcher path): incorporated.** Cleanup runs on every factory worker resume, including held, retired and non-dispatch paths. It covers every canonical UUID child of `<current case>/` and does not rely on VM disposal (lines 65–70, 585–586).
- **N4 (per-driver environment test): incorporated** (lines 586–588).
- **Audit metadata (the one explicitly named new mechanism): sound.**
  - The file is `audit-<canonical-record-sha256>.json`, with exactly `{schema_version:1, status, inputs_sha256, raw_sha256}`.
  - It is written after its audit bytes and is never authority.
  - It is in the missing-manifest binding (lines 162–167), and stream-d.md line 1436 matches.
  - Content addressing makes repeated writes idempotent.
  - `audit-*.json` and `audit-bytes-<sha>` do not collide, as long as `audit-bytes-*` keeps no `.json` suffix (see N5).
- **Earlier resolutions still hold:**
  - the producer-side re-mint guard (lines 72–82);
  - the completed-state settlement branch (lines 96–105);
  - `model_operation_id` scoped per row, repair-route pinning, and route exhaustion detected before the await;
  - the helper lifecycle: mode from the last row's `kind`, remove before every rebuild, one `prepare` per logical row, collect and remove before the next row;
  - gate placement and the single live module-attribute read (lines 511–534);
  - the stale-tree-only exception to the false gate;
  - the carry-forward allowlist, archival of all pilot identities, environment allowlists, the loopback permit, prompts and digests, and the 64 KiB/96 KiB bounds;
  - the relaunch-path statement and the stops table.

## Blockers

None.

## Majors

None.

## Nits

- **N1. Cleanup refuses unknown names, and nothing forbids helper temporary names (lines 70, 300–304).**
  - Cleanup now runs on *every* resume, and "unknown/noncanonical names refuse cleanup as infrastructure".
  - If an implementer builds the task tree atomically (a temporary sibling, then rename), a crash mid-`prepare` leaves a noncanonical entry. That wedges every later resume of the case, ordinary ones included, into `runner_error`.
  - Fix: pin that `prepare` builds in place under the canonical `<exhaustion_id>` name and creates no sibling. Alternatively, name the helper's own temporary pattern and have cleanup remove it. Extend the crash-mid-`prepare` test to assert that no noncanonical entry is ever created.
- **N2. Cleanup failure on a terminal path replaces the outcome stop (lines 65–66, 350–352, stops table).**
  - On a `factory_bug_held` or `retired_*` resume, a collect or remove failure stops `runner_error:DiagnosisTaskCleanupError`. That overwrites the public outcome label.
  - The card then becomes RETRY-eligible, though not money- or writer-reachable. This recovers on its own: `_trigger` rejects `runner_error`, so the ID is kept, and the next successful resume replays the completed state and re-emits its outcome stop.
  - Say so in one line (or in the stops table). Add a control: a held card hits a cleanup failure, then a successful resume brings back `factory_bug_held` with the same ID and no reservation.
- **N3. A root helper can outlive the runner.**
  - `model_dispatch_lock` is in-process (`model_runtime.py:46`).
  - `runner_supervisor` uses `kill_tree` as the runner user, which cannot SIGKILL the root `python3` child under `sudo`.
  - So a `prepare` orphaned by runner death can keep copying while a new process collects, removes or re-prepares. The result is a leftover tree, or a mixed tree that the next post-role collect would wrongly call `input_invalid`. That is the design-4 Major 2 failure class again, though the window is small.
  - Fix: have every helper operation take an exclusive `flock` on a fixed lock file under the root-owned `<case>` ancestor, so a stale helper finishes or the new one waits. Alternatively, state why the window is unreachable.
- **N4. Re-validating a valid row across a release change (lines 145–149, 257–261).**
  - A valid row with no decision is now re-validated on a later resume.
  - Same-owner resumes may install a different release. If `RESULT_SCHEMA`, a template or the validator changed, the row fails and the case becomes sticky `diagnosis_input_invalid`, when the real cause is a plumbing roll.
  - The design already freezes the templates ("selected frozen release source"). Say whether the validator and schema also come from the journal's `schema_sha256` binding, and what a mismatch between `schema_sha256` and the current release does. That mismatch is a pre-existing ambiguity which this revision makes reachable.
- **N5. Audit artifact details left implicit (lines 162–170, 572).**
  - Name the directory audit bytes go into when a stale tree belongs to a *prior* exhaustion ID. Presumably that is the prior ID's `work/diagnosis/<id>/`, bound to its own manifest.
  - Say that `audit-*.json` is checked for presence only (by the orphan binding) and never parsed on replay. Otherwise "exactly {…}" leaves it open whether a malformed audit file is `input_invalid`.
  - Give exact filename patterns (`audit-bytes-[0-9a-f]{64}` with no suffix, and `audit-[0-9a-f]{64}.json`).
  - Add `audit-*.json` to the orphan-refusal test list on line 572. It is in the binding but missing from the tests.
- **N6. Wording (lines 202–204 vs 354–356).**
  - "On a fresh dispatcher entry … remove the stale task tree … and rebuild from verified inputs" can be read as rebuilding before the gate.
  - Add "the rebuild happens only at `prepare`, after activation", to match the gate paragraph and the stale-tree exception.

## Answers to the brief's focus areas

- **Actual contradictions:** none. The scope boundary, the open extension obligations, the stops table, the gate paragraph, the cleanup and audit paragraphs, the test list and the stream-d.md addendum agree.
- **Crash gaps introduced in this round:** N1 and N3 are the only ones. Both are plumbing-crash corner cases. Neither reaches money or a writer while the gate is false, and each needs one sentence and one test. N2 and N4 are recoverable or pre-existing edges that should be stated.
- **Activation boundary:**
  - `close_to_passing` and active extensions stop `extension_comparison_pending` with no writer.
  - Valid-row completion and malformed re-detection are model-free and come before the gate.
  - With the gate false, the only privileged work is the old-pilot and stale-tree cleanup.
  - `DIAGNOSIS_ENABLED` stays false, with no second flag.
  - Fail-closed holds.
- **Constrained-slice readiness:** ready for implementation of the diagnosis-only sub-increment. The nits are optional under ENGINEERING §1, but N1 and N3 are cheap and worth folding in before the diff review. The diff goldfish should check the tests above, especially the crash-mid-`prepare`, gate-false replay, terminal-path cleanup and per-driver environment controls.

## Validation boundary

This is a design-readiness review only. No files were written, and no commits, merges, pushes, launches, cloud work, model calls, decryption, tests or suite runs were done. I make no claim about the 210eb39, 150-script or diff-24 results beyond what the review records state. I confirmed only that no factory source or test changed since `210eb39`. No Murphy row closes. `DIAGNOSIS_ENABLED` stays false, and A/B/E activation stays gated. Design-1 B1, B2 and the extension parts of M5/M6 stay accepted, open and unqualified. This PASS covers only the diagnosis-only sub-increment, not the complete dispatcher.

## Elephant response

*(to be completed by the elephant)*

## Elephant resolution

*(to be completed by the elephant)*

## Elephant response to passed design

All six optional nits accepted for implementation/diff review. Prepare builds in place at the canonical UUID with no temporary sibling. Helper operations serialize on a root-owned per-case flock (cleanup excludes that known lock file). Terminal cleanup failure is retryable infrastructure; successful replay restores the original outcome and ID without a model. Schema-v1 validation stays code-owned; frozen templates and the versioned schema bind the journal, and an unsupported intact schema contract stops diagnosis_schema_wait without new inference or resetting state rather than executing frozen Python or mislabelling it input-invalid. Audit artifacts for an old UUID stay under that UUID's private diagnosis directory; metadata is presence-only for orphan binding, not parsed as authority. Rebuild occurs only in prepare after activation. The full extension dispatcher is still incomplete; no extension blocker or Murphy row is closed here.

