import { defineWorkersConfig } from "@cloudflare/vitest-pool-workers/config";

// Runs the test suite inside the Workers runtime (workerd) with a local
// D1, applying the migrations before each file. Requires `npm ci`.
export default defineWorkersConfig({
  test: {
    poolOptions: {
      workers: {
        wrangler: { configPath: "./wrangler.jsonc" },
        miniflare: {
          d1Databases: ["DB"],
          bindings: {
            TTL_SECONDS: 604800,
            MAX_PULL: 500,
            APNS_HOST: "https://api.push.apple.com",
            APNS_BUNDLE_ID: "dev.diting.mobile",
          },
        },
      },
    },
  },
});
