# Invalid runs never carry a scientific result

## Problem and invariant

Murphy rows 14, 22–25, 36, 38, 40 and 41 describe one boundary failure:
execution evidence is interpreted before establishing that execution completed.
`cheat_runs` counts invalid runs as rejected cheats; `calibrate` commits runtime
errors as unsolved attempts. G4/G5 feed invalid batches to the writer. Final gate
crashes are currently written as failed scientific gates. G2 accepts a model's
retrieval assertion, and collection permits missing archives.

There are two execution classifications: `valid` and `invalid-infra`. Only valid
execution reaches scientific evaluation. A valid failed judge remains a failure.
An invalid execution is retried with identical guard, seed and run count; exhaustion
leaves a resumable operational stop, without a case verdict or writer feedback.
Retries do not expand the existing economic/worker lifetime limits.

## Implementation

1. Add `bin/run_validity.py`: `InvalidInfra(RuntimeError)`,
   `classify(summary=None, records=None)` returning the two labels, and
   `require_valid(...)` raising `InvalidInfra`. Reject empty batches, nonpositive
   run counts, error/invalid counts, record errors, false/missing checker validity,
   and judge `invalid`. This is execution validity, never judge pass/fail.
   Calibration receipts use the same record error/bench-crash rule before summary,
   commit and reuse; invalid legacy suffixes are quarantined, never counted.
2. `checkpoint_evidence.read_completed` defaults to requiring validity, using that
   helper after existing structure/aggregate checks (explicit `require_valid=False`
   remains a diagnostic-only escape hatch). Factory `checkpoint` retries twice at
   this boundary, preserving all arguments. `verdicts` also requires valid records
   so no direct caller can accidentally interpret invalid evidence. Delete G10's
   exception-to-failed-attempt conversion and saved-cheat-only validity check.
   Prototype invalid execution raises, rather than consuming selection. G3 setup
   failure raises an operational exception. G1 retains structural rejection; its
   filesystem/process exceptions already propagate.
3. Gate attempts use the durable retry journal described below, with two total operational attempts per unchanged invocation. Final pipeline records an
   exhausted crash as `gates[G] = "invalid-infra"`, `terminal_stop =
   "runner_error:<type>"`, and a separate `infrastructure_gate` field. It does not
   set `failed_gate`/`failed_detail`, invoke scientific after-gate feedback, or keep
   a scientific `gate_results` entry. Stop the loop immediately. Update recovery explicitly as specified below; preserve old crash-card import support.
   Early gates must propagate exhausted infrastructure errors (the current
   continue-to-attacker behavior also spends invalid evidence).
4. G2: runner-owned retrieval in `factory/freshness_retrieval.py`, before the
   semantic reviewer. Fetch each flagged URL with urllib, 30-second timeout and
   2 MiB body limit. Store exact response bytes, requested/final URL, status and
   digest inside the private review directory. Empty/truncated/access-error pages
   are invalid-infra. For HTTP 404/410 or DNS-not-found, fetch Wayback availability
   and its snapshot; clear unreachable only when the runner verified the dead URL
   AND a successful lookup with no snapshot. All ambiguous/transient failures
   raise InvalidInfra. Give the reviewer these local bytes. Require its live/archive
   claim to agree with the runner receipt. Bind receipt paths/digests to reusable
   confirmation; old assertion-only receipts must re-execute, not clear a hit.
   Do not globally change the searcher schema or substantive same-bug judgment.
   The direct validator accepts an explicit runner receipt map; absent proof is
   unresolved. Tests mock HTTP transport, never the classifier under test.
5. Collection: replace prefix-glob acceptance with a small `factory/collection.py`
   verifier. Every collected card needs a well-formed SHA256, an archive basename
   belonging to its exact case (final or checkpoint), membership in THIS transfer's
   file list, a regular nonsymlink archive, and an exact digest match. Missing,
   malformed, substituted and stale archives fail collection. No Boat calls in tests.
6. Silent windows: apply the supplied two-number S11 public-practice patch (60 to
   120 seconds in both declarations), only in a committed copy of the public rehearsal fixture. The repo dev S11
   is a different, announced descriptor and must remain unchanged. Do not extend runtime deadlines beyond declared
   observation. Existing invalid window evidence goes through the shared boundary;
   a retry retains the same seed. No subprocess/group/deadline work owned by E.
