# Goldfish design review: `docs/designs/stream-b-deployment-inventory.md`

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`. Reviewed in worktree `t3-ded79ec5` at `d7c1277`. I read the design and the files it references: `bin/boat-launch-guards.sh`, `bin/boat-spend`, `factory/control_resume.py`, `tests/factory/fixtures/isolation-timeouts/`, `docs/reports/stream-b-preparation-preflight-20261031.json`, and `factory/coordinator_inventory.py` (checked for reuse). I made no writes and no paid calls.

## Verdict: BLOCK

The scope is useful and the secrecy posture is sound. The design never reads `launch.json`, `monitor.sh`, `new.N` or ledger keys. It counts unknown names instead of printing them. It never claims a snapshot is atomic, that a launch is resolved, or that activation is authorized. Four blockers stop it from being correct and ready to implement.

## Blockers

**1. Blocker: the scan skips half of the guard's own "launch finished" evidence (lines 24–31).**
The guard decides whether a launch is unfinished from four inputs (`bin/boat-launch-guards.sh:309-323`):
- `new.*.pending` files;
- the `ids` file;
- one `$state/<id>.deleted` file per worker;
- `spend-finished`.

It also writes `cleanup-status.json`, and only then `complete`. The design's allowlist covers only `launch.json`, `controller.lock`, `monitor.sh`, `ids`, `complete` and `new.N[.pending]`. The `*.deleted` markers, `spend-finished` and `cleanup-status.json` would end up as anonymous "unknown entry counts".

Those are exactly the deletion and cleanup observations that increment (2), "legacy ownership/deployment qualification using this scan", needs. Without them the report cannot separate two cases:
- a launch whose workers were deleted but whose spend never finished;
- a launch where nothing was cleaned up.

Fix:
- Add `spend-finished` and `cleanup-status.json` to the allowlist (presence/type/size/mtime only).
- Report a count of names matching `[A-Za-z0-9_-]+\.deleted`, or say why worker IDs must stay hidden. The preflight already publishes `worker_ids`.
- State that the remaining unknown entries include the launch.sh restore copies: `restore-casekey.age`, `restore-input*.age`, `founder-ruling.json`, `initial.accounts.json` and `*.admission-*`. They must stay unnamed and unread.

**2. Blocker: the creation-evidence categories are undefined and merge two different states (lines 28–31).**
The design names three categories: `pending`, `markerless-response` and `none-observed`. It does not define:
- what `new.N` *and* `new.N.pending` together means. That is a response captured but never resolved, which the guard can leave behind after a failed `guard_ids resolve`;
- what `new.N.pending` alone means. That is intent recorded, with submission unknown;
- whether a category is assigned per serial or per launch, and how serials roll up into it.

Worse, `markerless-response` (`new.N` with no `.pending`) is also the *normal* result of a successful post-guard creation, because `guard_ids resolve` deletes the marker after it records the ID (`boat-launch-guards.sh:90-96`). The scan never reads `new.N`, so it cannot tell a legacy pre-guard markerless file from a cleanly resolved one. Yet the problem statement says the whole point is to surface legacy markerless files.

Fix:
- Define a fixed table: (response present, marker present) → label, reported per serial, with per-launch counts.
- Either rename `markerless-response` to something like `response-without-marker` and document that it includes resolved post-guard creations, or drop the claim that the scan identifies legacy files.

**3. Blocker: "the existing safe launch-ID grammar" is ambiguous (line 23).**
`factory/control_resume.py` has two grammars:
- `[A-Za-z0-9_-]+` at line 42, for resume argv;
- `[0-9a-f]{32}` at line 48, for reserved IDs.

The looser one would print any directory name an operator created by hand, which matters for secrecy. Fix: name `[0-9a-f]{32}`. Also say whether a symlinked or non-directory entry under `launches/` counts as invalid.

**4. Blocker: no output contract (lines 15–60).**
The design leaves several things undefined:
- JSON key names and nesting;
- the representation of missing, empty and invalid ledgers;
- the shape of an "unsupported" or "changed" observation;
- the error message text;
- which nonzero exit code means what;
- whether the expired-hold count uses `expires_at < observation time`.

The tests assert against this output and increment (2) consumes it, so leaving it open breaks the zero-decision rule. Fix: add a literal example output plus an exit-code table. Also state that the "reserved USD sum" covers only `status == "reserved"` records.

## Major

**5. Major: the objective is written in jargon (lines 5–11, Heilmeier "Objectives" and "Impact").**
Phrases like "exceptional provider billing lifetime and create multiplicity contracts" and "next adjacent implementable prerequisite" do not tell a fresh reader three things:
- what question the report answers;
- who runs it, and when;
- what decision it feeds.

Add three plain sentences. For example: "On the control VM, list every past launch directory and every money hold, without reading secrets or changing anything, so the next step can decide which old launches still need cleanup."

**6. Major: the symlink-free root rule clashes with macOS temp dirs (lines 48–50, tests).**
`tempfile` paths on macOS live under `/var`, which is a symlink to `/private/var`. A strict "no symlink components" check fails on test roots unless the tests resolve them first, and the full suite runs on the Mac. State that tests pass `Path(tempfile.mkdtemp()).resolve()`. Alternatively, define the check as applying to components after `realpath` of a trusted prefix. Either way this must be a decision in the design, not something the implementer guesses.

**7. Major: the test fixtures do not cover the real layout (lines 64–66).**
`tests/factory/fixtures/isolation-timeouts/` contains only allowlisted copies and has no `ids`, `*.deleted`, `spend-finished` or `new.N.pending`. The preflight shows the real unresolved launch `b275ff…` held only `controller.lock` and `launch.json`. Add that second real layout as a test case. Also name the test file, presumably `tests/factory/test_deployment_inventory.py`.

## Nits

8. **Nit:** the source-hash allowlist (lines 44–48) is `sha256sum` over four files. It can stay because it is cheap, but it is optional scope that has nothing to do with inventory.
9. **Nit:** lines 84–93 (the remaining increments, OpenRouter, the USD 20 envelope) do not belong to this change. Move them to the stream B tracker.
10. **Nit:** reuse check: `factory/coordinator_inventory.py` queries the live fleet through `boat-call`, so it does not cover this offline need. A new module is justified.
11. **Nit:** the Murphy section says "No Murphy row closes" and gives a reason, which is acceptable. It would be stronger to name the open rows this scan feeds, so the diff goldfish can check that none was closed by mistake.

## What passes

- **Scope usefulness:** the preflight is a one-off summary, so a repeatable read-only scan is a legitimate prerequisite.
- **Secrecy:** the design never reads launch contents or ledger keys, never prints exception text or paths, and tests with poison strings.
- **Ledger handling:** it matches `bin/boat-spend`: version 1, `usd` stored as a decimal string, and status `reserved` or `finished`. `reconciled_expired` is a genuine historical status that commit `6154653` removed.
- **Cost:** no spend, and none is claimed.

## Author disposition

All four blockers accepted. Design revised with cleanup observations, per-serial truth table, strict launch-ID grammar and an explicit output/exit contract. Majors 5–7 addressed; source hashes retained, tracker moved to a separate report, and open rows named. No blocker rejected. Fresh review requested; author does not certify these fixes.

