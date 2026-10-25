import {
  act,
  cleanup,
  fireEvent,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { APPEARANCE_KEY } from "./appearance";
import {
  Refusal,
  SIGNED_IN,
  firstSettings,
  marcus,
  panel,
  renderAt,
  sent,
  settingsHistory,
  stubApi,
} from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  localStorage.clear();
  delete document.documentElement.dataset.theme;
});

const models = [
  {
    model: "openai/gpt-6-luna",
    reasoning_efforts: ["low", "medium"],
    input_price: 0.1,
    output_price: 0.5,
  },
];

const ROUTES = {
  "GET /api/settings": settingsHistory,
  "GET /api/models": models,
};

it("shows each setting with who last changed it", async () => {
  const changed = {
    ...firstSettings,
    spending_limit: 0.75,
    changed_by: "Dana Whitfield",
    changed_at: "2026-10-24T11:00:00+00:00",
  };
  stubApi({
    ...ROUTES,
    "GET /api/settings": {
      current: changed,
      changes: [changed, firstSettings],
    },
  });
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  const spending = settings.getByRole("row", {
    name: /Spending limit for each round/,
  });
  expect(within(spending).getByRole("spinbutton")).toHaveProperty(
    "value",
    "0.75",
  );
  expect(within(spending).getByText(/Dana Whitfield/)).toBeDefined();
  const limit = settings.getByRole("row", { name: /Approval limit/ });
  expect(within(limit).getByText(/UnderCover/)).toBeDefined();
  const accuracy = settings.getByRole("row", { name: /^Accuracy/ });
  const [noise, tolerance] = within(accuracy).getAllByRole("spinbutton");
  expect(
    [noise, tolerance].map((input) => (input as HTMLInputElement).value),
  ).toEqual(["10", "10"]);
});

it("saves a change after the confirmation", async () => {
  const fetchMock = stubApi({ ...ROUTES, "PUT /api/settings": firstSettings });
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  const save = settings.getByRole("button", { name: "Save changes" });
  expect(save.getAttribute("aria-disabled")).toBe("true");
  fireEvent.change(
    settings.getByRole("spinbutton", { name: "Approval limit" }),
    {
      target: { value: "2000" },
    },
  );
  fireEvent.change(
    settings.getByRole("spinbutton", { name: "Held-out accuracy floor" }),
    { target: { value: "70" } },
  );
  fireEvent.click(save);
  const dialog = screen.getByRole("dialog", { name: "Save the settings?" });
  expect(within(dialog).getByText("$2,000.00")).toBeDefined();
  expect(sent(fetchMock, "PUT /api/settings")).toEqual([]);
  await act(async () => {
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Save changes" }),
    );
    await Promise.resolve();
  });
  const [body] = sent(fetchMock, "PUT /api/settings");
  expect(body).toMatchObject({
    payout_approval_limit: 2000,
    objectives: { accuracy: 0.7, grade: 1 },
    agents: 25,
  });
});

it("cancelling the confirmation changes nothing", async () => {
  const fetchMock = stubApi(ROUTES);
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  fireEvent.change(
    settings.getByRole("spinbutton", { name: "Approval limit" }),
    {
      target: { value: "2000" },
    },
  );
  fireEvent.click(settings.getByRole("button", { name: "Save changes" }));
  fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(sent(fetchMock, "PUT /api/settings")).toEqual([]);
});

it("says why a handler who can't sign off over the limit can't change them", async () => {
  stubApi({ ...ROUTES, [SIGNED_IN]: marcus });
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  expect(settings.getByRole("note").textContent).toBe(
    "Marcus Oyelaran can't sign off payouts over $1,000.00, so only a senior handler can change the settings.",
  );
  expect(settings.queryByRole("button")).toBeNull();
  expect(settings.queryByRole("spinbutton")).toBeNull();
  const limit = settings.getByRole("row", { name: /Approval limit/ });
  expect(within(limit).getByText("$1,000.00")).toBeDefined();
});

it.each([
  ["Claim agents at once in a round", "2.5"],
  ["Claim agents at once in a round", "26"],
  ["Held-out accuracy floor", "150"],
  ["Approval limit", ""],
  ["Approval limit", "-5"],
])("won't save %s set to %j", async (label, value) => {
  const fetchMock = stubApi(ROUTES);
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  fireEvent.change(settings.getByRole("spinbutton", { name: label }), {
    target: { value },
  });
  expect(settings.getByRole("alert").textContent).toContain(label);
  const save = settings.getByRole("button", { name: "Save changes" });
  expect(save.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(save);
  expect(screen.queryByRole("dialog")).toBeNull();
  expect(sent(fetchMock, "PUT /api/settings")).toEqual([]);
});

it("shows the backend's refusal of a save", async () => {
  stubApi({ ...ROUTES, "PUT /api/settings": new Refusal(403, "Not now") });
  renderAt("/settings");
  const settings = await panel("The platform's settings");
  fireEvent.change(
    settings.getByRole("spinbutton", { name: "Approval limit" }),
    {
      target: { value: "1500" },
    },
  );
  fireEvent.click(settings.getByRole("button", { name: "Save changes" }));
  fireEvent.click(
    within(screen.getByRole("dialog")).getByRole("button", {
      name: "Save changes",
    }),
  );
  expect((await settings.findByRole("alert")).textContent).toBe("Not now");
});

it("lists the models allowed, read only", async () => {
  stubApi(ROUTES);
  renderAt("/settings");
  const allowed = await panel("Models allowed");
  const row = await allowed.findByRole("row", { name: /openai\/gpt-6-luna/ });
  expect(within(row).getByText("low, medium")).toBeDefined();
  expect(within(row).getByText("$0.10 per million tokens")).toBeDefined();
  expect(allowed.queryByRole("spinbutton")).toBeNull();
});

it("switches the appearance and remembers it", async () => {
  stubApi(ROUTES);
  renderAt("/settings");
  const appearance = await panel("Appearance");
  expect(
    appearance.getByRole("radio", { name: "Same as the computer" }),
  ).toHaveProperty("checked", true);
  fireEvent.click(appearance.getByRole("radio", { name: "Dark" }));
  expect(document.documentElement.dataset.theme).toBe("dark");
  expect(localStorage.getItem(APPEARANCE_KEY)).toBe("dark");
  fireEvent.click(
    appearance.getByRole("radio", { name: "Same as the computer" }),
  );
  expect(document.documentElement.dataset.theme).toBeUndefined();
  expect(localStorage.getItem(APPEARANCE_KEY)).toBe("system");
});
