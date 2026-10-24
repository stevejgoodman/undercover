import { fileURLToPath } from "node:url";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// `npm run dev` reads the Supabase settings from the root .env. The unit and
// end-to-end tests run in modes of their own and set their own values.
const ROOT = fileURLToPath(new URL("..", import.meta.url));

export default defineConfig(({ mode }) => ({
  plugins: [react()],
  envDir: mode === "development" ? ROOT : undefined,
  server: {
    proxy: { "/api": process.env.UNDERCOVER_API ?? "http://127.0.0.1:8000" },
  },
  test: {
    environment: "jsdom",
    env: {
      VITE_SUPABASE_URL: "http://auth.test",
      VITE_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_test",
    },
    coverage: {
      include: ["src/**"],
      exclude: ["src/main.tsx"],
      thresholds: { statements: 80 },
    },
  },
}));
