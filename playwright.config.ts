import { defineConfig } from "@playwright/test";
import {
  AGENT_STAND_IN,
  AUTH_STAND_IN,
  HANDLER_PASSWORD,
  JUDGE_STAND_IN,
} from "./e2e/api";

// The tests run their own backend and dashboard, on their own ports and
// database, with stand-ins for the agent's service, Supabase Auth and the judge,
// so they never touch the servers started by `npm run dev`, Supabase, OpenRouter
// or `.env`.
export default defineConfig({
  testDir: "e2e",
  outputDir: "e2e/test-results",
  reporter: "list",
  use: { baseURL: "http://localhost:5174" },
  webServer: [
    {
      command: "node e2e/auth_stand_in.ts",
      url: `${AUTH_STAND_IN}/health`,
      env: { PORT: new URL(AUTH_STAND_IN).port, HANDLER_PASSWORD },
    },
    {
      command: "node e2e/judge_stand_in.ts",
      url: `${JUDGE_STAND_IN}/health`,
      env: { PORT: new URL(JUDGE_STAND_IN).port },
    },
    {
      command:
        "uv run -m backend.seed && uv run -m uvicorn backend.main:app --port 8001",
      url: "http://127.0.0.1:8001/api/health",
      // An empty DATABASE_URL keeps the tests on SQLite, whatever the shell has.
      env: {
        UNDERCOVER_DB: "e2e/undercover.db",
        DATABASE_URL: "",
        UNDERCOVER_AGENT: AGENT_STAND_IN,
        VITE_SUPABASE_URL: AUTH_STAND_IN,
        OPENROUTER_URL: JUDGE_STAND_IN,
        OPENROUTER_API_KEY: "e2e-key",
        // The judge is only called when no free model is set.
        MODEL_NAME: "",
      },
    },
    {
      command: "node e2e/agent_stand_in.ts",
      url: `${AGENT_STAND_IN}/api/health`,
      env: { PORT: new URL(AGENT_STAND_IN).port },
    },
    {
      // The e2e mode keeps Vite from reading the root .env, as development does.
      command: "npx vite dashboard --port 5174 --strictPort --mode e2e",
      url: "http://localhost:5174",
      env: {
        UNDERCOVER_API: "http://127.0.0.1:8001",
        VITE_SUPABASE_URL: AUTH_STAND_IN,
        VITE_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_e2e",
      },
    },
  ],
});
