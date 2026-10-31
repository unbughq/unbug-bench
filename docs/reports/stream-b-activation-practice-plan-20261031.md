# Stream B activation handoff and proposed practice

2026-10-31. Preparation only. See the preparation record below for live read-only
checks and dormant release staging. No worker or model call was launched. Both
code activation gates remain false.

## Founder account decision

Case-making workers must start on the founder’s SECOND Claude account.
Builder agents retain the first. Workers may use the first only while the
second is rate-limited, never merely because it is busy, unavailable, missing,
or expired. This decision is not fully enforced by the current router.

Credential selection is split across `factory/model_router.py` (`ACCOUNTS`,
`routes`, `_account_order`, `Store.rpc`), `factory/account_handoff.py`
(`launch_accounts`, `choose`), `factory/batch_holder.py` (dispatch environment),
`factory/launch.sh` (filters the bundle to the selected Claude token), and
`factory/model_runtime.py` (loads the admitted account into the child environment).
Public label `claude-factory-token-2` means factory account 2;
`claude-token` means account 1. Do not confuse the former with the exam-only
`claude-token-2`. Labels do not prove the human account identity.

Smallest proposed stream A increment: keep the existing transport and account
labels; enforce a worker Claude lane eligibility rule inside the authoritative
router. Prefer account 2 regardless of saved card preferences or local token
presence. Admit account 1 only when account 2 has a current, unexpired,
provider-reported rate-limit health record for that account or applicable route.
Do not infer rate limitation from concurrency occupancy or a synthetic wait
reason. Treat `quota` as qualifying only if its provider classification proves
subscription rate exhaustion, not credit/billing failure. Apply the same lane
eligibility to capacity and FIFO admission; expired health restores account 2
preference. Existing in-flight leases finish normally. Missing/expired account 2
credentials refuse or wait for provisioning; they must never enable account 1.
Test normal selection, busy/missing/expired/outage second account, genuine rate
limit, expiry, saved account-1 preferences, and account-1-only configuration.
This is a proposal for A, not a router change in this B task.

The reviewed practice policy must set each worker job’s
`initial_accounts: {"claude": 2}` and `claude_accounts: [2, 1]` only after
that eligibility rule is implemented and reviewed. Router account availability
must include the second label. Before that rule lands, a second-account-only
router allowlist prevents prohibited fallback, but does not demonstrate the
required fallback behavior and is not full acceptance. The existing holder
handoff can transport a permitted router selection without pushing both tokens
to every worker. Never change builder account selection as part of this work.

VM credential presence and human account mapping were not inspected. If absent
or expired, the founder must provide a valid Claude Code OAuth/setup token
created while authenticated to the SECOND Claude account, provisioned securely
under `claude-factory-token-2` in the control VM’s existing encrypted factory
secret bundle. The first-account fallback credential stays under `claude-token`.
The founder must confirm which human account each label represents. Use the
existing secret provisioning flow, never chat, command arguments, reports or
logs. A label-only availability check and authenticated preflight must pass
before launch; no secret values should be printed or persisted by this agent.

## Founder-approved spend; launch remains blocked

Founder approval dated 2026-10-31: all-in incremental spend cap USD 25, comprising a USD 20 cumulative
model-money bound and at most USD 5 for the disposable worker and incremental
storage/egress. Concurrency one, one case, no automatic replacement or diagnosis,
and a 60-minute worker TTL. The founder approved these spending bounds, but this task authorizes preparation
only. The parent must confirm A is merged before any live run. Verify provider
pricing and conservative infrastructure exposure before launch; refuse if TTL
plus cleanup/egress cannot fit USD 5.
The model bound is enforced by the existing money channel, including conservative
reservations and infra-waste calls. Do not claim the worker TTL alone is a hard
provider billing cap. The run may stop at its bound without sealing a case.

After A is merged, the remaining blockers below are resolved and the concrete
manifest/policy pass review: pin the
reviewed release and trusted closure on the control VM; validate restore scope,
R2 publication configuration, account-2 credentials and router policy; create a
fresh practice batch with a saved authenticated case/checkpoint and the bounds
above. Enable only the holder gate in the reviewed practice release; keep
DIAGNOSIS_ENABLED false. Launch one uniquely labelled throwaway worker through
the holder. Record operation ID and public evidence. Disconnect the Mac and
restart the holder once while work is active, then verify the same operation
resumes without duplicate creation or reservation. Exercise one transient
publication failure, let the holder replay, and verify the durable generation,
ACK, pointer, money state and chain-head status agree. Capture bounded retry and
retirement evidence. Do not deliberately consume five paid worker attempts.

