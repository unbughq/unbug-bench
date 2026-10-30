**Verdict: PASS.** The contract fix closes the deadlock, and the code PASS from review 4 still stands. It still depends on the full suite, which has not finished, so this is not a suite pass.

# Goldfish re-review: batch-service, `03b8455..HEAD` (docs only)

## Scope checked
- `git diff --name-only 03b8455..HEAD` lists only three files: `docs/designs/batch-service.md`, `docs/designs/interfaces.md` and `docs/reviews/batch-service-diff-4.md`. There are no code changes in `factory/`, `tests/` or `tools/`, so nothing changed can undo review 4's code PASS. Code PASS stands.
- **Full suite:** `/tmp/unbug-batch-increment2-final-tests.log` is still being written (last modified 02:32:51). It has 27 `==` script sections and no `FAIL` lines so far, and the `tests/run.py` process is still alive. **This is not a suite pass. Do not claim one until the run finishes green.**

## The blocker from review 4: closed
The deadlock is gone, and the exhausted owner now has a way to settle.
- **Ordering.** `batch-service.md` "Increment2b scheduling hook for D" and interfaces §8 both put a covered same-owner/same-revision settlement resume ahead of replacement, diagnosis and extension. A blocked replacement can no longer sit ahead of the resume that would unblock it.
- **Non-blocking FIFO.** Both files say a request blocked on money or an unknown total keeps its FIFO position but does not block later eligible requests. interfaces §8 adds "including the settlement that can unblock it". This removes the head-of-line hold.
- **A path for the exhausted owner.** It gets a settlement-only resume: no model invocation, then checkpoint and collect through the same `launch()`. This keeps the "one launch path" rule in ENGINEERING §4.
- **Settlement always ends in a known total.** I checked this against `docs/designs/stream-d.md:134-157`. `settle()` either books the missing events or reserves each unknown gap conservatively, as `max(0, reserved max − booked)`. It then writes `settled:true` and checkpoints. So the settlement-only resume always produces a known (possibly conservative) total, and the replacement becomes eligible. Without this, the fix could still hang on a receipt that never arrives.
- **Tests.** The added test sentence covers all three properties: the settlement-only resume runs before the blocked replacement, settlement makes the replacement eligible, and blocked FIFO entries do not stop later eligible work.

## Review 4 nit on stale A→B→A: closed
Both files now say the rebind starts from the current persisted source, advances only along acknowledged collection lineage, and refuses stale A→B→A.

## Conflict check: none found
- "Ordinary work follows these three classes" fits with settlement going first.
- "No diagnosis/extension dispatch while … usage unknown" still holds. Settlement is neither a diagnosis nor an extension.
- `batch-service.md:642-647` ("Settle runs first on the permitted resume", no increase/old+1/replacement/diagnosis/extension while unknown) matches interfaces §8.
- The parent policy still holds:
  - same owner, same or lower commitment, same revision;
  - the full old hold is retained and counted once;
  - every unknown maps to an admitted maximum;
  - nothing new happens until D settles first on resume.
- The `reconciled_decrease` and unsupported-decrease text is unchanged.
- Increment2 still runs fresh-only and fails closed. The new paragraphs approve the contract only, and remain labelled planned 2b and gated.

## Nits (not blocking)
1. **Deadline admission.** "capacity, deadline and money admission still apply" also covers the settlement-only resume. After the batch deadline, an unsettled exhausted owner keeps its full commitment held, so no replacement is lost. It would still help to say whether settlement-only is exempt from the deadline, so the final collection carries a settled total.
2. **Placement.** The "Also test …" sentence comes after "This is planned2b scope, not authority granted by increment2." Moving it before that line would keep the scope disclaimer as the closing statement.
3. **Cross-reference.** `batch-service.md` could cite stream-d §settle (conservative gap booking) for why settlement always ends in a known total. A reader of this file alone cannot see that it does.

## Summary
- **Code: PASS** carried from review 4. No code hunks changed. It still depends on the full suite finishing green, and that run has not finished.
- **New contract: PASS.** The review 4 blocker is closed with the minimal fix, there is no conflicting text, and three optional nits remain.
- No findings were rejected and no Murphy rows were closed, both as expected. Holder async/restore, Codex, store/journal and live practice were out of scope and not reviewed.

I made no edits and ran no state-changing commands, cloud calls, models or crypto.

---

Elephant response: PASS accepted; no findings rejected. Full-suite validation is still running and is not claimed here. Optional deadline clarification is deferred to2b's concrete settlement protocol: no deadline extension or release is granted by this foundation. No Murphy rows closed.