7. G11: require completed fake-pass report with exactly one correctly bound result
   per guard and valid rerun evidence. Retry operational failure. Static forbidden
   patterns are suspicions: when fresh case traffic passes, ask an approved
   independent reviewer selected below to adjudicate the flags against promise/runtime evidence;
   explicit supported confirmation fails G11, explicit supported exclusion passes,
   unavailable/malformed/inconclusive adjudication is invalid-infra. Preserve flags
   and adjudication privately; only fixed counts leave the seal.
8. G16/G17: before semantic review, validate saved execution receipts. For a submitted
   guard with missing/invalid check evidence, rerun that exact guard/seed/run count
   and update its execution evidence atomically. Missing/capped/no-submission
   evidence is operationally inconclusive, never proof of wrong_fix/hardness.
   For malformed/inconclusive review, try the next configured reviewer whose family
   differs from writer and solver, once; do not rerun the same paid review on the
   same evidence. If none is available, stop invalid-infra without writer feedback.
   Genuine missing_info/judge_too_narrow results retain normal scientific failures.
9. Add run_validity to gate dependencies without a calibration identity version bump. Validate legacy rows before reuse;
   known invalid rows cannot survive changed policy.
   Gate versioning re-executes only affected gates; no blanket card rewriting.

## Deletions and boundaries

Delete invalid-as-unsolved conversion, all-invalid-cheat acceptance, per-call-site
clean-run policy, prefix archive fallback and repeated identical inconclusive
review. Keep infrastructure diagnostics private and public counters allowlisted.
Do not edit model_runtime/account_handoff (A), subprocess/group management (E),
launch anything, decrypt anything, use Boat, or alter restore/main checkouts.
`run_validity` is the shared helper for the parent to integrate.

## Verification and row closure

Copy public saved checkpoint summaries and numbered records from the main checkout's
`results/` into test fixtures with source paths and SHA256 provenance. Include real
all-invalid reset batches, mixed G11 crash batches, valid no-guard/reference/cheat
results and invalid silent-window output. Mutations of those real artifacts exercise
missing/partial/mismatched evidence; they are not generated by production code.
Use the public practice case, the two restore-14 public cards (read-only), the VM's
public cards obtained by the provided read-only SSH command, and the existing real
public-card corpus. Never copy keys or private/decrypted case material.

Tests exercise G6/G7 rejecting all-invalid cheats (22); G10 never committing any
runtime error, including mixed batches (23); G2 refusing assertion-only retrieval,
timeout, inaccessible archive and forged snapshot, while accepting captured live/
archive evidence (24); exact collection generation/hash (25); retries with unchanged
inputs and no writer or selection call for invalid G1/prototype/G4/G5/G7 (36/38);
practice descriptor agreement and invalid-window retry (14); G11 runtime failure
versus semantic flags (40); and G16/G17 evidence repair, independent fallback,
inconclusive stop and valid scientific rejection (41).

Replay saved evidence under old and new verdict logic and report every actual
scientific verdict change. Public cards alone cannot prove hidden raw execution:
preserve their verdicts and explicitly report this evidence limit; do not claim
cards authenticate raw runs. A previously sealed scientific verdict may change only
with a demonstrated silent wrong result. Mark a Murphy row closed only when its
real-artifact test proves the entire row; partial mitigations remain open with notes.

Run `uv run --with numpy --with scipy python -B tests/run.py`. Save every fresh
goldfish design/diff review verbatim in docs/reviews, fix blockers, and re-review.
Commit implementation and row closure references together; parent merges only.


## Review-1 resolutions (normative where they refine the steps above)

### Blame and total retry bounds (B1, B2, M1, M2)

A runtime error, timeout, false checker validity, reset failure or malformed result
alone does not demonstrate blame. The old comments declaring API-shape crashes
failed attempts are the defect this task removes. We do not infer blame from a
stage string or merely from a reference passing: neither proves the unknown run
executed correctly. A guard-caused failure is scientific only when it has a valid
judge execution (for example a business request refused and a completed judge
legitimacy check false). Preserve that as a valid rejection. Explicit negative
security probes in verify-negative test enforcement, not case execution: their
expected rejection remains valid under their existing per-probe assertions. An
`invalid-probe` wrapper outcome is operational, and cannot certify G6. An actual
`cheat-pass` is a valid G6 rejection even when the CLI's exit status is nonzero.
Missing output or nonzero without a confirmed cheat-pass is invalid-infra.

