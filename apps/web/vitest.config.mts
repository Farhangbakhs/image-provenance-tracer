import react from "@vitejs/plugin-react";
import tsconfigPaths from "vite-tsconfig-paths";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [tsconfigPaths(), react()],
  test: {
    environment: "jsdom",
    // jsdom renders can exceed the 5 s default in CPU-contended CI containers.
    testTimeout: 15_000,
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
