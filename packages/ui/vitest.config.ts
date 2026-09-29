import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./vitest.setup.ts"],
    // Uncapped, vitest starts a worker per CPU (31 on the 32-vCPU dev VM, ~5 GB),
    // and parallel sessions froze the whole machine on 29.09. CI keeps the default.
    maxWorkers: process.env.CI ? undefined : 4,
  },
});
