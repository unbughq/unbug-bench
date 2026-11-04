# November4 approved smoke debit — inactive accounting handoff

Existing prepared branch t3/pilot-admission-cleanup-settlement fast-forward merged
factory-simplify dd81ff8 and approval09df201. Original November3 decision bytes,
SHA4e5caa263a8bf323abb78791f03c3a064df3ab0ee0b9b5bbb0b950e97a350660
and schema/replay remain unchanged. New docs/factory approval bytes both hash to
a774c1e9d284ec99b135d9a195e33617a00c4a366ac4962ae0790e8beb46a929.

Existing boat-spend/lifecycle path adds only the explicit smoke selector and
--record-approved-smoke-debit (no arguments). The old flag/default still selects
November3. First apply requires exact reserved/bound row/expiry/envelope, actual
absent/null, raw spend SHA, unique created worker/IDs, monitor spend binding, exact
completed deletion identity and pinned raw request/completion hashes. It snapshots
the entire reserved row; no finished_at or exact usage is invented. Both budget
rows retain actual_spend_usd=null; status budget_debited remains distinct from
provider settlement. All original spend/evidence bytes remain untouched.

Mixed permanent budget debits sum0.072 against original minimum5, leaving4.928
before other liabilities. Larger caller caps cannot reset headroom. finish/settle/
record no-op replays validate the specific persisted approval hash and preserve
both rows without provider/evidence access or writes. Other unknown liabilities
remain blocking. Existing factory public root/trust inventory carries the new
approval; no new source-root ownership, launcher, ledger or migration system.

Focused tests: conservative debit7, inventory10, launch-manifest2 passed; existing
settlement14 also exercised. Initial new-application transport/digest is AUTHORED
using the supplied public scope and exact hashes; unavailable canonical raw bytes
are not reconstructed or represented as real SHA matches. Negative tests cover
ownership/envelope/deletion identity/raw-hash/decision mismatch; mixed CLI replay,
legacy validity, unknown actual and cumulative cap. New design/diff goldfish PASS
saved verbatim in docs/reviews/boat-smoke-budget-debit-{design,diff}-1.md.

Exactly one full final-head run follows this report's commit:
TEST_SLOTS=4 TEST_JOBS=4, UNBUG_LOCAL_DOCKER_SMOKE unset, no cache or lockf,
caffeinate -i, uv run --with numpy --with scipy python -B tests/run.py.
Authoritative pre/post SHA/tree/status, UTC and monotonic elapsed/gap, command and
result are /tmp/smoke-budget-debit-final-20261104.{json,log}. Final handback states
that result; focused/review evidence never substitutes for it.

## Root-only application prerequisites

Nothing was applied live. Current holder82c1617 cannot parse the new approval row.
Root must quiesce/isolate every old accounting reader/writer before applying a new
row with reviewed compatible inactive tooling; do not change running source or
invalidate old journal/release pins. Root owns coordinated integration/re-pin and
lifecycle handoff. New runtime must carry BOTH pinned public approvals, use the
existing control home/ledger and lock, and verify the independently retained raw
binding before first application (recorded preapplication ledger SHA40266f78d2104e4cd0f9f08bd8064991bb5aa0b93875ada776fe67a3ac824953).
Do not reset homes/caps or overwrite either original snapshot. Missing/mismatched
evidence refuses; accepted replay is read-only. The command grants no launch or
successor admission authority. No third worker/practice/retry/fleet is authorized.
No live provider/controlVM/model calls, secrets/decryption, deployment/activation,
ledger mutation/writeoff, main/push or Murphy closure occurred. README/EXAM and
old artifacts are preserved. Root alone applies the approved live accounting change.
