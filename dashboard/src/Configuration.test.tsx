import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { VersionDetails, VersionSummary } from "./api";
import { panel, renderAt, stubApi } from "./testing";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const first: VersionSummary = {
  version: 1,
  instructions: "# UnderCover Agent: working a claim\nDecide the claim.",
  model: "openai/gpt-6-luna",
  reasoning_effort: "low",
  change: "The first version",
  reason: "The claim agent as it was on Week 2 Day 4",
  proposed_by: "UnderCover",
  approved_by: "UnderCover",
  approved_at: "2026-10-24T09:00:00+00:00",
  round_id: null,
  verdict: "kept",
  created_at: "2026-10-24T09:00:00+00:00",
  current: false,
  scores: {
    evaluation: null,
    held_out: {
      runs: 2,
      decision_accuracy: 0.86,
      accuracy: 0.72,
      cost_of_mistakes: 630,
      straight_through: 0.88,
      model_cost_per_claim: 0.0011,
      seconds_per_claim: 21.4,
      grade: 1.82,
    },
  },
};

const second: VersionSummary = {
  ...first,
  version: 2,
  instructions:
    "# UnderCover Agent: working a claim\nDecide the claim carefully.",
  reasoning_effort: "medium",
  change: "Instructions and reasoning effort",
  reason: "Fewer wrongful approvals",
  proposed_by: "The improver, round 1",
  approved_by: "Dana Whitfield",
  round_id: "round-1",
  current: true,
  scores: { evaluation: null, held_out: null },
};

const secondDetails: VersionDetails = {
  ...second,
  diff: [
    { change: "unchanged", text: "# UnderCover Agent: working a claim" },
    { change: "removed", text: "Decide the claim." },
    { change: "added", text: "Decide the claim carefully." },
  ],
};

it("shows the current version and every version with its scores", async () => {
  stubApi({ "GET /api/configuration/versions": [second, first] });
  renderAt("/configuration");
  const current = await panel("Current version: 2");
  expect(current.getByText("Dana Whitfield", { exact: false })).toBeDefined();
  expect(current.getByText("medium")).toBeDefined();
  expect(current.getByText(/Decide the claim carefully/)).toBeDefined();

  const versions = await panel("Versions");
  const rows = versions.getAllByRole("row").slice(1);
  expect(rows).toHaveLength(2);
  expect(within(rows[0]).getByText("Current")).toBeDefined();
  expect(within(rows[0]).getAllByText("–")).toHaveLength(2);
  expect(within(rows[1]).getByText("Kept")).toBeDefined();
  expect(within(rows[1]).getByText("72%")).toBeDefined();
  expect(within(rows[1]).getByText("1.82")).toBeDefined();
});

it("opens what a version changed", async () => {
  stubApi({
    "GET /api/configuration/versions": [second, first],
    "GET /api/configuration/versions/2": secondDetails,
  });
  renderAt("/configuration");
  const versions = await panel("Versions");
  fireEvent.click(versions.getAllByRole("button", { name: "Show changes" })[0]);
  const changes = await panel("What version 2 changed");
  const diff = await changes.findByRole("group", {
    name: "Changes to the instructions in version 2",
  });
  const removed = within(diff).getByText("Decide the claim.");
  expect(removed.closest(".diff-line")?.className).toContain("diff-removed");
  const added = within(diff).getByText("Decide the claim carefully.");
  expect(added.closest(".diff-line")?.className).toContain("diff-added");
});

it("says the first version has nothing before it", async () => {
  stubApi({
    "GET /api/configuration/versions": [{ ...first, current: true }],
    "GET /api/configuration/versions/1": { ...first, current: true, diff: [] },
  });
  renderAt("/configuration");
  fireEvent.click(
    (await panel("Versions")).getByRole("button", { name: "Show changes" }),
  );
  expect(
    await screen.findByText(/nothing before it to compare with/),
  ).toBeDefined();
});
