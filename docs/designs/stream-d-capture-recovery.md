# Fresh-case observation publication recovery

A fresh case must not lose a completed check merely because saving its proof had
a transient filesystem failure. Recover the saved proof or retry copying that
same result; never run the check again to recover it.

## Boundary and scope

Parent scope decision 72ca08f excludes retired/pre-schema cases. This increment
repairs current-schema ordinary observation publication in extension_package.py.
It does not reconstruct scores from card fields, add migration, change snapshot
schema or scientific versions, enable diagnosis, or change money/retry limits.
Permanent loss of proof still holds; no adapter can authenticate bytes that were
never retained. The all-outcomes integration remains a separate increment.

Today Records.save writes and syncs a complete staging tree, renames it to the
stage directory, then syncs its parent. observe_gate and observe_stress remove
the published directory on any capture exception. That destroys usable proof
when only the acknowledgement failed. Before-rename copy errors also discard
only staged files although the gate result remains available in memory.

## Change

Add Records.save_observation(stage, ok, info, before, old_card), used only by
observe_gate and observe_stress. Ordinary execution invoke stays outside capture
error handling. A capture failure after invoke returns cannot cause another invocation. Package/admitted-row save/capture is
unchanged. This helper owns at most two evidence-publication attempts, never a
gate_attempt, provider call or scientific retry.

Before the first attempt require the target stage directory to be absent (also
reject a symlink, including dangling links). An unexpected existing target is
not overwritten or removed: return False without calling save and leave observed[stage]
False. Freeze deep copies of info and old_card and pin
case_hash and scientific_version after the gate returns. Before each attempt,
require the live hash/version still equal these pins. Full case bytes are read
only by save; later entry_prefix retains its exact case/freshness checks.

Each attempt:
1. If no target exists, call ordinary save with the same captured result,
   pre-invoke inventory and old_card. Its staging cleanup remains unchanged.
2. If save raises an Exception, do not remove the stage directory.
   If a target now exists, load it with the existing digest, support, identity,
   result-shape and version checks. Construct probe = copy.copy(c), deep-copy its
   args and card, then Records(probe, r, observation_id=self.root.name,
   round_number=self.round_number). This is ordinary-observation-only recovery.
   Require extensions.digest({'ok': ok, 'info': info}) to equal
   extensions.digest({'ok': data['ok'], 'info': data['info']}); this compares the
   JSON representation, so tuple/list and JSON key conversions do not cause
   false inequality. If a result cannot be digested (including NaN), return False.
   Sync with extensions._sync_tree(target), which already syncs target.parent.
   Mark success only after that sync returns. A corrupt or
   mismatching published record is never deleted, replaced or rescored.
3. If the first attempt did not succeed and no target exists, retry save once.
   If a valid target exists but sync failed, the second attempt verifies and
   syncs it again instead of calling save. Both attempts catch Exception (never BaseException).
   Return False after two failed attempts, True after successful publication.

Everything the helper does, including freezing, pinning, target checks and
verification, is inside except Exception, returning False on failure. observe_gate
also catches Exception around all its post-invoke capture work (tuple unpacking,
pending and case checks included). invoke itself stays outside that try. Thus
post-invoke capture errors cannot escape into ordinary retry or change the tuple.
The pre-invoke inventory/projection catch remains CAPTURE_ERRORS as today. Set observed[stage] from that boolean. Keep the
existing close-marker guards. An intact record remains available to entry even
if both sync acknowledgements failed: entry validates its bytes, and partial
entry does not require closed.json. Corrupt published proof remains a refusal.
No new data is written by entry, and no live args are restored by validation.
Remove both destructive rmtree-on-capture-error paths. Capture errors before
invoke (inventory/projection), pending-shaped results, changed cases and result
exceptions retain their existing behavior; they have no recoverable bound result
in this increment. Missing known proof after two failed copies stays pending.

## Exams and test disposition

Use tests/factory/test_stream_d_entry.py and its saved practice/checkpoint/HTTP
fixtures; external controls remain labelled. Add no worker/model/network calls.
- Replace test_capture_failure_after_rename_does_not_retry with a one-shot
  post-rename G1 parent-sync failure: fire only when G1/record.json exists and
  the patch has not fired. Verification sync succeeds. Assert the unchanged
  snapshot, one save per stage, one invocation per gate and closed.json present.
- Keep the persistent patch separately: G1 bytes retained, two save attempts
  per G2+ stage, one gate invocation each, closed.json absent and entry pending.
- Real G4/G5 over invalid-runs-real.json.gz: fail one evidence-copy publication
  before rename, then succeed. Same result, entry frontier and support bytes as
  baseline; each real gate runs once, save called twice only for affected stage.
- Stress post-rename sync failure retains its authenticated proof and admits the
  normal snapshot. Stress validation/evaluation is not repeated for publication.
- Persistent copy failure preserves the original gate tuple and leaves entry
  pending; exactly two save attempts, no gate retry. Existing capture-error and
  pending-shape exams keep their refusal assertions.
- RuntimeError from save and from verification: one gate invocation, the original
  tuple and pending entry when proof is absent or invalid. No ordinary retry.
- Corrupt or symlinked target after publication, mismatched result, changed case
  or version between publication attempts: no replacement and pending entry.
- A pre-existing stage target refuses recovery without overwriting bytes.
- G3 validation uses copied args/card: live workers and card remain unchanged.
- Simulate one kill (BaseException bypassing capture handling) at _sync_directory(self.root) inside save only when G4/record.json exists after rename. Entry from
  retained checkpoint artifacts uses no evaluator or save: stress through G4 pass,
  frontier = extensions.stages().index('G5'), G5 onward unreached. It is a prefix,
  not equal to the uninterrupted full traversal. A partial staging directory
  alone never becomes scored evidence.

Midterm: focused entry tests. Final: full suite under detached plain lockf,
7200 seconds after lock acquisition (queue excluded), unique log/record committed,
then a fresh diff review. Max two design and two diff review rounds; a round-two
blocker goes to parent. One implementation commit, then evidence/approval commits.

## Cost, risks, and remaining work

No new model spend; one extra filesystem copy/sync attempt only on capture failure.
Risks are accepting stale proof or altering execution retries; frozen result,
identity/version checks and single-invoke tests address those. Do not accept a
card as evidence or erase corrupt proof. Estimate 2–4 engineering hours plus suite
queue and reviews. This supports Murphy 9 and 13; closes none. After this slice,
all-outcomes integration must explicitly account for genuinely absent/corrupt
proof and persistent disk failures; this design does not claim to repair them.

## Parent-approved after round 2

The parent accepts B3 option (b), with the exact one-shot G1 post-rename test
above, plus option (a) as the separate persistent-failure test. O1 is applied:
the crash is one event, guarded by the published G4 record's existence. O2:
the record card is the live post-invoke card; a retried save reads it again,
while old_card and the result are frozen. O3 (pre-invoke RuntimeError remains
under ordinary retry before any invocation) is accepted as scoped. No round 3.
