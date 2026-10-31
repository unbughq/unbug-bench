# Stream B practice blockers: launch prerequisites and first increment

## Problem and authority

The dormant preparation at e63a8aa cannot run the practice lifecycle. This addendum
supersedes the checkpoint-only bootstrap and Claude-only practice assumptions in
stream-b-practice-preparation.md and stream-b-activation-practice-plan-20261031.md.
Parent authorizes design and offline implementation, not launch, deployment, paid
model probes, pushing or merging. Design against A's reviewed account-2 branch at
1fff453. Parent subsequently directed integration of factory-simplify c32e884;
that merge brings A, D lane 2 and E loaded cleanup into this branch. Claude
reservation rules stay intact.

Practice uses one fresh case from an empty checkpoint if no eligible authenticated
same-batch checkpoint exists. Use the existing public marketplace practice target (projects/marketplace and
scenarios/dev/S13-marketplace), the small Python/SQLite overlay on the required
Medusa stack. A fresh source-port case must enter through normal admission; this
is not a restored/imported S13 checkpoint. Pin a valid rotation slot (1..8), never
the preparation candidate's invalid 0, and inspect the project descriptor before
activating.
Do not import the legacy archive or manufacture authentication. If that project
cannot exercise the lifecycle within the bound, stop qualification, not widen it.
Use A's bounded OpenRouter DeepSeek v4.1 flash route (about USD 1.17 maximum per
call), with MiMo (about USD 1.71) only as an explicitly pinned alternative. Pin all
model roles, including reviewers, to the selected cheap profile; no accidental
Claude default. This is a required future plumbing-only profile, not a presently
valid production CLI combination: model_runtime.select_models requires four
independent families and a Claude/Codex strong calibrator. The future policy
increment must define and review how the cheap plumbing exercise stops before
case-quality scoring, without relaxing production independence or calibration
rules. Do not simply pass the same cheap model to every role and claim readiness.
This incompatibility remains part of blocker 8. Keep USD 20 cumulative model money, USD 5 infrastructure, one
concurrent job, no replacement/diagnosis and a 60-minute maximum worker lifetime.
These are plumbing checks, not case-quality qualification. Reservations still
limit how many calls fit. Validate actual maxima against the integrated release.

Account identity is a separate check: later, one minimal Claude call outside the
batch money channel, in an isolated usage window, costs cents and is correlated
with the founder's private account-2 usage. Record only UTC window, invocation ID,
public selected label and the founder's confirmation. No tokens or fingerprints.
This task performs no call. A failed/inconclusive identity check remains a blocker;
it never lowers the USD 50 batch Claude invocation reservation.

## Ordered change for blockers 4 through 8

1. **Legacy ownership (6), before activation.** Keep holder/resume units disabled.
   Preserve legacy launch b275ffccd6134a33833853ad1d31ed16 and its launch record.
   A free lock and empty inventory are insufficient retirement evidence. Reconcile
   its provider creation request and any delayed outcome to a positively owned
   worker or definitive non-creation. Record disposition through the existing
   controller ownership protocol; do not delete the record or fabricate completion.
   If the provider cannot resolve it, admissions stay disabled.
2. **Delayed cleanup (7), before any creation request.** A later cleanup increment
   must durably bind launch/operation identity, provider request identity and an
   absolute expiry before submission. An independent control-VM supervisor must
   reconcile uncertain creation after holder restart and delete positively matched
   late workers even after expiry. It must never treat one empty inventory as
   final non-creation. Reuse Boat deletion receipts and complete inventory checks;
   retain ownership until deletion completion or definitive non-creation. Bound
   infrastructure exposure including delayed visibility, retries, storage and
   egress within USD 5; no launch if provider semantics cannot establish that bound.
   The post-create systemd-run timer in the old plan is insufficient. This needs
   provider contract evidence and its own implementation review, not a timer tweak.
3. **Controller handoff (4).** Keep the batch guard in factory_auto_resume: batch
   checkpoints collect, publish, ACK and retire, then use ordinary holder launch
   from the authenticated generation. Never enable legacy same-worker auto-resume
   for batches. The future scheduling owner must durably link each acknowledged,
   retired provider-wait generation to at most one successor, honor retry_after
   and batch deadline, preserve the owner money hold, and revalidate router
   admission at invocation time. A stale requested account is transport input,
   never permission to use account 1. A at 1fff453 enforces actual eligibility.
   Crash tests must cover before/after reservation, transport uncertainty,
   collection/ACK and retirement, with no duplicate creation/admission. TTL and
   infrastructure accounting include every worker across relaunches.