Delete the throwaway worker on success, failure or timeout using the controller
cleanup path and an independent control-VM TTL cleanup. Verify absence by worker
ID in provider inventory and retain deletion/charge evidence. If cleanup cannot
be verified, stop admissions and resolve deletion before calling practice done.
Keep only encrypted artifacts and public evidence; disable the practice gate.
Only then assess Murphy closures with real VM evidence. No row is closed here.

## Deferred B hardening

Follow-up increment: per-invocation ACK evidence for bookings, handed over in
`docs/reviews/stream-d-money-design-8-codex.md`. Bind prior ACK booked charge,
estimate and current attributed bookings to each invocation; validate each
invocation’s permitted decrease independently so a stale release or late booking
cannot subsidize a different invocation’s unsupported reduction. Include the B1
and B2 counterexamples from that review. This requires its own design, goldfish
reviews and real-artifact regression coverage. It is not implemented here.


## Preparation record and launch blockers

Public evidence: `stream-b-preparation-preflight-20261031.json`. No secrets were
printed or newly persisted. Decryption for label listing stayed inside VM pipes.
The existing scoped key could not decrypt the saved dry-run archive.

Committed manifest: `factory/batches/b-practice-20261031.json`. It pins one job,
concurrency one, USD 20, one-hour worker TTL, launcher max-spend USD 5 and no
replacement. Deadline 2026-11-07T00:00:00Z prevents stale admission. That date is
not a worker lifetime. Account 2 is the only allowed Claude account until A lands.
`--dry-run` prevents this preparation candidate from creating a real case. It
cannot demonstrate paid account routing and is NOT an alternative acceptance run.
Do not remove that flag to get around checkpoint authentication.

Policy candidate: `stream-b-practice-policy-20261031.json`. Release record:
`stream-b-practice-release-20261031.json`, built from commit 6ac450e. Release SHA256
`0781679022b81b4c3beff3c0e0595fbe19128c568e22f5737da61b8e0cbfb1ab`.
The generated six-file release is staged on the existing disk at
`/home/user/.unbug-control/releases/practice-6ac450e`; no new capacity was bought.
The source and active policy were NOT replaced. The existing holder and resume
timer were deliberately stopped after checking a complete empty worker inventory
and the lone unresolved controller's free lock. Both units were also disabled so reboot cannot silently reactivate them.

This is not a reviewed launch policy: the implementation sub-agent must hand it
to the parent for fresh goldfish design/diff reviews. The activation code itself
has the reviews listed in stream-b-activation-suite-20261031.md. No review of new
policy bytes is implied by those earlier reviews.

Launch is blocked by all of the following:

- Parent confirmation that A's reviewed account-2 change has merged is pending.
  Rebuild the release and policy after that merge; allow [2, 1] only then.
- The sole saved dry-run candidate is `case-20261014T130816Z-a869de`, archive
  `case-20261014T130816Z-a869de.tar.gz.age`, 2,027,790 bytes, SHA256
  `d93308338261cf32d468ec21ca5e619eea06b6585451a2cf51b644e2102ba9c8`.
  Its hash matches its card, but control-key decryption failed and it lacks a
  batch-release binding. It is a legacy sealed archive, not an admissible
  checkpoint for the new job. No authenticated eligible practice checkpoint was
  found. Do not rename it, forge an ACK, or import it through a test fixture.
  The holder's current resume predicate requires a prior same-batch operation,
  authenticated output, publication ACK and retirement. A fresh batch cannot
  simply resume this legacy archive. Parent must settle the practice bootstrap
  against the one-launch-path rule before the acceptance run is executable.
- The VM has legacy launch `b275ffccd6134a33833853ad1d31ed16` containing only
  launch.json and a free controller.lock, with no complete marker. Empty cloud
  inventory does not retire that ownership. Preserve it for explicit disposition.
- The VM active policy has no batch; router and batch services were inactive;
  there are no batch money files. `bin/unbug` is absent, so an actual VM
  `unbug status` baseline returned exit 127 (bin/unbug not found).
  Deployment/activation is incomplete.
- Both Claude labels are present (`claude-factory-token-2`, `claude-token`), as
  are both OpenCode labels. Presence is not token validity or human account
  mapping. Authenticated account-2 preflight, router configuration and R2
  publication access remain unverified. The r2-env bundle label is present.
  `/run/unbug-bench/router.json` and `router.env` are absent. No Claude credential
  is confirmed missing.