Deterministically erroring guards may remain unknown; we deliberately do not
invent a case result from that uncertainty. Bound this with one private durable
`infra-attempts.json` journal, implemented in run_validity, keyed by SHA256 of
canonical operation identity. For checkpoints identity includes case bytes, guard
bytes, scenarios, seed, runs and slot. For gate-level operations include gate,
case digest and gate runtime inputs. Record a running attempt before execution,
invalid error type after failure, completed status after success. At most two
attempts total for unchanged inputs, across resumes. An abruptly killed running
attempt consumes one infrastructure attempt, never a scientific attempt. Completed
units may execute normally when deliberately requested again; only invalid attempts
consume retry allowance. No nested gate retry of an exhausted checkpoint: propagate
`InfrastructureExhausted(InvalidInfra)` immediately. Retry gate wrappers only for
exceptions not already exhausted by a nested unit. Handled budget/provider-wait and deliberate-pause exceptions clear the running marker
without consuming infrastructure allowance and always propagate. Exhaustion is `infrastructure_exhausted`, a nonretryable
operational stop awaiting stream D's diagnosis, not an indefinite runner_error
resume loop, a retired case, or a failed gate. A changed execution input gets a
new key. No additional router/process-group functionality is introduced.

For G10, save `pending.json` beside `results.json` after copying a completed model
submission into ws/guard, before checkpoint. It contains try number, workspace,
identity, guard digest and capped/completed stop reason. Resume validates the exact
workspace/digest/identity and grades it without any model call. Checkpoint retries
use that ws/guard with the original seed + try, runs and slot. Do not commit a
result or advance the try on invalid execution. Remove pending only after a valid
atomic AttemptSeries commit. A no-submission result under the deliberate solver
time/call cap remains recorded as no_fix_submitted; it cannot alone prove wrong_fix
or hardness in G16/G17. The program's execution timeout is invalid-infra.

Delete early_cheat_check's catch-and-continue path: use the same durable retry
journal and propagate exhaustion. Convert its ordinary RuntimeError diagnostics
without creating unbound counters. Delete G14's local clean predicate and require
valid summaries before its scientific conditions. Strategy checkpoint/silent_window
boundaries raise InvalidInfra through require_valid; keep their diagnostic tails.

### Stop schema and readers (B3)

Define infrastructure_gate = {"gate": "G<number>", "error_type": fixed exception
class name, "classification": "invalid-infra", "exhausted": boolean}. Public
terminal_stop is infrastructure_exhausted if exhausted, else runner_error:<type>.
No failed_gate, failed_detail or scientific gate_result is created. Public progress
uses interrupted for infrastructure exhaustion. gate_minutes remains timing only.

Update recovery.crash_stop/recoverable_crash to recognize and validate this schema
alongside old type-only crash cards. restore_gate_crash authenticates the same
private crash files for both, preserving legacy compatibility and skip-build
reentry. require_restart_stop/restart eligibility must refuse exhausted states;
it must not treat them as ordinary retryable crashes. The same exhausted check
must precede rereview_stop, freshness_retry_stop, gate_only_continuation,
raised_limits, and holder/restart public decisions. coordinator delegates these
policies; its no-failed-gate test must not admit exhausted cards. scorecard_text
reports stopped infra independently of failures. Collection checks archive integrity
regardless of verdict and accepts stopped infra archives. No caller should change
an invalid-infra gate into a science failure. Tests load actual public crash cards,
make the new representation in memory, and check all policy entry points.

### Retrieval contract and review selection (M4, M5)

