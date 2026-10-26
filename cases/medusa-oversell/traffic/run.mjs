import http from "node:http";
import net from "node:net";
import {randomUUID} from "node:crypto";
import fs from "node:fs";
import {pathToFileURL} from "node:url";
const ids = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const run = Number(process.argv[3] || 1);
// Two app instances; each has its own warmed keep-alive socket.
const bases = [process.env.BENCH_URL || "http://127.0.0.1:9000", process.env.BENCH_URL_B || "http://127.0.0.1:9001"].map(u => new URL(u));
// The agent timeout lets Node honour the server's Keep-Alive hint (Medusa closes idle sockets
// after 5 s), so a pooled socket is dropped before the server closes it.
const agents = bases.map(() => new http.Agent({ keepAlive: true, timeout: 60000 }));
// The second cart of each concurrent pair is dispatched this many ms after the first.
const OFFSETS_MS = [0, 5, 20];
const offset = OFFSETS_MS[(run - 1) % OFFSETS_MS.length];
// Traffic options (argv[4], JSON): {"mode": "normal"} or {"mode": "stress", "seed": n}; optional
// "lb": "round-robin" (every request alternates instance) and "scenarios": [{id, dir}] whose
// hooks.mjs exports before(ctx) / after(ctx).
const options = JSON.parse(process.argv[4] || "{}");
let roundRobin = 0;
const stress = options.mode === "stress";
// Stress: every request group goes to a random instance, concurrent pairs are released in random
// order with random gaps, normal orders are released together with jitter, and a crowd of
// buyers hits two more kits at once. The schedule is drawn from the seed before any request,
// so it depends only on the seed (replayable), never on responses.
let state = (Number(options.seed) >>> 0) || 1;
const rand = () => { // mulberry32
  state = (state + 0x6D2B79F5) >>> 0; let t = state;
  t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
  return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const JITTER_MS = 50, BURSTS = 10, Y_STOCK = 8;
const fixedPlan = () => ({
  normal: [0, 1, 0, 1, 0].map(i => ({prep: i, done: i, delay: 0})),
  trigger: {aFirst: true, a: {prep: 0, done: 0}, b: {prep: 1, done: 1}, gap: offset},
  sequential: {a: {prep: 0, done: 0}, b: {prep: 1, done: 1}},
  legit: {aFirst: true, a: {prep: 0, done: 0}, b: {prep: 1, done: 1}, gap: offset},
  backorder: {prep: 1, done: 1},
  draft: {store: {prep: 0, done: 0}, over: {create: 0, convert: 1}, fit: {create: 0, convert: 1}},
  edit: {store: {prep: 0, done: 0}, over: {edit: 0, confirm: 1}, fit: {edit: 0, confirm: 1}},
  resale: {first: {prep: 0, done: 0}, cancel: 1, after: {prep: 0, done: 0}, list: 0, delete: 1, over: {prep: 1, done: 1}},
  crowd: [],
});
function stressPlan() {
  const i = () => (rand() < .5 ? 0 : 1), j = () => Math.floor(rand() * (JITTER_MS + 1));
  const cart = () => ({prep: i(), done: i()});
  const plan = {
    normal: Array.from({length: 5}, () => ({...cart(), delay: j()})),
    trigger: {aFirst: rand() < .5, a: cart(), b: cart(), gap: j()},
    sequential: {a: cart(), b: cart()},
    legit: {aFirst: rand() < .5, a: cart(), b: cart(), gap: j()},
    backorder: cart(),
    draft: {store: cart(), over: {create: i(), convert: i()}, fit: {create: i(), convert: i()}},
    edit: {store: cart(), over: {edit: i(), confirm: i()}, fit: {edit: i(), confirm: i()}},
    resale: {first: cart(), cancel: i(), after: cart(), list: i(), delete: i(), over: cart()},
    crowd: [],
  };
  // Crowd on W (stock 24): 6 buyers of 4 units, exactly the stock; all must be placed.
  const fits = [{"W-SINGLE": 4}, {"W-SINGLE": 2, "W-2PACK": 1}, {"W-2PACK": 2}];
  for (let n = 1; n <= 6; n++)
    plan.crowd.push({kit: "w", burst: 0, group: "crowd-w", path: "store-checkout", email: `crowd-w-${n}@bench.test`, lines: fits[Math.floor(rand() * fits.length)], ...cart(), delay: j()});
  // Bursts on Y (stock 8): up to BURSTS independent conflict trials. Each burst releases 2-4
  // carts that each fit alone (mostly multi-line) within 0-5 ms; the first burst runs together
  // with the W crowd. Placed burst orders are canceled to restore stock before the next burst.
  const shapes = [{"Y-SINGLE": 4}, {"Y-SINGLE": 2, "Y-2PACK": 2}, {"Y-SINGLE": 3, "Y-2PACK": 1}, {"Y-SINGLE": 1, "Y-2PACK": 2}, {"Y-SINGLE": 5}];
  for (let b = 1; b <= BURSTS; b++) {
    const size = 2 + Math.floor(rand() * 3);
    for (let n = 1; n <= size; n++)
      plan.crowd.push({kit: "y", burst: b, group: `burst-${b}`, path: "store-checkout", email: `burst-${b}-${n}@bench.test`, lines: shapes[Math.floor(rand() * shapes.length)], ...cart(), delay: Math.floor(rand() * 6), cancel: i()});
  }
  return plan;
}
const plan = stress ? stressPlan() : fixedPlan();
const sleep = ms => ms > 0 ? new Promise(r => setTimeout(r, ms)) : Promise.resolve();
const extraVariants = {}; // SKUs created by scenario hooks
const variant = sku => extraVariants[sku] || ids.products.flatMap(p => p.variants).find(v => v.sku === sku).id;
let adminToken; // admin API bearer token, set before the admin phases
function rawRequest(path, body, instance, method, retried = false) {
  return new Promise((resolve, reject) => {
    const payload = body === undefined ? null : JSON.stringify(body);
    const auth = adminToken && path.startsWith("/admin/") ? {authorization: `Bearer ${adminToken}`} : {};
    const req = http.request(new URL(path, bases[instance]), { method, agent: agents[instance], headers: { "x-publishable-api-key": ids.publishable_key, "content-type": "application/json", ...auth, ...(payload ? {"content-length": Buffer.byteLength(payload)} : {}) } }, res => {
      let raw = ""; res.on("data", b => raw += b); res.on("end", () => {
        let data; try { data = JSON.parse(raw); } catch { data = {raw}; }
        resolve({status: res.statusCode, data, judge_retried: retried});
      });
    });
    // No answer within 30 s is the app's outcome (e.g. a guard that hangs a workflow), not a
    // traffic error: it resolves as a non-200 response, so a checkout or cancel counts as refused.
    // Steps that need success (`required`) still throw. Every timeout is listed in the output.
    let timedOut = false;
    req.setTimeout(30000, () => { timedOut = true; req.destroy(); });
    // A pooled socket the server closed while the request was sent: the server never read it, so
    // resend once on a new connection (Node's documented pattern for keep-alive races).
    req.on("error", error => {
      if (timedOut) {
        out.timeouts.push({method, path, instance});
        resolve({status: 504, data: {bench_timeout: `no response within 30 s: ${method} ${path} on instance ${instance}`}});
      } else if (req.reusedSocket && error.code === "ECONNRESET" && !retried) rawRequest(path, body, instance, method, true).then(resolve, reject);
      else reject(error);
    });
    req.end(payload);
  });
}
// Protected host IPC captures fresh administrator state around the existing
// business request. The app has neither this socket nor an evidence descriptor.
function capture(data) {
  return new Promise((resolve, reject) => {
    const socket = net.createConnection(options.judge_refusal_socket);
    let response = "";
    socket.setTimeout(30000, () => socket.destroy(new Error("protected capture timeout")));
    socket.on("connect", () => socket.write(JSON.stringify(data) + "\n"));
    socket.on("error", reject);
    socket.on("end", () => {
      if (!response.includes("\n")) reject(new Error("incomplete protected capture"));
    });
    socket.on("data", chunk => {
      response += chunk;
      if (response.includes("\n")) {
        socket.end();
        try {
          const value = JSON.parse(response);
          if (value.error) reject(new Error(value.error)); else resolve(value);
        } catch (error) { reject(error); }
      }
    });
  });
}
async function request(path, body, instance = 0, method = body === undefined ? "GET" : "POST") {
  if (options.lb === "round-robin") instance = roundRobin++ % bases.length;
  const monitored = options.judge_refusal_socket && /^\/admin\/(returns|exchanges)(\/|$)/.test(path);
  const id = monitored ? (await capture({event:"before", path, body, instance, method})).id : randomUUID();
  let response, transport_error;
  try {
    response = await rawRequest(path, body, instance, method);
    return {...response, judge_request_id: id};
  } catch (error) {
    transport_error = String(error); throw error;
  } finally {
    if (monitored) await capture({event:"after", id, status:response?.status,
      retried:response?.judge_retried === true,
      transport_error:transport_error || response?.data?.bench_timeout});
  }
}
async function required(path, body, instance) {
  const r = await request(path, body, instance);
  if (r.status >= 400) throw new Error(`${path}: ${JSON.stringify(r)}`);
  return r.data;
}
const address = { first_name: "Bench", last_name: "Buyer", address_1: "1 Bench Street", city: "New York", province: "NY", postal_code: "10001", country_code: "us" };
const lineItems = lines => Object.entries(lines).map(([sku, quantity]) => ({variant_id: variant(sku), quantity}));
async function prepare(lines, email, instance, done = instance) {
  const items = lineItems(lines);
  const requested = Object.fromEntries(items.map(i => [i.variant_id, i.quantity]));
  const created = await request("/store/carts", { region_id: ids.region_id, email, shipping_address: address, billing_address: address, items }, instance);
  // Medusa refuses to create a cart whose lines are not available (e.g. a guard keeps stock
  // held): a refused sale, scored like a refused checkout, never a traffic error.
  if (created.status === 400 && created.data?.code === "insufficient_inventory")
    return {email, instance: done, prepared_on: instance, requested, refused_at: "cart", refused: created};
  if (created.status >= 400) throw new Error(`/store/carts: ${JSON.stringify(created)}`);
  const {cart} = created.data;
  await required(`/store/carts/${cart.id}/shipping-methods`, { option_id: ids.shipping_option_id }, instance);
  const {payment_collection} = await required("/store/payment-collections", { cart_id: cart.id }, instance);
  await required(`/store/payment-collections/${payment_collection.id}/payment-sessions`, { provider_id: "pp_system_default" }, instance);
  return {cart_id: cart.id, email, instance: done, prepared_on: instance, requested};
}
const complete = c => c.refused ? Promise.resolve(c.refused) : request(`/store/carts/${c.cart_id}/complete`, {}, c.instance);
// Release a pair, `p.gap` ms apart: cart a first unless the plan says b first. Results stay in
// a, b order.
async function release(a, b, record, p) {
  const [x, y] = p.aFirst ? [a, b] : [b, a];
  const start = process.hrtime.bigint();
  const first = complete(x);
  const dispatchedFirst = process.hrtime.bigint();
  if (p.gap) await sleep(p.gap);
  const second = complete(y);
  record.dispatch_gap_ms = Number(process.hrtime.bigint() - dispatchedFirst) / 1e6;
  const [rx, ry] = await Promise.all([first, second]);
  record.complete_elapsed_ms = Number(process.hrtime.bigint() - start) / 1e6;
  const [ra, rb] = p.aFirst ? [rx, ry] : [ry, rx];
  return [{...a, response: ra}, {...b, response: rb}];
}
// A refused admin step is an outcome, not a traffic error: keep its status and body.
const brief = r => r.status < 400 ? {status: r.status} : r;
const out = {transport: "http", instances: bases.map(String), run, mode: stress ? "stress" : "normal", seed: stress ? options.seed : null,
  dispatch_offset_ms: stress ? null : offset, plan, timeouts: [], normal: [], trigger: [], sequential: [], legit: [], backorder: [], draft: [], edit: [], resale: [], crowd: [],
  ...(options.lb && {lb: options.lb}), ...(options.scenarios && {scenario_records: {}})};
// Scenario hooks get a small API. ctx.group places orders one after another as one group on a kit
// and path, records them with the crowd (cross-checked and judged like a burst: within a group,
// stock only falls) and then cancels the placed ones so later traffic starts from full stock.
const hooks = [];
for (const s of options.scenarios || []) {
  const file = `${s.dir}/hooks.mjs`;
  if (fs.existsSync(file)) hooks.push({id: s.id, module: await import(pathToFileURL(file))});
}
const contextFor = id => ({
  ids, address, request, required, lineItems, complete, record: out.scenario_records[id] = out.scenario_records[id] || {},
  serviceURL: (name, path = "/", index = 0) => {
    const port = options.inventory_service_ports?.[name]?.[index];
    if (!port) throw new Error(`No declared inventory service endpoint: ${name}/${index}`);
    const base = new URL(`http://127.0.0.1:${port}`), url = new URL(path, base);
    if (url.origin !== base.origin) throw new Error("Inventory service path must stay on its declared endpoint");
    return url;
  },
  addVariant: (sku, id) => { extraVariants[sku] = id; },
  // A store checkout that never throws: a cart Medusa will not create counts as refused.
  order: async (lines, email, instance = 0) => {
    try { const c = await prepare(lines, email, instance); return {...c, response: await complete(c)}; }
    catch (error) { return {email, requested: Object.fromEntries(lineItems(lines).map(i => [i.variant_id, i.quantity])), response: {status: 400, data: {prepare_error: String(error.message).slice(0, 300)}}}; }
  },
  group: async (group, kit, path, steps, {cancel = true} = {}) => {
    const done = [];
    for (const step of steps) done.push({...(await step()), kit, group, path});
    out.crowd.push(...done);
    if (cancel) for (const r of done.filter(r => r.response?.status === 200)) {
      r.order_id = r.response.data.order.id;
      r.canceled = brief(await request(`/admin/orders/${r.order_id}/cancel`, {}, 1));
    }
    return done;
  },
});
const runHooks = async name => { for (const h of hooks) if (h.module[name]) await h.module[name](contextFor(h.id)); };
try {
  if (hooks.length) { adminToken = (await required("/auth/user/emailpass", ids.admin, 0)).token; await runHooks("before"); }
  // Normal orders alternate between instances so both are warmed (stress: released together).
  const normal = [];
  for (let i = 0; i < 5; i++) normal.push(await prepare({[`N${i+1}-SINGLE`]: 1}, `normal-${i+1}@bench.test`, plan.normal[i].prep, plan.normal[i].done));
  if (stress) out.normal = await Promise.all(normal.map(async (c, i) => { await sleep(plan.normal[i].delay); return {...c, response: await complete(c)}; }));
  else for (const c of normal) out.normal.push({...c, response: await complete(c)});
  // Concurrent trigger (product X, stock 10): 5 + 7 units, each cart fits alone.
  const P = plan.trigger;
  const a = await prepare({"X-SINGLE": 5}, "cart-a@bench.test", P.a.prep, P.a.done);
  const b = await prepare({"X-SINGLE": 3, "X-2PACK": 2}, "cart-b@bench.test", P.b.prep, P.b.done);
  out.trigger = await release(a, b, out, P);
  // Sequential trigger (product S, stock 10): same carts, A completes before B starts.
  const Q = plan.sequential;
  const sa = await prepare({"S-SINGLE": 5}, "seq-a@bench.test", Q.a.prep, Q.a.done);
  const sb = await prepare({"S-SINGLE": 3, "S-2PACK": 2}, "seq-b@bench.test", Q.b.prep, Q.b.done);
  out.sequential.push({...sa, response: await complete(sa)});
  out.sequential.push({...sb, response: await complete(sb)});
  // Legitimate concurrent pair (product Z, stock 16): 8 + 8 units, both must be placed.
  const L = plan.legit;
  const lc = await prepare({"Z-SINGLE": 4, "Z-2PACK": 2}, "legit-c@bench.test", L.a.prep, L.a.done);
  const ld = await prepare({"Z-SINGLE": 2, "Z-2PACK": 3}, "legit-d@bench.test", L.b.prep, L.b.done);
  out.legit = await release(lc, ld, out.legit_timing = {}, L);
  // Backorder exception (product BO, stock 4, allow_backorder): 6 units must be placed.
  const bo = await prepare({"BO-SINGLE": 6}, "backorder@bench.test", plan.backorder.prep, plan.backorder.done);
  out.backorder.push({...bo, response: await complete(bo)});
  // Admin sales paths, one after the other, each on its own product (stock 10).
  adminToken = (await required("/auth/user/emailpass", ids.admin, 0)).token;
  const D = plan.draft, E = plan.edit, R = plan.resale;
  // Draft orders (product D): after a 5-unit store order, convert a 7-unit draft (3 single +
  // 2 × 2-pack; must be refused), then a 5-unit draft that fits exactly (must be placed).
  const ds = await prepare({"D-SINGLE": 5}, "draft-store@bench.test", D.store.prep, D.store.done);
  out.draft.push({...ds, step: "store", response: await complete(ds)});
  for (const [step, lines] of [["over", {"D-SINGLE": 3, "D-2PACK": 2}], ["fit", {"D-SINGLE": 1, "D-2PACK": 2}]]) {
    const items = lineItems(lines), email = `draft-${step}@bench.test`;
    const created = await request("/admin/draft-orders", {region_id: ids.region_id, sales_channel_id: ids.sales_channel_id, email, shipping_address: address, billing_address: address, items}, D[step].create);
    const id = created.data?.draft_order?.id;
    out.draft.push({email, step, requested: Object.fromEntries(items.map(i => [i.variant_id, i.quantity])), draft_order_id: id, created: brief(created),
      response: id ? await request(`/admin/draft-orders/${id}/convert-to-order`, {}, D[step].convert) : null});
  }
  // Order edits (product E): on a placed 5-unit store order, add 3 single + 2 × 2-pack
  // (must be refused), then 1 single + 2 × 2-pack that fits exactly (must be confirmed).
  const es = await prepare({"E-SINGLE": 5}, "edit-store@bench.test", E.store.prep, E.store.done);
  const placed = await complete(es);
  out.edit.push({...es, step: "store", response: placed});
  const orderId = placed.status === 200 && placed.data?.order?.id;
  let current = es.requested;
  for (const [step, lines] of orderId ? [["over", {"E-SINGLE": 3, "E-2PACK": 2}], ["fit", {"E-SINGLE": 1, "E-2PACK": 2}]] : []) {
    const items = lineItems(lines), requested = {...current}, steps = {};
    for (const i of items) requested[i.variant_id] = (requested[i.variant_id] || 0) + i.quantity;
    let response = steps.begin = await request("/admin/order-edits", {order_id: orderId}, E[step].edit);
    if (response.status === 200) response = steps.add = await request(`/admin/order-edits/${orderId}/items`, {items}, E[step].edit);
    if (response.status === 200) response = steps.request = await request(`/admin/order-edits/${orderId}/request`, {}, E[step].edit);
    if (response.status === 200) response = await request(`/admin/order-edits/${orderId}/confirm`, {}, E[step].confirm);
    for (const k in steps) steps[k] = brief(steps[k]);
    // A refused edit stays open; cancel it so the next edit can begin.
    if (response.status === 200) current = requested;
    else steps.cancel = brief(await request(`/admin/order-edits/${orderId}`, undefined, E[step].edit, "DELETE"));
    out.edit.push({email: es.email, step, order_id: orderId, requested, steps, response});
  }
  // Resale (product R, stock 10), sequential: a 10-unit order (4 single + 3 × 2-pack) is
  // canceled through the admin API, which frees its stock, so the same 10 units sold again
  // must be placed. Then that resale's reservations are deleted through the admin API while
  // its order stays live; a further 10-unit order must be refused (its units are still owed).
  const rLines = {"R-SINGLE": 4, "R-2PACK": 3};
  const rf = await prepare(rLines, "resale-first@bench.test", R.first.prep, R.first.done);
  const first = await complete(rf);
  out.resale.push({...rf, step: "first", response: first});
  if (first.status === 200) out.resale.push({step: "cancel", order_id: first.data.order.id,
    canceled: brief(await request(`/admin/orders/${first.data.order.id}/cancel`, {}, R.cancel))});
  const ra = await prepare(rLines, "resale-after-cancel@bench.test", R.after.prep, R.after.done);
  const resold = await complete(ra);
  out.resale.push({...ra, step: "after-cancel", response: resold});
  if (resold.status === 200) {
    const lines = resold.data.order.items.map(i => i.id);
    const item = ids.inventory_items.find(i => i.sku === "R").id;
    const {reservations} = await required(`/admin/reservations?inventory_item_id=${item}&limit=100`, undefined, R.list);
    const deleted = [];
    for (const r of reservations.filter(r => lines.includes(r.line_item_id)))
      deleted.push({id: r.id, quantity: r.quantity, ...brief(await request(`/admin/reservations/${r.id}`, undefined, R.delete, "DELETE"))});
    out.resale.push({step: "delete-reservation", order_id: resold.data.order.id, deleted});
  }
  const ro = await prepare(rLines, "resale-over@bench.test", R.over.prep, R.over.done);
  out.resale.push({...ro, step: "over", response: await complete(ro)});
  // Stress crowd and bursts. A burst stops the sequence once it sells more than Y's stock (the
  // oversell stays for the checker); otherwise its placed orders are canceled.
  const fire = carts => Promise.all(carts.map(async c => { await sleep(c.delay); return {...c, response: await complete(c)}; }));
  const ready = async c => ({...(await prepare(c.lines, c.email, c.prep, c.done)), kit: c.kit, burst: c.burst, group: c.group, path: c.path, delay: c.delay, cancel_on: c.cancel});
  const units = r => Object.entries(r.lines).reduce((s, [sku, q]) => s + q * (sku.endsWith("2PACK") ? 2 : 1), 0);
  const crowdW = [];
  for (const c of plan.crowd.filter(c => c.burst === 0)) crowdW.push(await ready(c));
  for (let b = 1; b <= Math.max(0, ...plan.crowd.map(c => c.burst)); b++) {
    const spec = plan.crowd.filter(c => c.burst === b), carts = [];
    for (const c of spec) carts.push(await ready(c));
    const done = await fire(b === 1 ? [...carts, ...crowdW] : carts);
    out.crowd.push(...done);
    const placed = done.filter(r => r.kit === "y" && r.response.status === 200);
    const sold = placed.reduce((s, r) => s + units(spec.find(c => c.email === r.email)), 0);
    if (sold > Y_STOCK) { out.burst_stop = {burst: b, reason: "oversold", units: sold}; break; }
    let refused = false;
    for (const r of placed) {
      r.order_id = r.response.data.order.id;
      r.canceled = brief(await request(`/admin/orders/${r.order_id}/cancel`, {}, r.cancel_on));
      refused ||= r.canceled.status !== 200;
    }
    if (refused) { out.burst_stop = {burst: b, reason: "cancel refused"}; break; }
  }
  await runHooks("after");
} catch (error) {
  out.error = error.stack || String(error);
} finally { agents.forEach(a => a.destroy()); }
console.log(JSON.stringify(out));
