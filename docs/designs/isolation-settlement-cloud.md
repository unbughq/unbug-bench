# Item 8: cancellation settlement and cloud exposure qualification

## Problem

Local process cleanup, socket closure, and conservative money settlement have
separate tests. The current mid-response runtime regression replaces run_budgeted
with an exception, so it does not prove that a real process cancellation reaches
the receipt/settlement boundary. Its upstream is plain HTTP. Cloud cleanup has
an older real deletion receipt but the associated spend record labels an account
balance delta as actual spend. That is not attributable worker billing.

## Change

Extend tests/factory/test_model_call_maxima.py ProtocolTests with a real-process
variant of its existing mid-response runtime test. Keep the ordinary ModelRuntime,
router Store, gate, budget.run_budgeted, receipt producer and accountant. Replace
only the pinned CLI executable with a local Python protocol client, using a dummy
credential. It starts a heartbeat child in the CLI process group, sends
a request through the actual gate, reads the relayed prefix, signals readiness,
and waits. Set c.role_cancel only after both heartbeat and prefix are observed.
A wrapper around run_budgeted delegates to the real function and retains the gate
for observation; it must not raise cancellation itself or fake process startup.
Assert runtime interruption, stopped heartbeat and reaped CLI before settlement
is accepted, handler completion without upstream release, held unknown charge,
no active router lease, and byte-identical ledger on two reconciliation replays.
The real child sends synthetic protocol bytes, not a genuine Claude invocation.

Exercise upstream TLS with a test-only localhost certificate and a verifying
SSLContext trusting that certificate; do not disable verification. Patch only
the connection destination to localhost, retaining the actual HTTPSConnection.
Run HTTP/1.1 keep-alive and Connection: close plus HTTP/1.0 variants,
including HTTP/1.0 without Content-Length (close-delimited TLS). Keep the
existing plain HTTP regression. Use events and a generous 15-second cleanup
observation guard, less than the 60-second network timeout, with bounded release
and process cleanup in finally. Assert no late receipt or ledger rewrite after
upstream release. This qualifies the local current-Claude cancellation seam,
not live provider generation shutdown, isolated sudo UID cleanup, future profiles,
or other selected routes. No activation flag is changed.

## Cloud evidence and launch decision

Inspect saved real deletion and spend records first. Preserve public copies of
20261029T095210Z-99393-factory.json and its bx_d6dzvjbc deletion request/completion,
from the 20261029 restore directory cited by isolation-timeouts/README.md. Record
source hashes, identity, timestamps and exactly which bounds they establish.
An account delta cannot establish attributable cost or a cleanup-tail maximum;
a single deletion observation cannot establish an outage-time upper bound.
Read current provider pricing/usage/deletion documentation and compare the
ordinary launch path prerequisites. A live worker is authorized up to USD 1,
only through the normal single launch path with independent VM cleanup. If
current reviewed admission/bootstrap/cleanup prerequisites cannot provide that
path within USD 1, do not bypass them or enable unrelated lifecycle gates. Record
the exact blockers and leave cloud exposure unqualified. The task's second
prerequisite is investigated in this increment, but must not be called complete
without attributable billing plus deletion and complete inventory evidence.

## Deletions, tests and Murphy rows

Delete no production path; reuse the existing runtime regression helper instead
of introducing a parallel accounting harness. This is qualification evidence,
not a new provider abstraction. No Murphy row closes: row 9 and broader item-8
acceptance remain open. The narrow router cancellation row already closed by
plain-HTTP evidence can gain TLS/process evidence without broadening its claim.
Any newly observed defect gets a new-isolation-settlement-N row before fixing.

Run focused regressions then the full required command:
uv run --with numpy --with scipy python -B tests/run.py
Save unique full output and command/exit/hash metadata under docs/reports and
commit them. Fresh design and diff reviews use the engineering personas and
standards. A fresh reviewer must verify each blocker fix. Estimated scope is
one test/evidence increment; zero model spend and preferably zero infrastructure
spend. Remaining live/other-route qualification is explicitly handed back.


## Review-1 resolution (authoritative details)

B1 option (a): only a same-group heartbeat is created. No setsid child and no
SIGTERM immunity claim. Register the static non-isolated escaped-child finding
as new-isolation-settlement-1, open, without claiming a live reproduction or fix.
This increment changes no process cancellation policy.

M1: generate a per-test executable script with an absolute sys.executable shebang
and absolute temp paths embedded. It writes PID, prefix-ready and heartbeat files,
no stdout. The test watches readiness and heartbeat, then sets c.role_cancel.
The wrapper calls the real budget.run_budgeted; on its BudgetError it requires
cancelled, confirms the CLI PID is already reaped and the heartbeat has stopped,
and only then re-raises. This observation is before enforce exits and before the
runtime writes its receipt. Use ps state to distinguish a dead zombie heartbeat
from a live process; require absent or zombie plus stable heartbeat. Final test
cleanup kills the recorded process group if a failure leaves it alive. Reuse
self.stalled.release and handler_done; the old simulated client's received event
is replaced by the ready file only in real-process mode. An admission money_wait
means a harness/binding error to diagnose, not a reason to weaken money checks.