G2 executes inside the worker's runner (the existing factory has networked model
and search CLIs there). Failure to reach public HTTP is infrastructure, never a
freshness result. urllib uses HTTPS/HTTP only, rejects credentials in URLs, follows
ordinary public redirects and records the final URL. No proxy login or credential
attachment. Fetch up to 8 MiB with a strict bound: oversized bodies remain unknown,
exhaust the durable retry allowance and enter diagnosis rather than pass. Do not
pretend truncated text proves absence. This is an explicit limit, not a retrieval
success. Wayback success means HTTP 200, valid JSON object with archived_snapshots
object, and either empty closest or closest.available true, status "200", an
exact web.archive.org snapshot of the original URL, and a successful nonempty
snapshot fetch. Other responses are unknown. Verify byte hashes, URL and timestamp
on reuse; expiry follows the existing 24-hour receipt TTL. Bind confirmation_contract
2 and retrieval paths/hashes in every receipt, including late_recovery's clearance
validator; contract 1 assertion-only confirmations must reexecute. Tests patch only
urllib transport and use saved practice URLs/reviewer outputs and captured public
HTTP bodies. Old synthetic confirmation tests install an explicit fake transport;
new real-artifact tests test actual retrieval binding.

G11/G16/G17 choose from c.models["reviewers"] in configured order, excluding the
writer and strong-solver families. Their chains are already approved by role
configuration; do not invent another model. Use the normal case ledger/model_call
budget and existing reviewer per-call timeout. At most one attempt per configured
independent family for unchanged evidence, persisted with the private review
receipt. Exhaustion is invalid-infra, never a repeated identical paid review.
G11 reuses public_verdict's rule_violation/checker_false_positive/inconclusive
vocabulary from factory/g11_review.py. Require one row per guard with all flags
accounted for and nonempty evidence; the prompt requires the actual contestant
contract and saved runtime evidence. Its cost is ordinary independent review,
not a writer round; failed transport is infrastructure waste. Static scan flags
without valid runtime evidence cannot trigger writer repair. G16/G17 use the
existing tries/label/finding/evidence schema; before review, rerun a submitted
failed guard only when raw checkpoint evidence is absent/invalid. Store repaired
observations plus exact seed/runs in pending.json/results.json through
calibration.atomic_results. No submitted guard means insufficient evidence; request
a replacement calibration attempt within the same existing case economic envelope
by quarantining only the unreviewable suffix, then invoking calibrate for that
folder/role/exposure. Do not re-run already valid solver submissions.

### Compatibility and collection exceptions (M6, M7)

Do not bump calibration identity's schema version. Validate runtime error counts
and bench_crash before any summary or reuse. Changes in actual execution-dependent
sources still invalidate the affected mechanical receipts under existing source
fingerprints; do not clear unrelated stored passes by hand. G8/G9's semantic panel
receipts are not cleared solely for the new validity module. A baseline-to-current
identity migration may preserve a calibration row only when every non-policy input
matches and old policy digests equal the pinned base commit 6f17c5f. Document the
exact old digest allowlist in the implementation; reject unknown historical code
rather than assume equivalence. This prevents paid recalibration solely for this
policy while quarantining rows with explicit execution errors.

Collection permits archive-less cards only for explicit {kind: "provider-preflight",
scope: "availability_only"} probe receipts or {status: "startup_failed", gates: {}}
with no sha256/archive and no unwiped WORK. Existing ordinary cards are never
inferred to be probes from missing fields. Final archive basename is
<case>.tar.gz.age; checkpoint is <case>.checkpoint.tar.gz.age. A legacy card lacking
archive but carrying sha256 may use exactly those two names and must find exactly
one matching hash in this transfer; prefix globs are forbidden. Stale means the
bytes do not match the card's hash, even if the basename matches. No archive of a
different case/generation can cover WORK or authorize disposal.

### Exact artifact inventory and closure limits (M3, M8)

Committed gzip JSON fixtures in tests/factory/fixtures:
- invalid-runs-real.json.gz: six source groups, each embeds its original absolute
  source directory and SHA256 for every saved file. reset-invalid is
  results/runs/20261016T212940264293Z-s13-final-cross-service (3 trials); g11-mixed is
  results/infrastructure/2026-10-21-public-suffix-preflight/serial-diagnostic-attempt3/
  source/results/factory-slots/97/runs/20261021T160524422173Z-g11-rerun (5 trials);
  plain/reference/cheat are results/factory-slots/89/runs/
  20261020T162325625246Z-public-canary-none,
  20261020T162345598620Z-public-canary-reference,
  20261020T162415072204Z-public-canary-refuse-all (one trial each);
  window-invalid is results/remote/phase2-live-window-r2/task__cVbtpxn/steps/quiet/
  verifier/checkpoint.json (one invalid window).
