// Before the main traffic: two abandoned-cart holds on W (10 + 8 of 24), then the job runs.
// The stress crowd later needs all 24 W units, so a blocked job also shows as false blocks.
export async function before(ctx) {
  const holds = [];
  for (const quantity of [10, 8])
    holds.push((await ctx.request("/admin/reservations", {inventory_item_id: "iitem_bench_w", location_id: ctx.ids.location_id, quantity, description: "abandoned cart hold"}, 0)).status);
  const job = await ctx.request("/admin/jobs/cleanup-stale-reservations", {}, 1);
  ctx.record.holds = holds;
  ctx.record.job = {status: job.status, data: job.data};
}
