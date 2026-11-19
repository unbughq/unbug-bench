# Goldfish review: G11 side by side (diff 1)

- Branch: perf/g11-side-by-side, commit d5246a70 on main 1d1459d3; fixes in the next commit.
- Reviewer: fresh goldfish run by the coordinator. Verdict: **MERGE-AFTER-FIXES.** Findings below as relayed
  by the coordinator (the verbatim review is in the coordinator's session).

## Findings and disposition

1. **High:** `g11_slots` treated the card's `prepared_factory_slots` (G3's cleanup high-water mark) as live
   slots; after a round that shrank the slots, G11 would use retired slots and fail InvalidInfra on every retry.
   **Fixed:** counts slot 0 plus consecutive slots with `bench.factory_slot_ready` now (retirement removes that
   receipt). Test: high-water 4, 2 ready, uses slots 0 and 1 only.
2. **Medium:** each side-by-side scan reran the none/refuse-all baseline on its own slot, so each guard got its own
   table list (a possible verdict change; different evidence shape). **Fixed:** one guardless baseline on slot 0;
   scans get its list via new `fake-pass-check --traffic-tables`; the report keeps the serial shape. The test's
   stub bench returns a different list per slot and a flag that names it; d5246a70 fails it (`slot1-only` vs
   `slot0-only`).
3. **Keep slot choice out of G11's hashed sources.** **Fixed:** `evaluate_gate` sets `c.g11_side_by_side`;
   `g11` reads it as an attribute. Checked: against main only `g11` and `fake_pass_report` change in any gate's
   `source_inputs` (G11 only); the test asserts `g11_slots`/`g11_side_by_side` are absent.
4. **Design note and review record.** Added `docs/designs/g11-side-by-side.md` and this file. No Murphy row.
