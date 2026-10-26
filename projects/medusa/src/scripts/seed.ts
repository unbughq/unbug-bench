import { ExecArgs } from "@medusajs/framework/types"
import { ContainerRegistrationKeys, Modules, ProductStatus } from "@medusajs/framework/utils"
import { createApiKeysWorkflow, createInventoryLevelsWorkflow, createProductsWorkflow, createRegionsWorkflow, createSalesChannelsWorkflow, createShippingOptionsWorkflow, createStockLocationsWorkflow, createTaxRegionsWorkflow, linkSalesChannelsToApiKeyWorkflow, linkSalesChannelsToStockLocationWorkflow, updateStoresWorkflow } from "@medusajs/medusa/core-flows"
import { writeFileSync } from "node:fs"

export default async function seed({ container }: ExecArgs) {
  const link = container.resolve(ContainerRegistrationKeys.LINK)
  const fulfillment = container.resolve(Modules.FULFILLMENT)
  const inventory = container.resolve(Modules.INVENTORY)
  const storeService = container.resolve(Modules.STORE)
  const [store] = await storeService.listStores()
  const { result: [channel] } = await createSalesChannelsWorkflow(container).run({ input: { salesChannelsData: [{ ...{id: "sc_bench"}, name: "Bench" }] } })
  await updateStoresWorkflow(container).run({ input: { selector: { id: store.id }, update: { default_sales_channel_id: channel.id, supported_currencies: [{currency_code: "usd", is_default: true}] } } })
  const { result: [region] } = await createRegionsWorkflow(container).run({ input: { regions: [{ ...{id: "reg_bench"}, name: "Bench US", currency_code: "usd", countries: ["us"], payment_providers: ["pp_system_default"] }] } })
  await createTaxRegionsWorkflow(container).run({ input: [{ country_code: "us", provider_id: "tp_system" }] })
  const { result: [location] } = await createStockLocationsWorkflow(container).run({ input: { locations: [{ ...{id: "sloc_bench"}, name: "Bench warehouse", address: { country_code: "us", city: "New York", address_1: "1 Bench Street" } }] } })
  await link.create({ [Modules.STOCK_LOCATION]: { stock_location_id: location.id }, [Modules.FULFILLMENT]: { fulfillment_provider_id: "manual_manual" } })
  let [profile] = await fulfillment.listShippingProfiles({ type: "default" })
  if (!profile) profile = await fulfillment.createShippingProfiles({ name: "Standard", type: "default" })
  const set = await fulfillment.createFulfillmentSets({ name: "Bench shipping", type: "shipping", service_zones: [{ name: "US", geo_zones: [{ country_code: "us", type: "country" }] }] })
  await link.create({ [Modules.STOCK_LOCATION]: { stock_location_id: location.id }, [Modules.FULFILLMENT]: { fulfillment_set_id: set.id } })
  const { result: [shipping] } = await createShippingOptionsWorkflow(container).run({ input: [{ name: "Bench shipping", price_type: "flat", provider_id: "manual_manual", service_zone_id: set.service_zones[0].id, shipping_profile_id: profile.id, type: { label: "Standard", description: "Standard delivery", code: "standard" }, prices: [{ currency_code: "usd", amount: 0 }, { region_id: region.id, amount: 0 }], rules: [{ attribute: "enabled_in_store", value: "true", operator: "eq" }, { attribute: "is_return", value: "false", operator: "eq" }] }] })
  // This workflow treats input IDs as updates. Normalize its newly created ID
  // after completion; local foreign keys cascade and the pricing link is explicit.
  await container.resolve(ContainerRegistrationKeys.PG_CONNECTION).transaction(async (tx: any) => {
    await tx.raw("UPDATE shipping_option SET id = ? WHERE id = ?", ["so_bench", shipping.id])
    await tx.raw("UPDATE shipping_option_price_set SET shipping_option_id = ? WHERE shipping_option_id = ?", ["so_bench", shipping.id])
  })
  shipping.id = "so_bench"
  await linkSalesChannelsToStockLocationWorkflow(container).run({ input: { id: location.id, add: [channel.id] } })
  const { result: [key] } = await createApiKeysWorkflow(container).run({ input: { api_keys: [{ ...{id: "apk_bench"}, title: "Bench", type: "publishable", created_by: "bench" }] } })
  await linkSalesChannelsToApiKeyWorkflow(container).run({ input: { id: key.id, add: [channel.id] } })
  // Publishable keys are public app credentials. Freeze this local seed token too.
  key.token = "pk_" + "b".repeat(64)
  await container.resolve(ContainerRegistrationKeys.PG_CONNECTION).raw(
    "UPDATE api_key SET token = ?, redacted = ? WHERE id = ?",
    [key.token, "pk_" + "b".repeat(3) + "***" + "b".repeat(3), key.id])
  // D and E: kit products for the admin draft-order and order-edit paths; R: cancel/resale and reservation-deletion path.
  const skus = ["X", "N1", "N2", "N3", "N4", "N5", "Y", "Z", "W", "S", "BO", "D", "E", "R"]
  const items = await inventory.createInventoryItems(skus.map(sku => ({ ...{id: `iitem_bench_${sku.toLowerCase()}`}, sku, title: sku, requires_shipping: true })))
  const variant = (sku: string, title: string, item: string, required: number, backorder = false) => ({ ...{id: `variant_bench_${sku.toLowerCase().replaceAll("-", "_")}`}, title, sku, manage_inventory: true, allow_backorder: backorder, options: { Pack: title }, prices: [{ currency_code: "usd", amount: 10 * required }], inventory_items: [{ inventory_item_id: item, required_quantity: required }] })
  const { result: products } = await createProductsWorkflow(container).run({ input: { products: items.map((item, i) => {
    const backorder = skus[i] === "BO"
    const bundled = !backorder && (i === 0 || i >= 6)
    return { id: `prod_bench_${skus[i].toLowerCase()}`,
      title: backorder ? "Backorder product BO" : bundled ? `Product ${skus[i]}` : `Normal product ${i}`,
      handle: backorder ? "backorder-bo" : bundled ? `product-${skus[i].toLowerCase()}` : `normal-${i}`,
      status: ProductStatus.PUBLISHED, shipping_profile_id: profile.id,
      options: [{ title: "Pack", values: bundled ? ["Single", "2-pack"] : ["Single"] }],
      variants: bundled ? [variant(`${skus[i]}-SINGLE`, "Single", item.id, 1), variant(`${skus[i]}-2PACK`, "2-pack", item.id, 2)] : [variant(backorder ? "BO-SINGLE" : `N${i}-SINGLE`, "Single", item.id, 1, backorder)],
      sales_channels: [{ id: channel.id }] }
  }) } })
  await createInventoryLevelsWorkflow(container).run({ input: { inventory_levels: items.map((item, i) => ({ inventory_item_id: item.id, location_id: location.id, stocked_quantity: [10, 100, 100, 100, 100, 100, 8, 16, 24, 10, 4, 10, 10, 10][i] })) } })
  const ids = { region_id: region.id, sales_channel_id: channel.id, location_id: location.id, shipping_option_id: shipping.id, publishable_key: key.token, product_x: products[0].id, inventory_x: items[0].id, variant_single: products[0].variants.find(v => v.sku === "X-SINGLE")!.id, variant_pack: products[0].variants.find(v => v.sku === "X-2PACK")!.id, normal_variants: products.slice(1, 6).map(p => p.variants[0].id), products: products.map(p => ({ id: p.id, handle: p.handle, variants: p.variants.map(v => ({ id: v.id, sku: v.sku })) })), inventory_items: items.map(i => ({ id: i.id, sku: i.sku })),
    // Local-only admin login, created by bin/setup with `medusa user`.
    admin: { email: "admin@bench.test", password: "bench-admin-local" } }
  writeFileSync("/app/seed-ids.json", JSON.stringify(ids, null, 2) + "\n")
}
