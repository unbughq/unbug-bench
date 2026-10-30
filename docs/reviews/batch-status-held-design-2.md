**Verdict: PASS.** No blockers or Major findings are open. There are four optional Nits.

I reviewed `docs/designs/status.md` lines 75, 186 and 192–228 in worktree `t3-ded79ec5` against `factory/batch_status.py` and `tests/factory/test_batch_status.py`. I also read `docs/reviews/batch-status-held-design-1.md` and its resolution, `docs/designs/interfaces.md` §8, `docs/designs/stream-d.md` §"Diagnosis and factory-bug routing", the concurrent `batch-service.md` diff, and the saved fixture cards. I used the personas `zoom_out`, `design_critic` and `implementation_readiness`, all in Mode REVIEW, with the standards `heilmeier-standard.md` and `implementation-readiness-standard.md`. I made no edits, ran no tests, made no paid calls and saved nothing.

### Round-1 findings: are they resolved?

- **B1: resolved.** The design now names its files: `factory/batch_status.py`, `tests/factory/test_batch_status.py` and this design. Option (b) is stated plainly: this increment covers rendering plus one `read_rows`→`render` snapshot read, and the D-to-B queue assertions belong to `test_batch_service_d.py`. The concurrent `batch-service.md` text agrees. It lists `test_batch_service_d.py` as its own file and puts the "see finding" assertion in the status regression. The two increments can merge independently.
- **M1: resolved.** "Exact" now means exact wording, not the only action. The `near limit` rule still fires on top of it, and a test covers that. In the code, `near limit` is skipped only for `rejected`, `not collected` and `unreadable`, so a held case filed under `stopped` gets both flags without any new code.
- **M2: resolved.** The section now says:
  - the ruling replaces the maintainer queue;
  - the D producer is not implemented at `cfe616f`;
  - all three fields are strings;
  - `interfaces.md` and `stream-d.md` must be updated before activation;
  - tests author the fields.

  The shapes really do differ today: `stream-d.md:339` has `{component, reproducer, affected_operations, fix_required}`, and `interfaces.md:681-682` still says "maintainer queue". The design names this mismatch as a prerequisite. It is also fail-safe: if the field is missing or the wrong shape, status shows `factory bug: finding unreadable` and never shows card text.
- **M3: resolved.** The queue test is out of scope here, so the problem of "no child" checks passing trivially no longer applies to this increment.
- **Nits: resolved.**
  - The label is set to `factory bug held`.
  - The ID check uses `re.fullmatch`, and a trailing newline is tested.
  - The "at most 128" typo is fixed.
  - The ledger wording now says `continuation_budget` is left unchanged.

### Implementation readiness (checked against the code)

- **Branch order:** The design says the held check goes inside `phase == 'stopped'`, before the `if failed:` branch at `batch_status.py:138`. That makes held win over a stale `failed_gate`. Held also cannot be counted as sealed, and it lands in the `stopped` bucket, so near-limit applies. An implementer can code this directly.
- **Running, pending and failed rows:** these never reach the stopped branch (`batch_status.py:110-136`). That precedence needs a test, not new code.
- **ID and label:** The token rule is exact: a nonempty string of at most 128 characters, ASCII letters, digits, underscores, dots or hyphens, checked with `fullmatch`. The fallback wording is exact too. `_block(card, 'factory_bug')` already handles a value that isn't a dict. Adding `factory_bug_held: 'factory bug held'` to `STOPS` keeps line 186's known-stops list true.
- **Scope:** No new module, command, source, dependency or mutation is added. That is the smallest design that works, and nothing reuses or reinvents existing code.
- **Murphy rows:** The design claims no Murphy closure. That is correct, because no real lifecycle artifact exists yet.

### Nits (optional)

- **N1.** The snapshot test says it "retains the saved continuation_budget unchanged". But `ReadTests.snapshot` builds its card from `SEALED`, which is case `…a869de`, and that card has no `continuation_budget`. So the clause proves nothing as written. Either name a saved card that has `continuation_budget` and let `snapshot()` take it, or drop the clause. Adding the held stop to the `SEALED` card is still worth doing, because it proves held beats sealed through `read_rows`.
- **N2.** The precedence line says "Running and pending" only. The code sends journal `failed` down the same branch (`batch_status.py:132`). Say "running, pending and failed", or test all three, as the existing lifecycle test already does.
- **N3.** `factory bug: see finding <id>` doesn't say where a reader looks up that finding. The parent ruling takes away the maintainer queue, and nothing in status, `interfaces.md` or `stream-d.md` names a store for findings yet. Add that to the D follow-up list, so the action points somewhere before activation.
- **N4.** For Heilmeier completeness, add one sentence on risk: a held case shows as `stopped`, not as needing a ruling, so the attention flag is the only place it surfaces. This is already true in the design; it just isn't stated.

**To proceed:** go ahead with implementation, then run the full suite and a fresh diff-review goldfish. The D producer and the `interfaces.md`/`stream-d.md` updates stay required before activation. Production enablement was not reviewed.


## Elephant resolution

PASS accepted; no blockers rejected. Optional nits addressed: snapshot uses saved
5813be with its ledger; tests cover failed lifecycle; D lookup location is an
activation prerequisite; risk stated. Implementation remains read-only.