- USD 5 exposure and independent cleanup still need launch-time validation.
  TTL and --max-spend alone do not impose a hard provider billing cap.
  Read-only billing shows enough credit for the code's static USD 0.036 one-hour
  estimate, but less than USD 5. No infrastructure reservations ledger exists.
  The CLI help did not confirm the current default rate; storage/egress and
  delayed deletion exposure remain unverified. No admission hold was created.

No Murphy row is closed. Spend is USD 0 model / USD 0 incremental infrastructure.

## Commands and their readiness

These are command interfaces for the eventual run, not permission to execute
now. There is deliberately no fabricated checkpoint digest or enabled policy.
The source/import blocker prevents a complete executable launch command today.
Run from `/home/user/unbug-bench` as user on the control VM after installation:

```sh
python3 -B factory/batch.py verify --root /home/user/unbug-bench \
  --release /home/user/.unbug-control/releases/practice-6ac450e \
  --sha256 0781679022b81b4c3beff3c0e0595fbe19128c568e22f5737da61b8e0cbfb1ab
python3 -B bin/unbug status
python3 -B factory/key_holder.py status
bin/boat-call list --json
```

The release verification currently refuses against the legacy VM source, by
construction. Replace both release path and hash with the reviewed post-A pins;
never modify an existing release in place. Validate the policy with
`key_holder.policy_load`, not by starting the holder. Do not call money.authorize
as a dry check: the legacy function creates schema1 money, which the new holder
correctly refuses. Before launch the new batch should have no money.json; after
reservation it must be schema2, hold at most USD 20 and have no incidents.

After all blockers and review are resolved, set CHECKPOINT to the authenticated
same-batch generation selected by that resolution (no default or empty value):

```sh
test -n "${CHECKPOINT:?authenticated same-batch checkpoint required}"
python3 -B factory/key_holder.py launch --batch b-practice-20261031 \
  --job practice --checkpoint "$CHECKPOINT"
python3 -B bin/unbug status
```

Save the returned operation_id and launch_id as public evidence. Verify the
reservation's worker_id against that launch's ids and created event. Inspect
schema2 money, the generation manifest, outbox ACK, current pointer and chain
head with the validators in batch_holder/batch_status. Restart the holder only
once the independent cleanup is armed; confirm the same operation and worker
remain, with no extra reservation or creation.

Normal cleanup is the existing launch controller's collect-then-delete path.
For emergency deletion of the positively identified practice worker, use the
provider interface below; WORKER_ID must match BOTH reservation and launch ids.
The deletion is intentionally independent of successful collection:

```sh
bin/boat-call delete "$WORKER_ID" --yes --json
# Save the public returned operation.id as DELETE_OPERATION_ID.
bin/boat-call deletion status "$DELETE_OPERATION_ID" --json
bin/boat-call list --json
```

Require deletion operation targetId == WORKER_ID, kind == sandbox,
status == stage == completed, and timezone-aware completedAt; then require a
complete inventory page (hasMore == false) with that exact worker ID absent.
Inventory absence alone is not a deletion receipt. Preserve the request and
completion receipts. An unknown delete response needs reconciliation, not a
second blind delete. Emergency deletion does not fabricate a holder retirement
ACK; the receipt must be installed through its existing ownership verification.

The independent control-VM TTL must be armed for the identified worker with a
root-owned systemd timer, separate from holder/controller lifecycle. Exact
single-worker command after WORKER_ID is positively known (as root):

```sh
test -n "${WORKER_ID:?verified practice worker id required}"
systemd-run --unit="unbug-practice-ttl-$WORKER_ID" --on-active=60m \
  --timer-property=AccuracySec=1s --property=User=user \
  /home/user/unbug-bench/bin/boat-call delete "$WORKER_ID" --yes --json
systemctl list-timers "unbug-practice-ttl-$WORKER_ID.timer" --no-pager
```

This command is a second backstop, not yet an acceptable hard 60-minute lifetime:
its delay must be reduced by elapsed time since provider creation, and a delayed
or uncertain create must also be covered. Therefore do NOT launch with only this
post-create timer. The parent must review a pre-armed deadline/ownership cleanup
that covers delayed creation, binds deletion evidence and survives holder restart.
This unresolved cleanup requirement is a launch blocker, not a claimed completed
step. After timer execution obtain operation.id from its public service output,
run the deletion-status and complete-inventory checks above, and stop admissions
until deletion is positively verified. Keep DIAGNOSIS_ENABLED false throughout.


## Preparation validation and rollback

The release builder's real restore-inventory qualification passed four tests.
`batch.verify` passed for all local release/host pins; all six staged release
files matched their hashes on the VM. `key_holder.policy_load` passed locally
with only root/release filesystem locations translated to this checkout.
Both HOLDER_ENABLED and DIAGNOSIS_ENABLED were asserted false. This validates
structure and pins, not source authentication or live readiness.