- invalid-runs-practice.json.gz: 64 public files copied read-only from
  /Users/bugsincode/Developer/unbug-bench-late-rehearsal-20261026/
  case-late-rehearsal-marketplace-20261026/case, with provenance/hashes. S11 patch
  source is /Users/bugsincode/Developer/unbug-bench/results/infrastructure/
  2026-10-29-real-relaunch/g15-later-release.patch. Commit this patch beside the
  fixture and test applying it to a temporary fixture copy, never the source.
- invalid-runs-public-cards.json.gz: two restore-14 public cards plus 56 VM cards
  from the user-provided read-only SSH identity/known-host command, whose remote
  operation is only python3 reading /home/user/unbug-bench/sealed/*.scorecard.json.
  Offline tests never depend on SSH. Existing 58-card corpus is also replayed.
- Add saved guard-caused legitimate rejection/traffic-error evidence and the real
  verify-negative invalid-probe receipt if available. If unavailable, tests can
  prove the shared invalid handling with real reset/mixed batches, but the missing
  end-to-end coverage leaves that portion of rows 22/23 open. Do not fabricate a
  real provenance claim.

The VM card case-20261017T125556Z-18681d explicitly reports two strong run_error
outcomes while G10 passes and difficulty is hard. This is a demonstrated silent
wrong result: the new projection must withdraw G10/hardness pending valid evidence.
Other public cards are preserved; where no raw trials were available, report that
this is card-level compatibility, not proof of the original hidden execution.
Row 14 cannot claim that 120 seconds is performance-qualified without a new live
run (which is prohibited here). Mark its invalid-as-feedback path covered, but
leave the schedule-duration qualification open. Stream D owns diagnosis/replacement
on infrastructure exhaustion; this stream supplies the non-scientific stop state.


## Cross-stream integration and implementation details

Read docs/designs/interfaces.md at factory-simplify c49c754. This change does not
change router leases/provider_wait, settlement/reservation shapes, the B batch
journal, sh(), or launch.sh lifecycle. Minimal shared-area edits are:
- recovery.py: recognize the non-scientific infrastructure stop and refuse retry
  exhaustion before existing recovery eligibility checks (B/A consumers).
- launch_manifest.py: ship/qualify run_validity.py and the policy compatibility
  manifest, and include collection.py in host inputs (B/E consumers).
- collect.sh: report unwiped case identities and call exact archive verification
  before reporting collection success (B lifecycle consumer; row 25 is C-owned).
- checkpoint timeout retries retain one existing absolute allowance; no subprocess
  or process-group implementation is changed (E contract).

Submitted fixes use private pending-<try>.json receipts beside results.json;
separate try receipts preserve a legacy invalid suffix without rebuying any solver.
execution.json retains the actual validated summary/records in the protected
workspace. The pinned policy-only migration is factory/invalid-runs-compat.json:
unknown source digests or any non-policy change refuse migration. G8/G9 migration
also verifies the original stored-input signature and all supporting evidence.
Other changed execution gates revalidate under normal fingerprints.

G2 independently retrieves every structurally valid logged result URL before
counting it, including unflagged searches; flagged semantic judgments additionally
bind their own runner receipt and every response byte. An unresolved semantic
adapter result carries classification invalid-infra for GatePipeline.check; the
same adapter can still return repair counters to ensure_freshness without
publishing a scientific failure.

Additional committed artifacts include the genuine negative-invalid stdout and
negative-control report, guard-traffic-error, the public suffix case.json matching
those execution records, and the real public fake-pass report. Tests never pair
marketplace practice metadata with four-path suffix records for scientific scoring.
No original artifact or sealed verdict is rewritten.

The tracked tools/open-g2-verdicts.py diagnostic reader consumes the same receipt
contract. It loads verified runner bytes for current confirmations and reports
legacy assertion-only rows as unresolved, keeping the historical counter separate.
Its interactive unsealing/credential path is unchanged and was never invoked here.

Full-suite integration adds run_validity.py to Harbor's existing frozen runtime
copy list and names the four C worker additions in the independent upload test.
The orphan test_restore_failover_bundle.py referenced an absent, untracked rescue
finalizer. It is deleted, matching E commit e26fb55's cleanup; unified finalization
remains covered by tests/tools/test_late_restore_bundle.py. No rescue helper or
alternative launch path is restored.
