# Stream B activation handoff and proposed practice

2026-10-31. Planning only: no cloud calls, deployment, paid run, or secret
inspection performed. Holder and diagnosis activation gates remain off.

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

## Parent-approved live practice proposal

Proposed all-in incremental spend cap: USD 25, comprising a USD 20 cumulative
model-money bound and at most USD 5 for the disposable worker and incremental
storage/egress. Concurrency one, one case, no automatic replacement or diagnosis,
and a 60-minute worker TTL. This is a proposed authorization, not authorization
already granted. Verify provider pricing and conservative infrastructure exposure
before approval/launch; refuse if TTL plus cleanup/egress cannot fit USD 5.
The model bound is enforced by the existing money channel, including conservative
reservations and infra-waste calls. Do not claim the worker TTL alone is a hard
provider billing cap. The run may stop at its bound without sealing a case.

After the parent approves the concrete manifest, policy, and cost bound: pin the
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
