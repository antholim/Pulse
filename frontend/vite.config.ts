import react from "@vitejs/plugin-react";
import { coverageConfigDefaults, defineConfig } from "vitest/config";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    coverage: {
      provider: "v8",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/main.tsx", "src/test/**", "src/**/*.test.{ts,tsx}"],
      // json-summary feeds the coverage table in the CI run summary; lcov is uploaded to Codecov.
      reporter: [...coverageConfigDefaults.reporter, "json-summary", "lcov"],
      // CI fails below this; core logic aims for 80 percent.
      thresholds: { lines: 50, branches: 50, functions: 50, statements: 50 },
    },
  },
});
