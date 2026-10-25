import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { TRY_AGAIN } from "./components/Message";
import {
  Refusal,
  claim,
  history,
  policy,
  renderAt,
  settingsHistory,
  stubApi,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("says what to do next when a page can't load", async () => {
  stubApi({ "GET /api/claims": new Refusal(500, "The backend is down") });
  renderAt("/");
  expect((await screen.findByRole("alert")).textContent).toBe(
    "The backend is down",
  );
  expect(screen.getByText(TRY_AGAIN)).toBeDefined();
});

it("holds a page's place while it loads", async () => {
  stubApi({ "GET /api/dispatches/latest": null });
  const answer = vi.mocked(fetch).getMockImplementation();
  vi.mocked(fetch).mockImplementation((path, init) =>
    path === "/api/claims"
      ? new Promise<Response>(() => undefined)
      : (answer?.(path, init) ?? Promise.reject(new Error("No answer"))),
  );
  renderAt("/");
  const loading = await screen.findByRole("status");
  expect(loading.className).toBe("skeleton");
  expect(loading.textContent).toBe("Loading…");
});

it("places a claim under the queue, with the queue marked", async () => {
  stubApi({
    "GET /api/claims/CLM-1002": claim,
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
    "GET /api/settings": settingsHistory,
  });
  renderAt("/claims/CLM-1002");
  const crumbs = within(
    await screen.findByRole("navigation", { name: "Breadcrumb" }),
  );
  expect(crumbs.getByRole("link", { name: "Queue" }).getAttribute("href")).toBe(
    "/",
  );
  expect(crumbs.getByText("CLM-1002").getAttribute("aria-current")).toBe(
    "page",
  );
  const main = within(screen.getByRole("navigation", { name: "Main" }));
  expect(main.getByRole("link", { name: "Queue" }).className).toBe("active");
});

it("places an evaluation's copy under its evaluation", async () => {
  stubApi({
    "GET /api/claims/CLM-1002-E9": {
      ...claim,
      claim_id: "CLM-1002-E9",
      evaluation_id: "run-9",
      copy_of: "CLM-1002",
    },
    "GET /api/policies/POL-2002": policy,
    "GET /api/customers/CUS-3002/claims": history,
  });
  renderAt("/claims/CLM-1002-E9");
  const crumbs = within(
    await screen.findByRole("navigation", { name: "Breadcrumb" }),
  );
  expect(
    crumbs.getByRole("link", { name: "Evaluation" }).getAttribute("href"),
  ).toBe("/scoreboard/run-9");
  expect(crumbs.getByRole("link", { name: "Scoreboard" })).toBeDefined();
});

it("shows the settings' units beside the values a senior handler edits", async () => {
  stubApi({ "GET /api/settings": settingsHistory, "GET /api/models": [] });
  renderAt("/settings");
  const limit = await screen.findByRole("row", { name: /Approval limit/ });
  expect(within(limit).getByRole("spinbutton").parentElement?.textContent).toBe(
    "$",
  );
  const floor = screen.getByRole("row", { name: /Held-out accuracy floor/ });
  expect(within(floor).getByRole("spinbutton").parentElement?.textContent).toBe(
    "%",
  );
});
