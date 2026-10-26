// Fixed requests have no timing lottery; the base traffic still uses its recorded seed.
async function sell(ctx, quantity, legitimate) {
  const response = await fetch(ctx.serviceURL("marketplace", "/orders"), {
    method: "POST", headers: {"content-type": "application/json"},
    body: JSON.stringify({kit: "s", quantity}), signal: AbortSignal.timeout(15000),
  });
  const record = {requested: {s: quantity}, legitimate, response: {status: response.status, data: await response.json()}};
  (ctx.record.services ||= {}).marketplace ||= [];
  ctx.record.services.marketplace.push(record);
}
export async function before(ctx) {
  const headers = {authorization: "Basic " + Buffer.from("arm_monitor:arm_monitor").toString("base64")};
  const read = await fetch(ctx.serviceURL("marketplace", "/monitor"), {headers, signal: AbortSignal.timeout(5000)});
  const denied = await fetch(ctx.serviceURL("marketplace", "/monitor"), {signal: AbortSignal.timeout(5000)});
  const write = await fetch(ctx.serviceURL("marketplace", "/monitor"), {method: "POST", headers, signal: AbortSignal.timeout(5000)});
  ctx.record.monitor_ok = read.status === 200 && denied.status === 401 && write.status === 404 &&
    Object.keys((await read.json()).orders).length === 0;
  await sell(ctx, 2, true);
}
export async function after(ctx) {
  // Medusa's sequential first order owes 5. Of the shared 10, the channel sold 2:
  // 7 must fail, the remaining 3 must fit, and the final 1 must fail.
  await sell(ctx, 7, false);
  await sell(ctx, 3, true);
  await sell(ctx, 1, false);
}
