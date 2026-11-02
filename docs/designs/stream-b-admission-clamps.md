# Cumulative admission and replacement clamps

## Objective and scope
A practice replacement may spend only its own approved allocation. A retired
release must not create fresh headroom. This increment implements remaining B
item (4) on e2c2ea8, before any live qualification. It uses the existing manifest,
money state, holder admission and whole-batch carry-over; no second ledger,
settlement system or launcher. One offline implementation/review cycle.

The existing aggregate already adds carried_debit_usd to every job's greater of
held authority and known lifetime floor. It deliberately retains unused authority
and unknown reservations. Do not replace this with a sum of settled receipts.
The gaps are root-template copying for a fresh child, unrestricted practice
replacement generations, and operation replay returning before the aggregate
check. Ordinary production replacement chains remain unchanged.

## Manifest contract
Add optional `practice_admission` to the authenticated batch manifest, not the
holder policy. This is a new reviewed schema, not a field operators can invent.
Its exact keys are `schema: 1` and `jobs`. Each jobs entry has exactly
`baseline_usd` (S) and `incremental_usd` (E), encoded with money.amount's existing
nine-decimal grammar. E is positive; S is nonnegative. Keys are existing root
names or their single `-r1` child. Every root template has an entry; a child entry
requires replacement enabled. No r2 entry is legal. This explicit allowlist
bounds practice admission, without changing D's queue/production semantics.
The sum of all S+E entries must be at most money_limit_usd. Individual authority
is min(existing requested_total_usd, S+E). Fresh replacements have S=0, so a
root's historical $20 commitment can never become the child's authority.

S is not trusted merely because it is written down. For a new empty job it must
be zero. For initial checkpoint admission (first introduction of this optional
schema at a carry-over boundary), S must exactly equal the selected predecessor's
authenticated previous.total_usd, with no estimated reservations; the checkpoint
ACK/snapshot and release checks remain mandatory. Its carried commitment must
already be <= S+E. The existing carry-over retains that commitment exactly; this
increment neither raises nor resets an old grant. If existing authority cannot
fit, the candidate is refused and the practice manifest must use a genuinely
eligible empty input or undergo a separately reviewed change. Legacy inputs stay
retire-only. A carried, never-launched child has S=0.

At every subsequent carry-over boundary the entire practice_admission object
must equal the predecessor's. Removing it, changing S/E, or adding another
scenario/allocation refuses. Every successor must retain all original root templates, even when only one
scenario is selected for import; the history rule below prevents reuse. Beta is
a separate chain from alpha, initially listing scenarios 5, 6 and 7 with their
$50 total incremental allocation plus baselines. Beta-plumbing and beta-science
retain scenario 5/7 templates while importing only scenario 6. Do not require every listed root to be selected for import.
The batch cap cannot rise (existing transfer check). Prior spending, unknown
reserves and omitted jobs remain in carried_debit_usd. At a schema-introduction
boundary, jobs already present in historical money snapshots but not selected
cannot be presented as fresh work. At later boundaries the same rule applies:
_admit refuses a source=None name seen in any predecessor snapshot unless that
name is an imported never-launched child. Traverse the existing import snapshot
chain, without new journal fields. This prevents retired cases acquiring E again.

## Implementation
In batch_money.check_manifest validate the optional schema without resolving jobs
recursively. Add a small pure allocation-cap helper used by channel and
 authorize_locked: absent schema retains current behavior; present schema refuses
unlisted names, and clamps new authority to the named S+E. channel rejects any
persisted authority exceeding that cap, including POST/config use. Do not change
resolve_job's template or lineage grammar: unadmitted r2 can remain queued, and
ordinary chains still resolve. The cap changes authority, not authenticated
checkpoint accounting or D's exhaustion/extension rules.

In batch_holder._admit, before the replay return, enforce state incidents and
money.aggregate(state) <= money_limit_usd. Keep concurrency checks after replay.
Apply practice admission source/baseline/history checks before money advancement
or authorization; both reserve and the read-only qualifier call this same path.
Use fixed MoneyWait('money_wait') refusals. In an already-prepared batch,
refusal writes no operation/config/money (the lock directory may be created).
reserve calls transfer.prepare first: a first attempt can commit the transfer
before admission refuses; it cannot grant additional money. Replay is idempotent but
cannot report admission after cumulative overrun. Dispatch retains its _post
aggregate check and channel validation.

