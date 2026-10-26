// Before the main traffic: enable backorders on both Y variants. Stress bursts on Y then
// exceed its stock; every Y cart must be placed.
export async function before(ctx) {
  ctx.record.updates = [];
  for (const v of ["variant_bench_y_single", "variant_bench_y_2pack"])
    ctx.record.updates.push((await ctx.request(`/admin/products/prod_bench_y/variants/${v}`, {allow_backorder: true}, 0)).status);
}
