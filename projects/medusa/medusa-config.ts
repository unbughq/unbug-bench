import { defineConfig } from "@medusajs/framework/utils"
export default defineConfig({
  projectConfig: {
    databaseUrl: process.env.DATABASE_URL,
    databaseDriverOptions: { connection: { ssl: false } },
    redisUrl: process.env.REDIS_URL,
    http: { storeCors: "http://localhost:9000", adminCors: "http://localhost:9000", authCors: "http://localhost:9000", jwtSecret: "bench-local-jwt", cookieSecret: "bench-local-cookie" },
  },
  admin: { disable: true },
  modules: [
    { resolve: "@medusajs/medusa/fulfillment", options: { providers: [{ resolve: "@medusajs/fulfillment-manual", id: "manual" }] } },
    // Two app instances: the default in-memory locking provider is per process.
    { resolve: "@medusajs/medusa/locking", options: { providers: [{ resolve: "@medusajs/medusa/locking-redis", id: "locking-redis", is_default: true, options: { redisUrl: process.env.REDIS_URL } }] } },
  ],
})
