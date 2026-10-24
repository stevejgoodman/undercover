import {
  act,
  cleanup,
  fireEvent,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { Proposal, Recipe, Round, RoundDetails, Scores } from "./api";
import {
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
});

const scores = (accuracy: number, grade: number): Scores => ({
  runs: 2,
  decision_accuracy: accuracy,
  accuracy,
  cost_of_mistakes: 600,
  straight_through: 0.8,
  model_cost_per_claim: 0.0011,
  seconds_per_claim: 21,
  grade,
});

const finished: Round = {
  round_id: "round-1",
  number: 1,
  thread_id: "thread-1",
  stage: "finished",
  progress: null,
  recipe_version: 1,
  version_before: 1,
  version_tried: 2,
  reason: "Fewer wrongful approvals",
  scores_before: scores(0.72, 1.8),
  scores_after: scores(0.84, 1.85),
  verdict: "kept",
  why: "accuracy improved",
  started_by: "Dana Whitfield",
  started_at: "2026-10-24T10:00:00+00:00",
  stopped_by: null,
  finished_at: "2026-10-24T10:20:00+00:00",
  cost: 0.2731,
  spending_limit: 0.5,
};

const change: Proposal = {
  proposal_id: 7,
  kind: "change",
  status: "waiting",
  reason: "Refer a claim with a missing document",
  based_on: 2,
  instructions: "Decide the claim.\nRefer a claim missing a document.",
  model_before: "openai/gpt-6-luna",
  model: "openai/gpt-6-luna",
  reasoning_effort_before: "low",
  reasoning_effort: "medium",
  recipe: null,
  diff: [
    { change: "unchanged", text: "Decide the claim." },
    { change: "added", text: "Refer a claim missing a document." },
  ],
  decided_by: null,
  decided_at: null,
  rejection: null,
  created_at: "2026-10-24T11:00:00+00:00",
};

const open: Round = {
  ...finished,
  round_id: "round-2",
  number: 2,
  stage: "waiting_for_change",
  version_before: 2,
  version_tried: null,
  scores_before: scores(0.84, 1.85),
  scores_after: null,
  verdict: null,
  why: null,
  finished_at: null,
  cost: 0.0042,
};

const details = (round: Round, proposals: Proposal[] = []): RoundDetails => ({
  ...round,
  settings: firstSettings,
  models_allowed: [],
  first_evaluations_missing: [],
  proposals,
});

const recipes: Recipe[] = [
  {
    version: 2,
    recipe: "1. Read the results.\n2. Add rules for kinds of mistakes.",
    reason: "One rule per kind of mistake",
    proposed_by: "The improver, round 1",
    approved_by: "Dana Whitfield",
    approved_at: "2026-10-24T10:19:00+00:00",
    round_id: "round-1",
    created_at: "2026-10-24T10:19:00+00:00",
    diff: [
      { change: "removed", text: "2. Add a rule for each claim." },
      { change: "added", text: "2. Add rules for kinds of mistakes." },
    ],
  },
  {
    version: 1,
    recipe: "1. Call read_results.",
    reason: "The lab's first recipe",
    proposed_by: "UnderCover",
    approved_by: "UnderCover",
    approved_at: "2026-10-24T09:00:00+00:00",
    round_id: null,
    created_at: "2026-10-24T09:00:00+00:00",
    diff: [],
  },
];

function showRounds(rounds: Round[], open?: RoundDetails, handler = {}) {
  return stubApi({
    "GET /api/rounds": rounds,
    "GET /api/settings": settingsHistory,
    "GET /api/recipes": recipes,
    ...(open && { [`GET /api/rounds/${open.round_id}`]: open }),
    "POST /api/rounds": { status: "accepted" },
    ...handler,
  });
}

