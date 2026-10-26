// After the crowd has sold all 24 W units, post the physical count of 20.
export async function after(ctx) {
  const r = await ctx.request(`/admin/inventory-items/iitem_bench_w/location-levels/${ctx.ids.location_id}`, {stocked_quantity: 20}, 0);
  ctx.record.recount = {status: r.status, ...(r.status >= 400 ? {data: r.data} : {})};
}
