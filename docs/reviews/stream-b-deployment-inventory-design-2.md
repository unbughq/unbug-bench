**Design goldfish review: `docs/designs/stream-b-deployment-inventory.md` (round 2)**

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: `heilmeier-standard.md`, `implementation-readiness-standard.md`. Worktree `t3-ded79ec5` at `d7c1277`. The design, prior review and tracker report are untracked. I read the design, `docs/reviews/stream-b-deployment-inventory-design-1.md`, `docs/reports/stream-b-remaining-20261031.md`, `bin/boat-launch-guards.sh`, `bin/boat-spend`, `bin/hcloud-park`, `factory/control_resume.py`, `tests/factory/fixtures/isolation-timeouts/`, `docs/reports/stream-b-preparation-preflight-20261031.json`, commit `6154653`, and the named rows in `docs/murphy-register.md`. I made no writes, started no workers or subagents, and made no paid calls.

## Verdict: PASS

All four earlier blockers are fixed, and I checked each fix against the code. No new blocker came up. Two Majors and some Nits remain. They are cheap to fold in before implementation, but none of them makes the design claim something false.

## Earlier blockers, checked independently

**B1 (cleanup evidence): fixed.**
- `spend-finished` and `cleanup-status.json` are now on the allowlist (lines 25–26). These match what the guard reads and writes at `boat-launch-guards.sh:317-326`.
- `[A-Za-z0-9_-]+\.deleted` is counted by type and never named (lines 29–31). This matches the guard's `touch "$state/$retire_id.deleted"` at lines 247 and 258, and its worker grammar at line 69.
- The restore copies are explicitly unknown, unnamed and unread (lines 31–33).

**B2 (creation categories): fixed.**
- There is a per-serial table with per-launch counts for all three labels (lines 35–45, 106).
- `markerless-response` was renamed `response-without-marker`. The design says this label also covers creations that were resolved normally, which matches `guard_ids resolve` unlinking the marker (lines 90–96).
- The claim that the scan identifies legacy files was dropped (lines 46–47).
- The case of both files present corresponds to the guard's failed-resolve path (lines 140, 284).

**B3 (launch-ID grammar): fixed.** It is now `[0-9a-f]{32}`, the same as `control_resume.py:48`. Symlinked and non-directory entries count as invalid, even when the name matches (lines 21–24). Invalid names are never printed.

**B4 (output contract): fixed.**
- A literal schema-1 example is given (lines 85–102).
- Item, metadata, source and ledger state vocabularies are defined (lines 104–133).
- The error enum is closed (line 135).
- Exit codes are 0, 1 and 2 (lines 140–142).
- An expired hold means `expires_at < observation time` strictly, and equality is not expired (lines 130–131).
- The USD sum covers `status == reserved` only (line 53).
- The ledger rules match `bin/boat-spend`: version 1, `usd` stored as a string, `expires_at` as a float. They also match the historical `reconciled_expired` status: commit `6154653` shows those records keep `usd` and `expires_at`, so the "all records need both fields" rule will not falsely invalidate them.

Earlier Majors 5–7 are also fixed:
- The objective is in plain words (lines 5–8).
- Tests resolve `mkdtemp()` (line 147).
- The `b275ff…` layout with only `launch.json` and `controller.lock` is reconstructed from the preflight (lines 148–150).
- The test file is named.

## Findings

**1. Severity: Major.**
*Scope:* lines 29–31 and 107 (`deleted_markers`).
*Finding:* `guard_retire` touches `<id>.deleted` **and** `<id>.parked` when `hcloud-park` succeeds (`boat-launch-guards.sh:246-247`). `bin/hcloud-park` keeps that VM running until its paid hour ends. So a `.deleted` count can include live, billing VMs. The design's stated use is deciding which launches "still need investigation or cleanup", and today a parked launch looks the same as a launch whose workers were really deleted. The `.keep` marker (VM kept because its checkpoint was not verified, line 226) is in the same position.

The design avoids a false claim: it says markers are unverified, never calls a launch resolved, and lists provider-creation-deletion as an outstanding proof. That is why this is not a blocker.

*Recommendation:* count `[A-Za-z0-9_-]+\.parked` and `[A-Za-z0-9_-]+\.keep` by type, the same way `.deleted` is counted (new `parked_markers` and `keep_markers` keys). Add both to the guard-layout test.

**2. Severity: Major (zero-decision gaps the tests will lock in).**
*Scope:* output contract, lines 104–142.

Five small decisions are still left to the implementer:
- (a) Whether a non-regular `new.N` or `new.N.pending` makes the item `state: error`. Line 37 says it "still counts as present", and line 110 only covers the seven allowlisted names. The answer changes the exit code.
- (b) Sort order for `launches.items` (by id?) and for `creations`. Serials keep leading zeros, so `new.01` and `new.1` are distinct. Say whether they sort by string, or by integer then string.
- (c) The `reserved_usd` string format. `str(Decimal)` can emit `1E+2`. Specify fixed-point output, e.g. `format(total, 'f')`, and whether trailing zeros are normalized.
- (d) What `expired_reserved` and the per-status counts hold when the ledger is invalid: computed, zero, or null. Only the total is defined as null.
- (e) Which stream `{"error":"invalid-arguments"}` goes to, stdout or stderr.

*Recommendation:* add one line for each.

**3. Severity: Nit.**
*Scope:* line 16.
*Finding:* the ledger location is implied, not stated.
*Recommendation:* say `<control-home>/boat-reservations.json`, as in `boat-spend:80-82`.

**4. Severity: Nit.**
*Scope:* lines 66–68.
*Finding:* `control_resume.py:20` calls `.resolve()` on the control home, so the live tooling tolerates a symlinked home and this tool refuses one.
*Recommendation:* that is fine for a required argument. Add one sentence telling the operator to pass a canonical path (`realpath`).

**5. Severity: Nit.**
*Scope:* lines 116–119 and 126–132.
*Finding:* stat-tuple read stability, the 32-digit and ±18-exponent bounds, and duplicate-key rejection are more defence than a quiesced, trusted filesystem needs. These read as implementation weeds.
*Recommendation:* they can stay because they fail closed and are cheap. They should not grow further.

**6. Severity: Nit.**
*Scope:* lines 148–152.
*Finding:* it is unclear what `created.json` is used for. It cannot go into the legacy layout, which has only `launch.json` and `controller.lock`.
*Recommendation:* say it supplies the `new.N` bytes in the guard layout.

**7. Severity: Nit.**
*Scope:* lines 9–10.
*Finding:* "provider guarantees for billing during failed stops and number of creates" is still opaque to a fresh reader.
*Recommendation:* point to the provider-contract report, or put it in plain words.

## What passes

- **Heilmeier:** objective, current practice (an ad hoc preflight), what is new, impact, risks (non-atomic, needs a quiesced filesystem), cost (none), timeline (one offline cycle) and exams (the named tests plus the full suite) are all answered.
- **Murphy:** no row closes. Rows 6, 27, 28, 35 and 51 and new-batch-service-1 through -4 exist in the register and stay open. That is consistent with an observation-only tool.
- **Reuse and YAGNI:** `factory/coordinator_inventory.py` queries the live fleet, so it does not cover this offline need, and a standalone stdlib module is justified. The tool adds no persisted state and no integration.
- **Secrecy:** contents are never read and unknown names are never printed. Poison strings are tested, and fresh CLI processes are checked for byte and mtime invariance.

## Author disposition

*(For the author to fill in.)*

Author disposition: PASS accepted. Findings 1–4 and 6–7 incorporated before implementation; defensive checks remain bounded as requested by finding 5. No blocking findings or rejections.
