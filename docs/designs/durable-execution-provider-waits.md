# Durable execution: provider waits and credential problems

Status: proposed, revision 2 after design review 1. This records the founder's 2026-11-05 decision in the current
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

For genuine `PROVIDER_LIMIT` results, continue sleeping until the recorded retry
time regardless of the number of free or paid limit results. A provider limit is
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
for the affected workers and submit an authenticated, idempotent
`observe(pool, healthy=True, observation_id=<renewal receipt>)` to clear the router
block. WP8 or its credential-delivery integration owns this later rollout gate; it
must test the real blocked → verified delivery → healthy observation → admitted
route path without logging secrets. Until that gate is met, the wait can remain
blocked even after a file changes. This
can wait indefinitely until configuration is repaired; it is not scored as a
case result. Tests can shorten the wait through `Timing`.

In WP5a's later review, `worker_step.py` must inspect the fixed, trusted
`c.card["provider_wait"]["reason"]` when the stop is `provider_wait`. Translate
only the exact value `credential_expiring` to the credential infra reason; retain
ordinary quota/wait results as `PROVIDER_LIMIT`. Preserve valid reset metadata for
genuine waits and never record the account, route or raw provider text. Test the
real router → runner wait record → worker classification path. An older generic
`router:provider_wait` without retained reason metadata is indistinguishable and
stays generic; do not infer a credential fault. WP1's fake-seam tests exercise both
credential result shapes, and this real cross-package test is a WP5a/final gate.

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
