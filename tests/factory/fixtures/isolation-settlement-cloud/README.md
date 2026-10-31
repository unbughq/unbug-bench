# Saved cloud evidence (not cloud qualification)

Read-only copies from the 2026-10-29 restore, captured for this increment on
2026-10-31. provenance.json records absolute sources, SHA256 and transformations.
Only sandbox/operation identity is included; no human/account identity, secrets,
case bytes, commands or URLs. The readiness copy omits arbitrary observed and
provider_error fields, retaining only listed timing/lifecycle fields.

The spend file is preserved verbatim despite its misleading actual_spend_usd
name. USD 0.09361 is the account balance delta 4.26532 - 4.17171, not attributable
worker cost. Historical restore-14/bin/boat-spend balance() converts account credit
seconds by dividing by 100000. Thus fixture billing.json creditBalanceSeconds
417171 corresponds to 4.17171 USD under that historical converter; this does not
verify today's price or establish this worker's usage.

Deletion request and completion match sandbox bx_d6dzvjbc and operation
bdop_fdc58246dcdd44348ec9d206bd38abca. Completion is 2026-10-29T11:18:20.705Z.
The public readiness record precedes deletion. These bytes establish one observed
lifecycle, not an outage upper bound, current inventory absence, or final billing.
See docs/reports/isolation-settlement-cloud.md for missing qualification evidence.
