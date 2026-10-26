// Before the main traffic: add the 3-pack, then a sequential group on Y (stock 8) that only the
// new factor exposes: A 1 x 3-pack + 2 single = 5 (placed), B 1 x 3-pack + 1 x 2-pack = 5 (lines
// 3 and 2 each fit the 3 left; must be refused), C 1 x 3-pack = 3, exactly the rest (placed).
export async function before(ctx) {
  const {product} = await ctx.required("/admin/products/prod_bench_y?fields=options.id,options.title,options.values.value", undefined, 0);
  const option = product.options.find(o => o.title === "Pack");
  await ctx.required("/admin/products/prod_bench_y/options/batch", {update: [{product_option_id: option.id, add: [{value: "3-pack"}]}]}, 0);
  const created = await ctx.required("/admin/products/prod_bench_y/variants", {title: "3-pack", sku: "Y-3PACK", manage_inventory: true, allow_backorder: false,
    options: {Pack: "3-pack"}, prices: [{currency_code: "usd", amount: 30}], inventory_items: [{inventory_item_id: "iitem_bench_y", required_quantity: 3}]}, 1);
  const variant = created.product.variants.find(v => v.sku === "Y-3PACK");
  ctx.addVariant("Y-3PACK", variant.id);
  ctx.record.rule = {factors: {[variant.id]: ["y", 3]}};
  await ctx.group("s5-three-pack", "y", "store-checkout", [
    () => ctx.order({"Y-3PACK": 1, "Y-SINGLE": 2}, "three-a@bench.test", 0),
    () => ctx.order({"Y-3PACK": 1, "Y-2PACK": 1}, "three-b@bench.test", 1),
    () => ctx.order({"Y-3PACK": 1}, "three-c@bench.test", 0),
  ]);
}
