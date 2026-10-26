// Sequential express orders on Y (stock 8), before the main traffic, as one group on a new path:
// A 4 units (placed), B 2 single + 2 x 2-pack = 6 units (each line fits the 4 left, must be
// refused), C 2 x 2-pack = 4 units, exactly the rest (placed). Placed orders are then canceled
// so the main traffic starts from full stock; the judge scores the group from the API record.
export async function before(ctx) {
  const order = async (lines, email, instance) => {
    const body = {region_id: ctx.ids.region_id, email, shipping_address: ctx.address, billing_address: ctx.address, items: ctx.lineItems(lines)};
    return {email, requested: Object.fromEntries(body.items.map(i => [i.variant_id, i.quantity])), response: await ctx.request("/store/express-orders", body, instance)};
  };
  await ctx.group("s2-express", "y", "express-checkout", [
    () => order({"Y-SINGLE": 4}, "express-a@bench.test", 0),
    () => order({"Y-SINGLE": 2, "Y-2PACK": 2}, "express-b@bench.test", 1),
    () => order({"Y-2PACK": 2}, "express-c@bench.test", 0),
  ]);
}
