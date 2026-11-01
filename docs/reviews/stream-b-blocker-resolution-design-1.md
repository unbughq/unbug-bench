**FAIL. 3 blockers, 3 majors, 4 nits.**

The legacy-case part does what you required: retire, never hold for provenance. The design isn't ready to implement because of three gaps. Its new spending rule would stop the live practice run it defers to. The legacy launch's possible unpaid provider debt is neither resolved nor explicitly deferred. And it calls the spending rule "fail-closed" when it isn't.

---

# Goldfish design review: `docs/designs/stream-b-blocker-resolution.md` (review 1)

Mode: REVIEW. Personas: zoom_out, design_critic, implementation_readiness. Standards: heilmeier-standard.md, implementation-readiness-standard.md. Worktree `t3-ded79ec5` at 9b9e5e0; the design file is untracked. I read: `docs/ENGINEERING.md`, `bin/boat-spend`, `factory/batch_service.py` (`plan`), `factory/batch_holder.py` (`_source`, `reserve`, `_post`), `docs/designs/stream-b-practice-blockers.md`, `docs/designs/stream-b-delayed-creation.md`, the cleanup-qualification `report.md` and `observations.json`, `batch-service-inventory-20261030.json`, `tests/factory/test_isolation_timeouts.py` lines 400–465 and `tests/factory/test_batch_service_d.py`.

The four blockers are never named in the design. I read them as the scanner's `outstanding_proofs`: historical-provenance, controller-ownership, provider-creation-deletion and cumulative-cost.

## Verdict: FAIL

## What is sound

- **Legacy retirement meets the founder's rule.** Section 2 turns `legacy_projection_unbound` (a hold) into a final `legacy_retire`. It does this before the diagnosis gate and before stored facts are read. It needs no provenance reconstruction and treats retirement as an end state, not a case pass. That is "retire-only, never hold", with no import path.
- **The holder rejection is in the right place.** `batch_holder._source` runs before `money.advance_locked` in `reserve` and again in `_post`. Rejecting there stops money movement, account selection and dispatch.
- **The deferrals of provider cleanup cost and deployment give reasons.** It also keeps the USD 5 limit instead of quietly loosening it, and does not count an empty fleet or a retired case as cleanup proof.
- **It adds no speculative runtime code**: no new ledger, supervisor, adapter or reset path.
- **No Murphy rows are closed.** That is correct for offline exclusion tests.
- **Tests are not required to prove cloud behaviour**, and the design says so.

## Blockers

**B1 — The new spending rule makes Boat admission single-use, which blocks the live practice it defers to.**
*Severity: Blocker. Scope: Change item 1 (lines 23–39) and item 3 (lines 63–75).*

- **The mechanism.** A finished record with no attributable charge permanently refuses new admission. Nothing can ever attach a charge: no receipt import, no reset path, and `--finish` never releases. So the first worker that finishes on a control home blocks every later `--check` there, for good.
- **Who it hits.** Batch relaunches get a new spend record and so a new `--check`. Non-batch `factory/launch.sh` callers are also blocked; `stream-b-delayed-creation.md` notes the holder gate does not cover them.
- **Why that breaks the plan.** The practice exams this design relies on need more than one worker in sequence. `stream-b-practice-blockers.md` requires "retirement, relaunch, settlement and terminal finish" (lines 145–147), and line 74 counts every worker across relaunches. Settling final charges is deferred to "the live practice run before any later implementation releases these holds". The relaunch part of that run can't happen under this code. The deferral goes in a circle, and the design never says so.
- **Fix — pick one and state it:**
  - Say plainly that after the first finish, all Boat admission on the control home is refused until a later reviewed settlement increment. List the relaunch, settlement and multi-worker exams as blocked by that increment, not as live-practice exams, and note the effect on non-batch callers.
  - Or define a reviewed settlement now (for example, charge finished records at an approved conservative amount once the provider ceiling is obtained) and make that the practice entry condition.

**B2 — The four blockers are never listed, and controller ownership (legacy launch `b275`) is neither resolved nor deferred.**
*Severity: Blocker. Scope: lines 9–13, 59–61 and 63–64.*

- **The list is missing.** Item 3 promises "a handoff report with the four blocker dispositions" but never says which four, or which disposition each gets. You require each one to be resolved, or deferred to live practice with a reason. The design has to say that itself, not leave it to the report.
- **`b275`'s possible provider debt is in limbo.** Section 2 retires `b275` "as case work" and says "unknown provider debt stays unknown". The earlier design (`stream-b-practice-blockers.md` lines 46–52) said "If the provider cannot resolve it, admissions stay disabled". This design replaces only the hold for case *eligibility* (line 12). It is silent on whether that earlier condition still blocks admission.
- **The new ledger can't see it.** The live ledger was `missing` (`observations.json`), so `b275` has no record and the cumulative check never counts its debt.
- **Fix.** Add a four-row table: blocker, disposition (resolved / deferred to live practice / deferred to a named later increment), reason, and the exact exam. For controller ownership, state one of two things:
  - `b275`'s unknown debt blocks first admission until it is reconciled live, with the required evidence named;
  - or it is accepted as unbounded, unledgered exposure that the practice owner must re-approve along with the USD 5 policy.

  Either is consistent with retire-only for the *case*. Saying nothing is not.

