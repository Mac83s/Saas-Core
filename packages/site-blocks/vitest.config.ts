import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Uncapped, vitest starts a worker per CPU (31 on the 32-vCPU dev VM), and
    // parallel sessions froze the whole machine on 29.09. CI keeps the default.
    maxWorkers: process.env.CI ? undefined : 4,
  },
});
