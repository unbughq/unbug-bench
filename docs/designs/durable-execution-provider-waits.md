# Durable execution: provider waits and credential problems

Status: proposed. This records the founder's 2026-11-05 decision in the current
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
the fixed reason, release the worker for a long wait as with other sleeps, then
retry after a durable, bounded 900-second wait. Reset the public status to
`running` on wake. A repaired credential is picked up by the next attempt. This
can wait indefinitely until configuration is repaired; it is not scored as a
case result. Tests can shorten the wait through `Timing`.

The change deletes the generic 96-free-limit give-up rule and the paid-limit
give-up rule for genuine limits. It does not add another runner or change the
wire contract. The historical handoff remains a record of the superseded request.

## Tests and Murphy rows

- Policy tests show genuine free and paid provider limits continue to sleep beyond
  both former thresholds, and both credential-result forms retry without consuming
  infra allowance.
- WP4 classification tests cover missing/expired credentials as the fixed infra
  reason, with no provider text in records.
- A real-DBOS fake-worker test runs more than 96 free genuine limits then succeeds;
  another observes `waiting_for_credentials`, fixes the scripted problem and
  succeeds. Test durable sleep and worker release as appropriate.
- Existing bound, classification, report, replay and 20-kill tests continue to pass.

Targets Murphy rows 4 and 48. This design closes no row without the real artifacts
required by ENGINEERING.
