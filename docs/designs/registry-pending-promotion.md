# Registry: pending candidate promotion (Murphy row 7)

**Problem.** `statement_round.prepare` imports every collected statement that is not
this wave's candidate as historical (`complete=false`, status `completed`). A candidate
of another handoff that is still pending is therefore imported as history first. When
its own handoff runs, `Registry.reserve` finds the existing entry and returns it
unchanged (digest known) or raises "different content" (digest unknown), so `export`
refuses it as historical-only. Reproduced on a copy of the retained public registry
`sealed/statement-registry` (37 historical-only entries): `reserve` and
`replace_rejected` give `complete=False`; `export` raises "historical-only".

**Change (`factory/registry.py`, ~12 lines).** In `reserve`, under the existing lock, a
non-historical call on a non-released, `complete=false` entry is a promotion when the
statement digest equals the stored one, or the stored digest is None and the
ciphertext digest equals the stored one. Promotion keeps the stored ciphertext, then
takes the normal new-reservation path: `expected_revision` check, predecessors
recomputed from all non-released entries, fresh reservation token, `complete=true`,
status `screening`. `replace_rejected` only treats a *complete* entry as a conflicting
previous; historical-only mismatches still raise in `reserve`.

**Why not "import only genuinely historical" (the other half of row 7's fix).** The
registry exists so later workers screen against earlier pending candidates
(`registry.py` docstring), and `same_worker_handoff` requires every collected
statement in the attestation. Pending candidates must stay visible, so the import side
stays and promotion is the fix. Row 7's first sentence is superseded.

**Mutual predecessors (accepted).** A pending candidate B imported as history is already
in the predecessor set of every later reservation (A). On promotion B's predecessors are
recomputed from all live entries, so A and B screen against each other. For a
near-duplicate pair both may be rejected and reselect. Over-rejection is the safe
direction for duplicate screening, and before this change B could not be admitted at
all. The tests assert both directions explicitly.

**Promotion guards.** Only entries with status `completed` and `complete=false`
(what `import_historical` produces). A missing stored ciphertext object refuses.

**Known remaining sub-case (not fixed): new-registry-pending-promotion-1.** A wave that
imports a pending candidate as history under a statement digest the registry has since
replaced (candidate reselected before its handoff) raises "different content" and fails
that wave. Same mechanism class, different cause; it needs its own design.

**Unchanged.** Mismatched statement or ciphertext, released entries, `historical=True`
calls, and historical-only entries nobody reserves still refuse to export. Screening
is untouched: a promoted candidate is compared against every other live entry.
Complete entries remain idempotent.

**Deletes.** Nothing; adds no new status, file or caller change.

**Tests.** `tests/factory/test_registry_promotion.py` (real registry/ciphertext copy,
threaded interleaving, `statement_round.prepare` two-wave flow, kept ciphertext, missing
object, negatives, stale revision). Fails on parent, passes on change.

**Murphy rows.** Row 7: implemented, and regression-tested against the retained real
registry and ciphertext through `statement_round.prepare`; not deployed or live-proven.
The register is not edited by this branch (root owns it); root may set row 7 `closed`
with `tests/factory/test_registry_promotion.py` as `Closed by` at merge.
