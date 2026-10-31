# Claude profile / isolation merge resolution

Merge commit: 4df2854c33479ef83a94731c779f06073fa7e6a4.
Parents: 45ccb1f88e32551e70d79a498657971aa59e0664 and
7ab397e03a94ae8e51b1c0ce1fe2760a8b52fc0e.

Review only the conflict resolution with `git show --remerge-diff 4df2854`.
This is a small mechanical integration of previously reviewed designs, not a
new production change. A separate design was skipped under the small-fix rule;
the merge commit message and this record specify the intended integration.

The helper requires model and retains keyword-only real_cli/content_length.
The HTTP loop retains all CLAUDE_PROFILES and its three framing variants. The
real-process TLS loop now also covers every profile and all four framing
variants, including close-delimited HTTP/1.0. The helper passes model through
job authority, card roles, runtime.call, route assertions and reservation maximum.
The actual provider model remains the base Claude model, as A requires.

All existing process-death, pre-settlement ordering, immutable late usage,
unknown-hold and reconciliation checks remain. Route/account/provider-model
assertions from A execute for both modes. The real process branch does not
manually report startup: real run_budgeted invokes on_started after Popen.
The simulated branch retains its single synthetic on_started invocation.
The saved negative-control script forwards the newly required model argument.

The Murphy resolution preserves the router cancellation row with its scoped TLS
evidence and the open non-isolated escaped-descendant row. No row is closed by
this merge. Production files have no manual conflict-resolution changes.

Focused command: uv run --with numpy --with scipy python -B tests/factory/test_model_call_maxima.py
Result: 25 tests, OK, exit 0, 15.492 seconds.
Full-suite evidence is the uniquely named isolation-profile-merge-suite log and
JSON; the JSON records the pre-run commit/hash and verifies unchanged module bytes.
Fresh review of this resolution is saved as
`docs/reviews/isolation-profile-merge-diff-1.md` after completion.


Full suite completed with exit 0: 161 scripts, zero failures, 1757.787 seconds.
Record: `isolation-profile-merge-suite-20261031T153602Z-dc56c211.json`.
Full log: `isolation-profile-merge-suite-20261031T153602Z-dc56c211.log`.
Test module hash was captured before the run and verified unchanged afterward.
The combined module passed all 25 tests during the full run as well. Three
unrelated suite skips are recorded in the JSON and log; this module has none.
