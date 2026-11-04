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

**Unchanged.** Mismatched statement or ciphertext, released entries, `historical=True`
calls, and historical-only entries nobody reserves still refuse to export. Screening
is untouched: a promoted candidate is compared against every other live entry.
Complete entries remain idempotent.

**Deletes.** Nothing; adds no new status, file or caller change.

**Tests.** `tests/factory/test_registry_promotion.py` (real registry/ciphertext copy,
threaded interleaving, negatives, stale revision). Fails on parent, passes on change.

**Murphy rows.** Row 7: implemented and tested here; not live-proven. The register is
not edited by this branch (root owns it).