it("says how to start when there are no rounds", async () => {
  const fetchMock = showRounds([]);
  renderAt("/improvement");
  const rounds = await panel("Rounds");
  expect(rounds.getByText(/No rounds yet/)).toBeDefined();
  fireEvent.click(await screen.findByRole("button", { name: "Start a round" }));
  const dialog = screen.getByRole("dialog", { name: "Start a round?" });
  expect(sent(fetchMock, "POST /api/rounds")).toEqual([]);
  await act(async () => {
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Start a round" }),
    );
    await Promise.resolve();
  });
  expect(sent(fetchMock, "POST /api/rounds")).toHaveLength(1);
  expect(
    (await panel("Versions on the held-out set")).getByText(
      /No version has been measured/,
    ),
  ).toBeDefined();
});

it("shows where an open round has got to", async () => {
  const evaluating = {
    ...open,
    stage: "evaluations" as const,
    version_tried: 3,
    progress: { done: 2, of: 3 },
  };
  showRounds([evaluating, finished], details(evaluating));
  renderAt("/improvement");
  const round = await panel("Round 2");
  const current = await round.findByRole("listitem", { current: "step" });
  expect(current.textContent).toContain("Evaluations");
  expect(current.textContent).toContain("2 of 3");
  expect(round.getByText("$0.0042", { exact: false })).toBeDefined();
  expect(
    (await screen.findByRole("button", { name: "Start a round" })).getAttribute(
      "aria-disabled",
    ),
  ).toBe("true");
});

it("shows a waiting change with its diff, and approves it after the confirmation", async () => {
  const fetchMock = showRounds([open, finished], details(open, [change]), {
    "POST /api/rounds/round-2/proposals/7/decision": { status: "accepted" },
  });
  renderAt("/improvement");
  const proposal = await panel("A change is waiting for approval");
  expect(
    proposal.getByText("Refer a claim with a missing document"),
  ).toBeDefined();
  const effort = proposal.getByRole("row", { name: /Reasoning effort/ });
  expect(within(effort).getByText("low")).toBeDefined();
  expect(within(effort).getByText("medium")).toBeDefined();
  const added = proposal.getByText("Refer a claim missing a document.");
  expect(added.closest(".diff-line")?.className).toContain("diff-added");

  fireEvent.click(proposal.getByRole("button", { name: "Approve" }));
  const dialog = screen.getByRole("dialog", { name: "Approve the proposal?" });
  await act(async () => {
    fireEvent.click(within(dialog).getByRole("button", { name: "Approve" }));
    await Promise.resolve();
  });
  expect(
    sent(fetchMock, "POST /api/rounds/round-2/proposals/7/decision"),
  ).toEqual([{ decision: "approve", reason: "" }]);
});

it("rejects a proposal only with a reason", async () => {
  const fetchMock = showRounds([open], details(open, [change]), {
    "POST /api/rounds/round-2/proposals/7/decision": { status: "accepted" },
  });
  renderAt("/improvement");
  const proposal = await panel("A change is waiting for approval");
  const reject = proposal.getByRole("button", { name: "Reject" });
  expect(reject.getAttribute("aria-disabled")).toBe("true");
  fireEvent.click(reject);
  expect(screen.queryByRole("dialog")).toBeNull();
  fireEvent.change(proposal.getByLabelText(/Reason, needed to reject/), {
    target: { value: "Name no claims" },
  });
  fireEvent.click(reject);
  const dialog = screen.getByRole("dialog", { name: "Reject the proposal?" });
  expect(within(dialog).getByText("Name no claims")).toBeDefined();
  await act(async () => {
    fireEvent.click(within(dialog).getByRole("button", { name: "Reject" }));
    await Promise.resolve();
  });
  expect(
    sent(fetchMock, "POST /api/rounds/round-2/proposals/7/decision"),
  ).toEqual([{ decision: "reject", reason: "Name no claims" }]);
});

it("stops an open round after the confirmation", async () => {
  const fetchMock = showRounds([open], details(open), {
    "POST /api/rounds/round-2/stop": { ...open, stage: "stopped" },
  });
  renderAt("/improvement");
  const round = await panel("Round 2");
  fireEvent.click(round.getByRole("button", { name: "Stop the round" }));
  const dialog = screen.getByRole("dialog", { name: "Stop round 2?" });
  await act(async () => {
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Stop the round" }),
    );
    await Promise.resolve();
  });
  expect(sent(fetchMock, "POST /api/rounds/round-2/stop")).toHaveLength(1);
});

