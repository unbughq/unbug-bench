# Stream E: first Item 8 prerequisite increment

Branch: t3/isolation-item8-prereqs, cut from factory-simplify f829df7.
Implementation: a42c520. No push, merge, provider operation or paid model call.
The required Claude goldfish reviews are orchestration reviews, not factory calls.

Six factory queries now put their existing 25/30/120-second limits into
boat-call's owner deadline rather than killing it at a competing outer timeout.
They preserve inherited earlier deadlines and existing nonzero refusal behavior.
Diagnosis remains disabled. This is local hardening, not live qualification.

## Local evidence

`tests/factory/test_isolation_outer_callers.py` passed five tests in 48.346 s.
`tests/factory/test_coordinator_inventory.py` passed its inventory and admission
checks. Tests replay checked-in isolation-timeouts Boat version/list/created and
launch artifacts through real boat-call/processes.py executables. The local
transport and heartbeat child are explicitly injected faults, not remote workers.
The transport is named boat, so pinned version discovery is actually exercised.
No credentials, provider API or model API are used.

Initial targeted observations with a two-second inherited command deadline and
three-second slow ps probe: key_holder 5.135 s, batch_holder 5.150 s,
coordinator admission 5.131 s, coordinator inventory 5.134 s, batch_status 5.151 s,
TTL retirement 5.152 s from caller start through return. Each returns 124 only
after its real separate-session heartbeat child stops. Single SIGTERM owner
cancellation returned 143 after 3.323 s, including the assertion observation
interval. Timings are observations, not upper bounds or remote billing evidence.
The full-suite log contains another set of measured local timings.

The escaped-pipe test deliberately lets a child detach before the ancestry
snapshot. It confirms the Boat owner has exited but its caller is still blocked
on pipe EOF; terminating the escaped child releases the caller. All injected
processes are cleaned up. This documents OPEN new-isolation-outer-wall-2 rather
than claiming cancellation qualification. A local exit or quiet heartbeat is not
authoritative evidence that provider-side work stopped or usage settled.

## Scope and remaining work

new-isolation-outer-wall-1 closes only for the six factory call sites, backed by
the real-artifact/process regression in the fix commit and subject to fresh diff
review. new-isolation-outer-wall-2 remains open and blocks Item 8 activation.
The single-threaded holder can still wedge on an escaped capture-pipe holder;
transfer.py and statement_round.command share this risk. Temporary-file capture
or equivalent isolation needs a separate reviewed increment. Outer timers in
public-qualification/finish.py and dashboard callers remain outside this change.

A/D must qualify invocation cancellation, unknown-usage reservation and final
settlement. B/E must qualify cleanup from creation through authoritative provider
deletion, delayed creation, full inventory absence, current prices and conservative
infrastructure exposure. No maximum duration or dollar amount for a stopped remote
worker is established here. Existing 60-second holder client uncertainty and TTL
pre-call checks remain as documented in the design. No live launch is authorized.

## Reviews and full suite

Design review 1 could not run because the initial file-write command failed;
its record is retained. Review 2's blocker was accepted by explicitly tracking
the escaped-pipe risk as an open activation hold. Fresh review 3 passed.
Verbatim records: docs/reviews/isolation-item8-prereqs-design-{1,2,3}.md.
Full suite: `uv run --with numpy --with scipy python -B tests/run.py` completed
with exit 0 in 1186.919 seconds. Full unfiltered log:
`docs/reports/isolation-item8-prereqs-suite-20261031T131629Z-3cf32eef.log`.
Fresh diff review follows this committed suite record.
