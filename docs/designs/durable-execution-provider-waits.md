# Durable execution: provider waits and credential problems

Status: proposed, revision 5 after design reviews 1–4. This records the founder's 2026-11-05 decision in the current
thread: genuine provider rate limits keep waiting, and missing or expired
credentials are handled as a separate configuration problem. The handoff's
generic 96-free-limit cutoff conflicts with ENGINEERING section 4 and is superseded
by this decision.

## Problem and change

WP1 currently gives up on every 96th zero-cost `PROVIDER_LIMIT`, including genuine
quota waits. ADMIT then stops admission, and other steps can be diagnosed as case
failures. Separately, WP4 classifies both a missing local secret and an expired
login as `router:credential_expiring`, also a `PROVIDER_LIMIT`; waiting silently
does not tell an operator that configuration needs attention.

For genuine `PROVIDER_LIMIT` results, continue waiting regardless of the number
of free or paid limit results. Use the valid recorded retry time, or a bounded
fallback to recheck when no recorded time is valid. A provider limit is
not a case outcome. The ledger still bounds every paid attempt; an exhausted batch
bound follows its ordinary wait path. The frozen `BatchSpec` field
`max_spent_limits_per_step` remains present for compatibility but does not stop a
genuine provider limit under this decision. Do not edit `contract.py`.

WP4 classifies `credential_expiring` and `codex_login_expired` as `INFRA_ERROR`
with the existing fixed, public-safe `router:credential_expiring` reason. WP1 also
recognizes that reason on an older `PROVIDER_LIMIT` result. Either form is a
configuration wait: do not count it against infra retries, diagnose it, retire
the case, or stop admission. Publish a `waiting_for_credentials` case status and
the fixed reason, release the worker on every credential wait, then retry after a
durable, bounded 900-second wait. Reset the public status to `running` on wake.
Release the worker on every genuine provider wait too, including repeated short
waits; this avoids indefinitely holding scarce capacity while another case waits.
The tradeoff is that a short reset can require a fresh worker and snapshot restore.
Paid provider-limit usage remains batch waste and counts against the batch bound.

The router also records credential blocks independently of the credential file.
Replacing a file alone is not sufficient. Before claiming a repair can resume a
real case, the credential-delivery path must distribute and verify the replacement
for the affected workers and submit an authenticated, idempotent, **scoped**
credential-health update tied to that verified credential generation. The current
`observe(pool, healthy=True)` clears every health entry for the pool and descendants;
it is not sufficient by itself because it can erase independent or newer quota,
credit, rate or outage observations. WP8 or its credential-delivery integration
must design and review conditional clearing that preserves those blocks, then test
stale/duplicate renewal receipts and a concurrent unrelated observation. It must
also prove newly provisioned workers receive the verified replacement credential
after a wait releases the old worker. Test the real blocked → verified delivery →
scoped health update → admitted route path without logging secrets. Until that gate is met, the wait can remain
blocked even after a file changes. This
can wait indefinitely until configuration is repaired; it is not scored as a
case result. Tests can shorten the wait through `Timing`.

In WP5a's later review, enable `UNBUG_PROVIDER_WAIT=1` in the isolated engine step
process and provide a stable job identity derived from the case ID together with
the batch ID and **attempt** deadline. Capture the current `ProviderWait` exception
and any joined concurrent waits before `run_step` converts them to a string; do not
read a stale `provider_wait` field from a restored card. Pass only allowlisted fixed
reason and valid reset metadata to `worker_step.py`: translate the current exact
`credential_expiring` reason to the credential infra result, and keep ordinary
quota/wait results as `PROVIDER_LIMIT`. Clear the per-step wait collection before
the step and join its concurrent calls. Select only the terminal wait for each
currently stopped logical call; earlier serial waits, including `previous_waits`,
are usage evidence, not current results. If any current terminal wait has the
exact credential reason, report the credential infra result. Otherwise, for each
current quota wait, accept its reset only if it is a finite epoch timestamp,
strictly after the classifier's clock and no more than `MAX_RESET_AHEAD_S` (eight
days) ahead. Select the latest accepted reset; if none qualifies, use the existing
900-second fallback, then recheck. A surfaced `cancelled` with current terminal
provider waits uses that same selection; `cancelled` without such waits remains
the normal cancellation outcome. Preserve interrupted-usage evidence and do not
classify stale wait metadata from earlier attempts. Never record the account, route
or raw provider text in DBOS. Test the real router → current runner exception →
worker path for credential-only, quota-only, mixed credential/quota, peer
cancellation, an earlier serial credential wait, an earlier longer serial reset,
a stale restored card, mixed valid and invalid resets, past and out-of-range
resets, and no valid reset. An older generic
`router:provider_wait` without retained reason metadata is indistinguishable and
stays generic; do not infer a credential fault. WP1's fake-seam tests exercise both
credential result shapes, and this real cross-package test is a WP5a/final gate.
The router's deadline must be no later than the supervisor's **actual** monotonic
deadline, which starts before restore. Pass that cutoff into the child and derive
the router's wall-clock limit from the remaining time; do not start a fresh full
attempt timeout after setup or restore. Test a deliberately slow restore and prove
the router cannot continue beyond the supervisor's deadline. The original batch
deadline still does not stop an already-running case.

Earlier unreviewed WP1 draft journals are unsupported by this unpublished package:
all wave-1 runs use new disposable test databases, as reviewed in
`durable-execution-wp1-bootstrap-scope-design-1.md`. No existing journal is claimed
to replay under this pre-release change. After the first supported production
generation, compatible changes must use `DBOS.patch` for the case and independently
recovered child workflows. Test a same-generation kill during the new credential
wait; WP8 must enforce its separate fresh-generation database gate before real use.

The change deletes the generic 96-free-limit give-up rule and the paid-limit
give-up rule for genuine limits. It does not add another runner or change the
wire contract. The historical handoff remains a record of the superseded request.

## Tests and Murphy rows

- Policy tests show genuine free and paid provider limits continue to sleep beyond
  both former thresholds, and both credential-result forms retry without consuming
  infra allowance.
- WP4 classification tests cover missing/expired credentials as the fixed infra
  reason, with no provider text in records.
- Report tests cover the new public status, its fixed reason and `running` after
  wake; cleanup tests prove worker release even with the default threshold.
- A real-DBOS fake-worker test runs more than 96 free genuine limits then succeeds;
  another observes `waiting_for_credentials`, fixes the scripted problem and
  succeeds after a kill and restart. Test repeated short genuine-provider waits
  and the worker release for each wait.
- Before the WP5a/final integration gate, exercise the real router-to-worker wait
  metadata path and the credential-delivery/router-health repair sequence above.
- Existing bound, classification, report, replay and 20-kill tests continue to pass.

Targets Murphy rows 4 and 48. This design closes no row without the real artifacts
required by ENGINEERING.
