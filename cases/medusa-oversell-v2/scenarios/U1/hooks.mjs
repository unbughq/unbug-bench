// Exercise the existing admin API; the outcome, not the contestant's explanation, is graded.
export async function before(ctx) {
  const hold = await ctx.request("/admin/reservations", {
    inventory_item_id: "iitem_bench_w", location_id: ctx.ids.location_id,
    quantity: 1, description: "expired manual hold"
  }, 0);
  ctx.record.created = hold.status;
  ctx.record.id = hold.data.reservation?.id;
  if (ctx.record.id)
    ctx.record.deleted = (await ctx.request(`/admin/reservations/${ctx.record.id}`, undefined, 1, "DELETE")).status;
}
