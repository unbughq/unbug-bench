**Verdict: PASS.** I found no blocking or Major issues, only three optional nits.

**Scope:** I reviewed only commit `23e29b1` ("Show held factory bugs as unscored status attention") in `t3-ded79ec5`. I checked it against `docs/designs/status.md` §"Factory bug held" (lines 192–230), line 75 and line 186, and against the resolutions in `batch-status-held-design-1.md` and `-2.md`. I used the `zoom_out` and `implementation_readiness` personas, in Mode REVIEW. I left the uncommitted accounting changes (`batch-service.md`, `murphy-register.md`, `batch-service-design-14.md`) out of scope. I made no edits, paid calls or VM actions, and saved nothing. The focused file passes all 14 tests when run with `python3 -m unittest discover -s tests/factory -p test_batch_status.py`. A direct file-path run fails at import because the `fixtures` module path isn't set up that way, so that error is not a test failure. The full suite's result is the parent's to record; this review does not replace it.

### Design conformance
- **Known stop and label:** `factory_bug_held: 'factory bug held'` is added to `STOPS`. That keeps the known-stops list at line 186 true, and `unknown stop` / `check case` are never shown for it. The test asserts this.
- **Stopped beats stale `failed_gate` / G12:** the held check is the first branch inside `phase == 'stopped'` (`batch_status.py:139`). It comes before `if failed:` and before the sealed check. The bucket stays `stopped`, never `rejected` or `sealed`. The test applies the held stop to the real SEALED card (G12 pass), the real REJECTED card (stale `failed_gate`) and the OLD card. It asserts `Sealed 0 / 3`, `0 rejected, 1 stopped`, and that each card is left unchanged.
- **Safe token and fallback:**
  - The check reads `isinstance(finding, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', finding)`, and it short-circuits, so the regex never sees a non-string.
  - In Python's conditional expression, `+` binds tighter than the conditional, so the precedence is correct.
  - `[A-Za-z]` matches only ASCII here because no flags are set.
  - `_block` already handles a `factory_bug` value that isn't a dict.
  - The tests cover `None`, `''`, `123`, `True`, `'bad\n'` (the fullmatch case), a value with a space, a 129-character value, `'é'`, `{}`, and `factory_bug` set to `None`, `[]` or `{}`. All of them show `factory bug: finding unreadable` and print no card text.
  - Status never reads `gate_or_stage` or `summary_class`, and the test asserts the `summary_class` text is absent.
- **Lifecycle precedence:** rows that are `running`, `pending` or `failed` never reach the stopped branch. The test checks all three, as round-2 N2 asked, and asserts no `factory bug:` action appears.
- **Near-limit coexistence:** the `near limit` rule skips only `rejected`, `not collected` and `unreadable`, so a held case gets both flags without any new code. The test sets 8/10 spend and asserts both actions are shown.
- **`read_rows` snapshot with the saved 5813be ledger:**
  - `snapshot()` gains a `source_card` parameter that defaults to SEALED, so existing callers don't change.
  - The new test builds on saved card `…5813be`, whose real values are `terminal_stop: paused`, a `continuation_budget` dict and no `case_budget`. It authors only `terminal_stop` and `factory_bug`, and `snapshot()` adds its usual operational bindings (`case`, `sha256`, `batch_release_sha256`).
  - It asserts that `continuation_budget` survives `read_rows` unchanged, that the `case-practice-k: factory bug: see finding finding-infra-1` flag and the label appear, and that no file under the test root changes.
  - This resolves round-2 N1.
- **Scope:** the commit adds no new module, command, data source, dependency, mutation or maintainer queue, and closes no Murphy row. The new card fields are labelled as authored, not as D output. That matches the parent ruling and design option (b).
- **Zoom-out:** the change is the smallest that works: one branch of about 6 lines, plus a dict entry. Nothing is reinvented; it reuses `_block`, `STOPS` and the existing near-limit rule.

### Nits (optional, non-blocking)
- **N1.** No test covers the valid upper bound: a 128-character ID should still show `see finding`. Only the 129-character rejection is tested.
- **N2.** In `test_authored_factory_bug_held_is_unscored_and_actionable`, the near-limit, lifecycle and malformed-ID checks reuse the loop variable `card` left over from the last loop pass (the OLD-derived card). That works, but naming the base card explicitly would read more clearly.
- **N3.** The snapshot test's `assertIn('factory bug held', text)` would be stricter as `'| factory bug held'`, which pins it to the per-case reason column, matching the render test.

### Still open (from the design, not new findings)
- Before activation, D still has to build the producer for `terminal_stop: factory_bug_held` and the `factory_bug` field.
- `interfaces.md` and `stream-d.md` still need updating, since they currently say "maintainer queue" and describe a different `factory_bug` shape.
- Where to look up a finding still has to be named.

This commit correctly claims none of these.
