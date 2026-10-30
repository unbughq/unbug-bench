# Invocation-local wall validation

Implementation: e95d0253e4385dc46b458f8616b77c9f13f3b6f2 on
t3/router-maxima-rounding. Production changes only the gate's exact-port
lifecycle and the runtime's user argument; run.pilot_wall is unchanged.

Focused unit/artifact checks: eight wall tests, 21 maxima tests and 36 router tests pass.
The wall tests exercise pilot, pilot-strong and pilot-easy through the actual
runtime/gate with the process and firewall boundaries faked. They cover exact
argv, concurrent port ownership, cancellation-independent deletion, cleanup
before release, missing identity, failed deletion, and insertion applied before
TimeoutExpired (even successful deletion then retains the socket). EADDRINUSE
proves retained ownership. An initial test attempted to patch a frozen runtime
instance; patching the class fixes the test setup, with no production change.

## Actual Linux proof

The explicitly authorized worker **bx_rh5p34r3** ran the committed
tests/factory/live/gate_wall_probe.py against real pilot_wall, real iptables and
ip6tables, and a synthetic local upstream. No provider/model credentials or real
model requests were used. Source hashes, numeric UIDs, rule snapshots, all 21
network checks, and two gate receipts are in the gzip fixture linked by
router-gate-wall-live-evidence.json. The controller source is preserved beside
this record; no additional worker was created.

The probe confirms gate denial before insertion; gate reachability during its
exact UID/port exception; denial of another listening local port, another UID's
gate access, and IPv6 loopback; unchanged bench/service access; and denial at a
new listener on the former gate port after both normal and exceptional cleanup.
It verifies exact baseline rules after cleanup and removes both test chains and
Unix users without errors. The offline fixture test validates these captured
outcomes and that each active rule set differs only by the exact exception.

Boat's verified rate was $0.036/default-hour and next start charge $0. The
planned 1200-second TTL envelope was $0.012 (reserved maximum $0.082 allowing
the published maximum start fee), below the user's $0.10 limit. The attributed
pre-deletion usage was **14 seconds / $0.00014**. The post-deletion usage query,
including a query bounded by the deletion timestamp, returns `not_found`, 404;
there is no final provider cost record. Do not relabel the observed cost as final.

From the provider's per-worker start timestamp 2026-10-30T06:18:14.514Z through
confirmed deletion at 06:18:32.310Z is 18 seconds rounded up, bounding compute
at **$0.00018** at the verified rate. This is an explicit conservative bound,
not a wallet delta. The deletion operation
bdop_0fc7ef2ae61c4bceb9c22b057b8581dc has matching target/kind, completed status
and stage, and the worker is absent from inventory. The controller finished
in 20.630 wall seconds. The fixture records the observed bill and cost bound
separately.

Murphy new-router-gate-wall-1 is closed with the unit tests and real evidence,
subject to fresh diff review. Full-suite validation remains pending for the
final reviewed commit and will be recorded with its terminal result.

## Subsequent terminal suite record

The frozen reviewed SHA d15af56fbdcc07c825943425969fca325dbe3cb9 passed
145 scripts, 0 failed, exit 0, finishing 2026-10-30T06:38:33.389159Z.
See router-gate-wall-full-d15af56.json and its SHA-256-linked gzip log.
The original review-time pending statement remains historical. No production
source changed during the suite. The fresh diff review accepts the Murphy closure.
