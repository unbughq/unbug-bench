# Test the ruler

`python3 tests/live/judge/judge_vs_promise.py [states=5000] [seed=20261014]`

Compares the judge (`cases/medusa-oversell/checker/check.sql`, run unchanged as
`bench_checker`) with `reference()`, a plain reading of the promise in CONTESTANT.md,
on hand-made edge states and thousands of seeded random shop states. It starts its own
throwaway `postgres:17.11-bookworm` container (unique name, no published port), loads
only the 9 tables check.sql reads (columns taken from the Medusa 2.19.0 migrations), and
removes the container on exit. It never touches the bench's Docker stack. Standard
library only; needs Docker. 5,000 states take 1 to 3 minutes.

Exit 0: no disagreement. Exit 1: disagreements, each class shrunk to a minimal example, or
check.sql failing on a custom line item. Exit 2: harness error.

## Reference rule

Per inventory item: units owed on live orders must not exceed the stock, unless the item
allows backorders. Live = not soft-deleted, not canceled, not a draft (`is_draft_order`
or status `draft`). Owed = per line on the order's current version, max(0, ordered −
fulfilled) × the kit's `required_quantity`. Stock = `stocked_quantity` summed over live
levels at all locations. Reservations are ignored.

## Compared

`kits.<k>.sold` and `kits.<k>.stocked` for x, s, z, bo, d, e, r; `concurrent_oversold`,
`sequential_oversold`, `draft_oversold`, `edit_oversold`, `resold_oversold`; `oversold` over
every product (Y included); `oversold_other_items`; the `overreserved` warning (reserved above
stock on a non-backorder item).

## Judge fixes applied 2026-10-14 (were the known differences)

1. `oversold` and the per-path fields count units owed only. More reserved than stocked is
   the separate `overreserved` warning, not a failure (founder decision 2026-10-14).
2. Owed units per line are clamped at 0 (`GREATEST(quantity − fulfilled_quantity, 0)`).
3. Custom order lines with no product (`variant_id` NULL) are skipped in the `orders` list;
   before, `json_object_agg` crashed on the null key.
4. Every inventory item is judged, not only the 7 kits: items outside the kits use the
   catalog's own `required_quantity` and backorder flags (`oversold_other_items`).

Result 2026-10-14: 5,000 states (seed 20261014) and 20 edges, 0 disagreements
(`results/judge-vs-promise-2026-10-14-fixed.log`). Mutation check: reverting fixes 2 and 4
gives 136 disagreements on 1,500 states.

## Not checked

- Traffic- and API-dependent fields: `pass`, `normal_ok`, `trigger_ok`, `legit_concurrent_ok`,
  `backorder_ok`, `draft_ok`, `edit_ok`, `resold_ok`, the `bench.py` cross-check and
  `api_oversold`.
- `valid` (seed tampering, `checker_ok`) and `bookkeeping_ok`. Neither is part of the
  promise.
- Kit tampering. The catalog rows stay as seeded; check.sql uses frozen kit factors and
  backorder flags by design.
- Tampering with the catalog of items outside the 7 kits: they are judged through their
  own variant links and backorder flags, which are not frozen.
- Real Medusa behaviour. States are synthetic rows shaped like Medusa's, not produced by
  Medusa workflows, and the schema is a minimal subset without the other columns or
  constraints.