VM rollback does not require a source or policy restore: neither was changed.
The prior policy SHA256 remains
`fd0a861da1ef5f315ebf99345e410962437902004308539c9e02cd3d89beadf5`.
To restore the prior service state only after disposition of legacy ownership,
run as root `systemctl enable --now unbug-key-holder.service` then
`systemctl enable --now unbug-resume-launches.timer`. Do not do that for this preparation;
the founder instructed the holder to stay off until launch. The staged release
is inert and can remain on the existing disk. No worker deletion was attempted.


## Parent update: A at 1fff453; controller integration remains blocked

Read directly from 1fff453: `docs/designs/router-account2.md` and
`docs/reviews/router-account2-diff-1.md`. A's reviewed router admission change
passed its full suite; parent says merge into factory-simplify is pending.
This preparation branch has not merged A and must not run before parent confirms
that merge. Current staged pins therefore remain preparation-only and obsolete
for the eventual acceptance run.

Controller integration is not a small policy adjustment:

1. `account_handoff.choose` consumes `provider_wait`, but launch.sh's plan/apply
   branches (lines 568 and 597 at this release) run only on `provider_limit:*`.
2. `launch_accounts` treats initial_accounts as an override, suppressing the
   router-requested switch back to account 1 on checkpoint relaunch.
3. `factory_auto_resume` exits for UNBUG_BATCH_OPERATION or batch_release before
   either branch. Merely replacing the two stop checks cannot fix batch handoff.
   Removing those guards would change the reviewed explicit checkpoint-launch
   lifecycle and must not be smuggled into preparation.

Required follow-up: design and review the batch checkpoint/controller handoff,
keep router authority over fallback, preserve lease/receipt/money/TTL continuity,
and test controller-driven 2 -> 1 -> 2 transitions against real saved artifacts.
Include interrupted transport and resumed controller replay; no duplicate model
admission, no inference of rate exhaustion from occupancy or missing credentials.
Direct choose() unit tests alone do not prove controller wiring. Until this is
implemented and reviewed, A's correct router rule can safely wait but cannot
complete the required automatic round trip. This is a launch blocker.

Parent confirms both credential labels have different fingerprints, but both
identity probes returned HTTP 403. Do not store token values or fingerprints in
this plan. Account identity remains unknown. During the eventual approved run,
record a UTC window and the worker's invocation IDs, model and router-selected
public account label. Compare the founder's private Claude account usage before
and after that window and record only a public confirmation that usage appeared
on account 2 (and on account 1 only during genuine provider-rate fallback).
Builder activity can confound that comparison: isolate the observation window
or correlate identifiable usage events; otherwise mark identity inconclusive.
A denied profile endpoint is not permission to guess identity, and differing
tokens are not proof. Do not generate paid calls solely to probe identity during
preparation or synthesize rate evidence to force fallback. If natural rate-limit
fallback does not occur within the approved cap/TTL, report the live round trip
as unexercised rather than increasing spend. Any founder-confirmed label mapping
and usage evidence must be recorded without account email or credential values.


## Money dry-check blocker: USD 50 per Claude invocation

The pinned release and A commit 1fff453 both set CLAUDE_CALL_USD to 50.
`model_router.route_maximum('claude/claude-opus-5-5')` returns max_usd=50;
`model_runtime.invocation_maximum` passes that exact lease maximum to
`budget.reserve_invocation`, which refuses when total + pending + maximum
exceeds the authenticated job commitment. Therefore even a zero-spend practice
case with the approved USD 20 bound cannot reserve its first Claude call.
The parent-approved USD 25 all-in envelope does not authorize USD 50 model money.

This is a hard blocker for exercising account-2 usage, independent of identity,
credentials and controller handoff. A separately reviewed smaller enforceable
per-invocation profile (still within cumulative USD 20) would be needed under
this approval. Do not merely lower a reported maximum, bypass the money gate,
use a free different-family route to claim Claude acceptance, or increase the
approved cumulative bound. No model invocation or reservation was made by this
check. The exact maximum record is in the public preflight JSON.


## Final preparation regression

The required `uv run --with numpy --with scipy python -B tests/run.py` completed
with 155 scripts, zero failures, exit 0. Source/manifest commit 6ac450e; only
documentation changed during the run. Full command, log hash and reported skips
are committed in `stream-b-preparation-suite-20261031.json`. This does not clear
any launch blocker or substitute for fresh policy/design review.
