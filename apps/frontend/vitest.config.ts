import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: {
    jsx: "automatic",
  },
  test: {
    environment: "jsdom",
    include: ["src/**/*.test.{ts,tsx}"],
    setupFiles: ["./vitest.setup.ts"],
    // Rendering whole panels with axe checks takes 1–2 s on an idle machine
    // and passed 5 s under load (backend suite, image builds on the dev VPS):
    // three different tests failed that way on 18–19.09 and passed alone.
    testTimeout: 15_000,
  },
});