**B3 — "Fail-closed unknown-liability accounting" overstates what the rule does.**
*Severity: Blocker. Scope: lines 31–35 and 71–72.*

- **The inconsistency.** The design says TTL amounts are estimates, not bounds, and refuses on finished records because their cost is unknown. But it still admits new work while other `reserved` holds exist, summing their TTL estimates against max-spend. An active reserved worker's cost is just as unbounded as a finished one's, so the rule is estimate-based for in-flight work.
- **Fix.** Either refuse admission whenever any other unknown-liability record (reserved or finished) exists — that is simpler and matches practice's one-job limit — or drop "fail-closed" and record concurrent estimate-based admission as an accepted risk, deferred with a reason.

## Major

**M1 — Earlier reviewed contracts and existing tests are contradicted but not marked superseded.**
*Scope: item 1; Tests.*

- **The design contract.** `stream-b-delayed-creation.md` lines 29 and 44–48 require that admission *excludes* historical `reconciled_expired` entries from the totals and that `--finish` still works on them. This design reverses that without saying it supersedes it. The `isolation-timeouts.md` ledger paragraphs are also affected.
- **The tests.** Two existing tests assert the opposite of the new behaviour:
  - `tests/factory/test_isolation_timeouts.py::test_concurrent_admission_reserves_whole_envelope_and_finish_observes_account` (lines 432–435: retry admitted after finish);
  - `::test_historical_expired_release_remains_compatible` (line 454: `next.json` admitted).

  The design should name these as reversed and say which file gets the new subprocess tests. Otherwise the implementer has to guess.

**M2 — Paths and exact behaviours are missing (zero-decision rule).**
- No path or schema for the "frozen public retirement disposition" or the handoff report. Name both, plus the fields — at least the inventory digest and, for both the Mac and VM sides, case, `card_sha256`, `card_archive_sha256` and file sha256s.
- On refusal, it doesn't say whether the spend record is still written with `allowed=false` (today it always is, and callers may read it). It also doesn't give the refusal message text.
- It doesn't say whether ledger validation also runs on `--finish`, or what `--finish` does with a malformed ledger.
- It doesn't say what happens if `retirements/<case>/<generation>.json` already exists with different content. Say: refuse, unchanged.
- It doesn't name the exact retirement-record fields or the fsync/atomic write. Say: reuse `atomic_json` inside the existing `batch_money.locked`.
- It doesn't say what `plan()` returns for a retired generation when `DIAGNOSIS_ENABLED` is false. Currently the gate returns `diagnosis_unavailable` first; the design wants retirement ahead of it, so say the new order explicitly.

**M3 — Heilmeier gaps.**
- The objective is written in internal shorthand ("B planning boundary", "holder _source", "D") rather than plain language.
- There is no timeline.
- Impact (who benefits, what changes for the batch) is only implied.

Add a short plain-language objective and a timeline line.

## Nits

- **N1.** Say that the Hetzner path (`ledger_path is None`) is outside the cumulative rules.
- **N2.** `plan()` has no production caller today (tests only), so the holder-side rejection is the real enforcement. Say so, so nobody reads the planning-side retirement as an active production guard.
- **N3.** Build the retirement path from the already-validated journal key and generation hash. Don't take raw input; this avoids path injection.
- **N4.** Case names are already committed in `batch-service-inventory-20261030.json`, so a "public" disposition adds no new leak. Worth one sentence given the case-secrecy rule.

## Scope honesty against your requirement

- **Legacy cases (retire-only, never hold): met.**
- **Provider cleanup cost: honestly deferred**, with the provider-contract or re-approval precondition.
- **Deployment: honestly deferred** to live practice.
- **Cumulative cost:** claimed as resolved in code, but overstated (B3), and it quietly blocks the live practice it defers to (B1).
- **Controller ownership (`b275`): neither resolved nor explicitly deferred (B2).**

The design passes once B1–B3 are fixed. M1 and M2 should be fixed before implementation so the implementer has no choices left to make.

## Elephant disposition

Accepted B1–B3, M1–M3 and N1–N4. Revision 2 removes the fail-closed financial
claim, explicitly blocks successor admission until reviewed settlement exists,
refuses any other reservation, names all four user blockers and places b275
provider-debt reconciliation before first admission. Added exact record/refusal
contracts, affected tests and supersession, objective, timeline and scope limits.
No blocking finding rejected. Fresh design review required before implementation.