M2: save the actual HTTPSConnection before setUp's patch. For the TLS test wrap
the existing upstream server socket with an SSLContext(PROTOCOL_TLS_SERVER).
Generate its temporary localhost certificate using the existing model_router
test's openssl pattern, adding localhost SAN. Build a verifying default context
with that certificate as cafile. Stack the destination patch returning the real
HTTPSConnection('localhost', port, context=trust, **kwargs). Host identity is
localhost, not a claimed provider authentication test. No committed certificate.

M3/N4: parameterise the existing helper by cli mode; the server TLS wrapper
selects transport. Real-process runtime.call explicitly uses timeout=60, and its
client uses 60 seconds too; gate.remaining() supplies upstream timeout. The
upstream release event waits 60 seconds. Allow 20 seconds for readiness then a
15-second cancellation observation deadline, before the 60-second gate timeout.
The old simulated/plain HTTP case keeps its existing 30/5-second bounds.
After release require validated_requests=0, settled_usd=0, and unchanged cap,
receipt and ledger for every variant, including close-delimited TLS.

M4: cloud prerequisite 2 will NOT complete in this increment. The cloud work is
an archive and an explicit dependency handoff, not a live experiment with an
undefined workload. No identity is requested and no worker is created. The
normal path requires decrypted launch credentials on stdin (founder identity
for legacy launch, or the separately reviewed control-VM scoped restore path),
reviewed release/job configuration, eligible bootstrap/checkpoint, and independent
cleanup. Existing preparation reports leave these unresolved. This does not
prove that founder presence is universally necessary; the control-VM path is the
intended resolution under the no-Mac rule. Before spending the authorized USD 1,
B/E must supply that ready path and a bounded workload whose model plus machine
exposure fits the envelope. Do not enable HOLDER_ENABLED to circumvent it.

Attributable cost acceptance means provider per-sandbox usage matching this
sandbox and its lifetime, with final running=false and documented billing
settlement semantics, plus a matching completed deletion operation and complete
inventory absence. Current saved provider docs describe boat usage / sandbox
usage; availability of that documented API is not the missing real receipt.
No account-delta bracket is accepted here. A measured deletion delay is evidence
of this run only, not a provider worst-case outage bound. Hard exposure also needs
a documented billing-stop bound or independently enforced provider limit and
verified cleanup policy. The report lists missing evidence rather than inventing
that bound from a successful sample.

Archive sources (sandbox/operation identity only; never human/account identity):
/Users/bugsincode/Developer/unbug-bench-e15450-restore-14-20261029/results/spend/
20261029T095210Z-99393-factory.json,
20261029T095210Z-99393-factory-bx_d6dzvjbc.readiness.json, and
20261029T095210Z-99393-factory.deletions/bx_d6dzvjbc/
{deletion-request,deletion-completion-query,deletion-completion}.json.
Inspect readiness for private fields and retain only allowlisted public timing
fields if necessary, recording both source and retained hashes. The fixture
README's no-identity phrase means no human identity; sandbox IDs already exist
in created.json. Preserve original spend bytes but explain that 417171 credit
seconds times 0.00001 USD/second is 4.17171 USD under the historical rate, and that
the historical actual_spend_usd is only an account balance observation.

Delivery exam: local first-prerequisite seam passes only with real subprocess
cancellation plus all TLS/settlement assertions; no broader route/UID/live claim.
Second prerequisite fails evidence completeness and stays open with the exact
missing receipts and admission dependencies. Impact: prevent false item-8 and
DIAGNOSIS_ENABLED readiness claims. Expected implementation one working session
plus review/suite runtime. Amend new-router-item8-prereqs-1's Closed by cell to
add the TLS test and its scope, without closing any broader row. Commit unique
logs as docs/reports/isolation-settlement-cloud-suite-<UTC>-<nonce>.log plus JSON
metadata. Fresh review is required for this revision before implementation.


## Review-2 implementation details

Archive destination: tests/factory/fixtures/isolation-settlement-cloud/ with
README and provenance hashes. Blocker report: docs/reports/isolation-settlement-cloud.md.
Attach c.role_cancel=threading.Event() before submitting runtime.call, then set
that same event only after readiness. The local client waits even after socket
errors so cancellation remains deterministic. Parameterize the upstream release
wait as 60 seconds for real-process and 30 for the old simulated client. Ordering
assertions concern gate close and invocation reservation settlement, not the
budget ledger terminal_stop written before process cleanup. Historical credit
conversion source: restore-14/bin/boat-spend balance(), divides credit seconds
by 100000; this is a historical converter, not current-price verification.
Main risk is timing sensitivity of real processes; event/file readiness and
bounded cleanup in finally keep failures diagnosable without leaking children.


TLS harness implementation clarification: CPython's HTTPSConnection uses
super(HTTPSConnection, self), so replacing its module-global name with a mock
breaks the real class. Restore that global to the saved class inside the TLS test
and redirect only model_call_gate.http's local namespace to a destination factory.
The factory constructs the unchanged real HTTPSConnection with the trusting
context. Preserve handler/client exception observations to diagnose readiness
failures. Synchronize the old simulated client's cancellation timestamp with an
event before reading it; receiving a prefix alone does not order that write.