it("lists the rounds with their scores before and after, verdict and cost", async () => {
  showRounds([open, finished], details(open));
  renderAt("/improvement");
  const rounds = await panel("Rounds");
  const first = rounds.getByRole("row", { name: /Round 1/ });
  expect(within(first).getByText("72% → 84%")).toBeDefined();
  expect(within(first).getByText("1.80 → 1.85")).toBeDefined();
  expect(within(first).getByText("Kept")).toBeDefined();
  expect(within(first).getByText("accuracy improved")).toBeDefined();
  expect(within(first).getByText("$0.2731")).toBeDefined();
  const second = rounds.getByRole("row", { name: /Round 2/ });
  expect(within(second).getByText("Open")).toBeDefined();
  expect(within(second).getByText("To come")).toBeDefined();
});

it("charts each version measured on the held-out set", async () => {
  showRounds([open, finished], details(open));
  renderAt("/improvement");
  const chart = await panel("Versions on the held-out set");
  expect(
    chart.getByRole("img", {
      name: /^Held-out accuracy: version 1 72%, version 2 84%$/,
    }),
  ).toBeDefined();
  expect(
    chart.getByRole("img", {
      name: /^Held-out grade: version 1 1.8, version 2 1.9$/,
    }),
  ).toBeDefined();
});

it("shows the recipe's versions with their diffs", async () => {
  showRounds([]);
  renderAt("/improvement");
  const recipe = await panel("The improver's recipe");
  fireEvent.click(
    (await recipe.findAllByRole("button", { name: "Show changes" }))[0],
  );
  const removed = recipe.getByText("2. Add a rule for each claim.");
  expect(removed.closest(".diff-line")?.className).toContain("diff-removed");
});

it("says why a handler who can't sign off over the limit can't run rounds", async () => {
  showRounds([open], details(open, [change]), { [SIGNED_IN]: marcus });
  renderAt("/improvement");
  const proposal = await panel("A change is waiting for approval");
  expect(proposal.getByRole("note").textContent).toBe(
    "Marcus Oyelaran can't sign off payouts over $1,000.00, so only a senior handler can approve or reject a proposal.",
  );
  expect(proposal.queryByRole("button")).toBeNull();
  expect(screen.queryByRole("button", { name: "Start a round" })).toBeNull();
  expect(screen.queryByRole("button", { name: "Stop the round" })).toBeNull();
  expect(
    screen.getByText(
      "Marcus Oyelaran can't sign off payouts over $1,000.00, so only a senior handler can start or stop a round.",
    ),
  ).toBeDefined();
});

it.each([
  ["first_evaluations", "First evaluations 1 of 3", { done: 1, of: 3 }],
  ["improving", "The improver is working", null],
  ["waiting_for_change", "A change is waiting for approval", null],
  ["evaluations", "Evaluations 3 of 3", { done: 3, of: 3 }],
  ["verdict", "The verdict", null],
  ["waiting_for_recipe", "A recipe is waiting for approval", null],
] as const)("shows a round at the %s stage", async (stage, label, progress) => {
  const round = { ...open, stage, progress };
  showRounds([round], details(round));
  renderAt("/improvement");
  const panelShown = await panel("Round 2");
  const current = await panelShown.findByRole("listitem", { current: "step" });
  expect(current.textContent.replace(/^\d/, "")).toBe(label);
  const steps = panelShown.getAllByRole("listitem");
  const at = steps.indexOf(current);
  for (const step of steps.slice(0, at))
    expect(step.className).toContain("stage-done");
  for (const step of steps.slice(at + 1))
    expect(step.className).toContain("stage-to-come");
});

it("lists the rounds newest first, as the backend gives them", async () => {
  const third = { ...finished, round_id: "round-3", number: 3 };
  showRounds([third, finished]);
  renderAt("/improvement");
  const rows = (await panel("Rounds")).getAllByRole("row").slice(1);
  expect(rows.map((row) => row.textContent.slice(0, 7))).toEqual([
    "Round 3",
    "Round 1",
  ]);
});