In batch_transfer, check the practice schema continuity and initial authenticated
baseline against the frozen source snapshot before export/import writes. Recheck
in read_import so altered receipts cannot bypass the contract. Use the existing
predecessor and snapshot authentication, not a parallel provenance record.
In batch_money.authorize (the legacy schema1 entry), refuse practice manifests:
practice is supported only through the existing schema2 holder admission path.
This guard excludes practice from the legacy path; it does not delete that
production API. No existing API is deleted. The repeated replay bypass is removed.

## Tests and exams
Use tests/factory/test_batch_holder.py and test_batch_transfer.py's retained
scorecard, continuation ledger and ciphertext. Their batch/ACK/retirement bindings
are authored offline, not live authentication claims. Add tests in
 tests/factory/test_batch_admission_clamps.py reusing those helpers, plus focussed
manifest/cap tests in that same file. Delete imported TestCase helper names from
its module namespace to avoid duplicate discovery. No workers, model calls or network.

Midterm: root old requested $20, authenticated S and E, fresh child S=0 and E=7.50
gets at most $7.50, never $20 or root S+E. Refuse child nonzero S, unlisted child,
r2 after child exhaustion, malformed map, bool/schema/dollar values, and an
oversized persisted channel. Test ordinary no-schema chain remains unchanged.
Prove replay does not duplicate authority and returns identical operation.

Final: at exact aggregate cap admit, one nanodollar above refuse; retained card
known-floor overrun refuses replay as well as new work. Unknown liabilities keep
holds. Carry a root twice while omitting a retired job, retaining its debit.
A separate queued-child arithmetic test uses authored money state: there is no
production path to reserve a child without also creating an operation, so the
existing never-launched-child transfer path cannot yet be exercised normally.
This is an open carry-over-stream gap, not carry-continuity or live proof. Refuse increased
E, removed schema, baseline mismatch, nonzero fresh child S, re-admission of an
omitted historical name, and cumulative overflow caused solely by carried debit.
Check refusal leaves money/operations/config bytes unchanged and qualifier
agrees without writing. Existing carry-over and holder tests must still pass.
Run the exact full suite to a unique committed log/JSON with source/tree/digests,
then a fresh independent diff review. No Murphy row closes: offline authored
lifecycle bindings do not prove real launch/deletion/account attribution.

## Preflight and handback
Do not rewrite old frozen release pins or remove live proof requirements. Record
current preflight blockers in docs/reports/stream-b-admission-clamps.md, including
whether the historical preparation check now refuses stale pins. Distinguish this
offline clamp from live admission qualification. Items (6) account-2 attribution
and (7) launch/deletion evidence remain live-practice exams. Cleanup/creation cost,
A's route/paid-spend caps and feasibility, cancellation/settlement, exact live
policy/release/input pins, and outcome/carry-over live qualification remain
separate evidence. A's forthcoming shared paid cap is not implemented here.
Both activation gates stay off; no deployment or secret handling. No rows closed.

## Risks and review clarifications
An old $20 commitment with E=$7.50 requires S >= $12.50 to fit. Thus most old
$20 inputs refuse; this increment delivers S+E or refusal, not automatic lowering.
A later lowering proposal must review prepare/read_import/imported_row and must
not release historical headroom. Input selection remains a practice prerequisite.
The permanent r2 refusal leaves that item queued; no queue drain is introduced.
When carry_from is absent, nonzero S fails manifest validation itself.
Older code ignores this optional field: every practice manifest must be built
with the reviewed clamp implementation, never an older release. Exact release
pins remain a preflight blocker. The manifest stays schema1 for compatibility.
Cost: offline tests and subscription review only, no case calls or workers.
Timeline: design/review, implementation/full suite, fresh diff review in this
increment; live input/account/deletion qualification stays in the practice run.
