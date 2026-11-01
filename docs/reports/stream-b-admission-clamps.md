# Stream B cumulative admission and replacement clamps

Implemented against e2c2ea8. The authenticated manifest can now name practice
allocations by job. Fresh child authority is clamped to its own S+E; root history
is never copied as child spending permission. Only explicitly listed root/r1
jobs can be admitted. Production manifests without the optional schema retain
ordinary replacement-chain behavior. An r2 may remain queued but cannot launch.

The existing money aggregate retains all holds, known lifetime floors and carried
debit. Admission now checks it before returning an operation replay. Transfers
preserve the entire allocation map, and admission rejects a previously admitted
but omitted job even when its template would produce a fresh case name. No new
ledger or settlement mechanism was introduced. Both activation gates remain off.

Design review: docs/reviews/stream-b-admission-clamps-design-1.md (Claude, PASS,
zero blockers). All three majors were clarified before implementation.
Targeted validation: admission clamps 8 tests, holder 59, carry-over 14, input
qualifier 11, all passed. The first full-suite record is below; fresh diff review
found B1 (two nondiscriminating tests) and M1 (production partial-grant regression).
Both are accepted in docs/reviews/stream-b-admission-clamps-diff-1.md. The fix
keeps the baseline-mismatch cap above held, gives the history test spare aggregate
headroom, and limits partial grants to practice manifests. A new regression
requires production oversized requests to refuse without mutation. A full-suite
rerun and fresh independent review will validate these changes.
No Murphy rows closed: retained artifacts use authored batch and lifecycle
bindings. No workers, model calls, live cloud, pushes or secret handling.

## Remaining preflight blockers
The saved preparation remains blocked. The new offline invocation is recorded in
stream-b-admission-clamps-preflight.json: exit 1, PREPARATION INVALID / PINS STALE:
host differs from batch commit. Its historical release was built at bc33fe52.
We did not rewrite pins, policy or launch_ready. The frozen blocker list still
reports these seven groups (some code has since landed; live proof is distinct):

- B cleanup, lifecycle cost proof, legacy ownership, inventory/controller handoff.
  Saved legacy cases are retired; legacy provider debt and live cleanup proof
  are not converted into admission proof by retirement.
- B2 authenticated generation, owner/ACK, role binding and baseline S.
- A merged profile release, honest route maxima, <=$5 item8 feasibility and
  <=$0.01 probe. A's forthcoming shared paid-spend cap is separate work.
- E cancellation/unknown settlement, escaped capture pipes and measured
  creation-through-deletion timing.
- D/B outcome joins, replacement clamp and cumulative carry-over qualification.
  Lane 1 outcome code and this offline clamp are present; live qualification is
  not. The queued never-launched child's money-only state has no production
  creation path yet; that gap belongs to the carry-over stream. The queued-child
  test here is explicitly authored arithmetic evidence, not closure of that gap.
- Live account-2 attribution and natural 2-to-1-to-2 acceptance (item 6).
- Final live policy, exact fault/cleanup interfaces and immutable release/input
  pins require fresh review. Launch/deletion evidence (item 7) runs live.

Two input constraints are material. Beta starts a separate chain with all three
scenario allocations and keeps all root templates through every release. An old
$20 authority fits E=$7.50 only when authenticated S >= $12.50: otherwise it
refuses. We do not lower that old grant or free headroom. This is S+E or refusal,
not automatic conversion of historical $20 checkpoints. Input selection must
respect it. The preflight's old expected-conversion wording is not implemented
as an unconditional migration. A later proposal to lower commitments must review
prepare/read_import/imported_row separately and retain historical liabilities.

## Full-suite validation
The exact required suite passed at source 72cd3d9405a3ee17c7bfa958c6396b5795424141
(tree 76918921668c074a371f0809c7eaac3833330c78): 169 scripts, 0 failed, exit 0.
The unique record is stream-b-admission-clamps-suite-20261101T193952Z-7bd3784d.json
and its matching .log.gz, including UTC times and both log hashes. Source and
tests were unchanged during the run. Fresh diff review is still required.