4. **Router configuration (5).** After integration, install the existing
   unbug-model-router.service and its root-controlled /run/unbug-bench/router.json
   and router.env through the existing secure provisioning flow. Pin persistent
   database, account availability and capacities; include factory account 2 and
   only policy-authorized fallback labels. Keep bearer material in the existing
   secret channel, never this report. Verify worker reachability/authentication,
   durable lease/wait replay and OpenRouter availability before enabling holder.
   No new scheduler or permissive defaults. Missing config refuses admission.
5. **Release and policy review (8), last.** Build immutable pins only after A and
   the lifecycle/cleanup increments are integrated. Replace the preparation-only
   dry-run manifest with a reviewed fresh-launch cheap-model candidate, validate
   all role flags, TTL, spend and deadline using batch/key_holder validators, and
   review the exact policy/release hashes. Old staged pins are obsolete; do not
   overwrite them. Keep HOLDER_ENABLED and DIAGNOSIS_ENABLED false in this change.
   Activation needs a later reviewed release with only holder enabled. The current
   policy is not approved by this design review.

## First coherent implementation increment

Implement only checkpoint account selection precedence in
factory/account_handoff.py:launch_accounts and its existing offline test file.
Initial accounts are defaults for bootstrap or missing account metadata; observed
checkpoint accounts override those defaults. An authorized, held router-requested
provider_wait selection overrides both. Explicit per-request account overrides
retain their existing highest precedence (batch dispatch passes an empty request).
Selection is not admission: choose continues requiring an allowed account and
held label, and A checks live eligibility before every invocation. No local
rate-limit inference, health record, secret transport, or new scheduling path.
A requested label absent from the held bundle never produces a switch;
selection stays on the resolved account. Preserve
public history and input card/policy bytes; dispatch uses the same helper.

Pass choose an initial_state built from the resolved defaults plus observed
accounts (normalizing absent OpenCode to 1 only in the state, as today), before
applying explicit request overrides. Do not change initial_state defaults,
prepare, apply or current. Test missing provider_accounts with initial Claude 2
and a requested account 1 explicitly.

Both callers adopt this precedence: batch_holder.dispatch and the non-batch
key_holder launch path. Founder jobs can still force an account through the
existing validated per-request override. Reverse the existing paused-card test
expectation from (2, 2) to (1, 2); initial_accounts is a bootstrap default, not a
checkpoint override. Keep key_holder's validation error text unchanged: an
explicit initial selection is still valid terminology for a bootstrap default.
Cost is one local implementation/review cycle, no infrastructure or model probes.
Blockers 4-8 remain tracked by the numbered preparation-report list and this
ordered addendum; no new runtime failure was observed to allocate a Murphy row.

This deletes the unconditional initial_accounts override on restored state. It
fixes one blocker-4 prerequisite, not controller scheduling, automatic 2 -> 1 -> 2
qualification, or the whole blocker. Other steps above are contracts for later
increments and remain launch blockers. No live policy/manifest bytes are changed.

## Tests and review

Use tests/factory/test_account_handoff.py with the retained opencode-failover
scorecard/policy; explicitly authored provider_wait/account envelopes exercise
fresh account 2, restored account continuity, authorized 2 -> 1 -> 2 selection,
missing/unauthorized requested key, explicit request precedence, repeatability,
unchanged inputs and public history. No encrypted fixture generated by the
implementation proves authentication; these tests prove selection only.
Run the full ENGINEERING suite to a unique retained log and commit its result.
Fresh read-only goldfish design review uses zoom_out, design_critic and
implementation_readiness; diff review uses zoom_out and implementation_readiness.
Save final reports verbatim and elephant responses only.

## Murphy rows and acceptance

No rows closed by this increment. Rows 6, 27, 28, 35, 51 and the open batch-service
rows retain their existing status. Selection tests are not real VM closure proof.
Later qualification must exercise wait, authenticated checkpoint, publication
retry/ACK, retirement, relaunch, settlement and terminal finish (a bounded terminal
stop counts; sealing is not promised), with the Mac disconnected and one holder
restart. Record complete deletion/charge evidence including delayed creation.
Natural Claude fallback is separate from the cheap-route practice; do not forge
provider-rate evidence or spend more merely to force a live 2 -> 1 -> 2 sequence.

## Controller scheduling increment (2026-10-31)

The next controller increment is specified in stream-b-controller-waits.md. It
adds automatic reservation of due provider-wait successors after authenticated
publication and retirement, using the existing source chain and money hold.
It does not enable either gate, prove a cumulative infrastructure bound or
resolve the other launch blockers. The founder's $25 all-in practice allowance
is for later execution; this increment launches no workers and makes no paid
model calls. Final offline validation and review records use the
stream-b-controller-waits prefix in docs/reviews.
