import { expect, test } from "./signed_in";
import type { DecisionKind } from "../dashboard/src/api";
import {
  createEvaluation,
  finishRun,
  payClaim,
  recordDecision,
  recordModelCall,
  recordWorkTime,
  startClaim,
} from "./api";

// This test stands in for the agent's service and its claim agents, playing
// out an evaluation of the held-out set's tiny claims through the API, and
// checks the Scoreboard and the evaluation's page. Only this file records
// evaluations, and its copies are its own.

test("the Scoreboard shows an evaluation played out through the API", async ({
  page,
  request,
}) => {
  const { run_id, number, claims } = await createEvaluation(
    request,
    "held_out",
    true,
    5,
  );
  const copyOf = (original: string) => `${original}-E${String(number)}`;
  expect(claims).toHaveLength(5);

  for (const { claim_id } of claims) {
    await startClaim(request, claim_id, `e2e-${claim_id}`);
    await recordModelCall(request, claim_id, run_id, 0.0125);
    await recordWorkTime(request, claim_id, run_id, 40);
  }
  const decide = (original: string, decision: DecisionKind, payout: number) =>
    recordDecision(request, copyOf(original), {
      decision,
      payout,
      section: "Section 5",
      reason: `The agent's reason on ${original}.`,
    });
  const pay = (original: string, amount: number) =>
    payClaim(request, copyOf(original), amount);
  await decide("CLM-1104", "approve", 250);
  await pay("CLM-1104", 250);
  await decide("CLM-1106", "approve", 300);
  await pay("CLM-1106", 300);
  await decide("CLM-1110", "refer", 0);
  await decide("CLM-1112", "approve", 1200);
  await finishRun(request, run_id);

  await page.goto("/scoreboard");
  const evaluation = `Evaluation #${String(number)}`;
  const row = page.getByRole("row", { name: new RegExp(`^${evaluation} `) });
  await expect(row.getByText("Finished")).toBeVisible();
  for (const shown of [
    "80%",
    "40%",
    "1.92",
    "$620.00",
    "60%",
    "$0.0125",
    "40 s",
  ])
    await expect(row.getByText(shown, { exact: true })).toBeVisible();
  await expect(row.getByRole("cell").last()).toHaveText(/^\d+ s$/);

  await row.getByRole("link", { name: evaluation }).click();
  await expect(page).toHaveURL(`/scoreboard/${run_id}`);
  const scored = page.getByRole("region", { name: "Claims" });
  for (const original of ["CLM-1106", "CLM-1112", "CLM-1114"])
    await expect(
      scored
        .getByRole("row", { name: new RegExp(copyOf(original)) })
        .getByText("Miss"),
    ).toBeVisible();
  for (const original of ["CLM-1104", "CLM-1110"])
    await expect(
      scored
        .getByRole("row", { name: new RegExp(copyOf(original)) })
        .getByText("Right"),
    ).toBeVisible();
  const undecided = scored.getByRole("row", {
    name: new RegExp(copyOf("CLM-1114")),
  });
  await expect(undecided).toContainText("No decision");
  await expect(undecided.getByText("F", { exact: true })).toBeVisible();
  const graded = scored.getByRole("row", {
    name: new RegExp(copyOf("CLM-1104")),
  });
  await expect(graded.getByText("A", { exact: true })).toBeVisible();
  await expect(graded.getByText("2.40")).toBeVisible();
  const measures = page.getByRole("region", { name: "Measures" });
  await expect(measures.getByText("$0.0001")).toBeVisible();

  await scored.getByRole("link", { name: copyOf("CLM-1112") }).click();
  await expect(page).toHaveURL(`/claims/${copyOf("CLM-1112")}`);
  await expect(
    page.getByText("A copy of CLM-1112 in an evaluation"),
  ).toBeVisible();
  await expect(
    page.getByText(
      "Held for sign-off. In an evaluation this counts as finished, and a copy can't be signed off.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: "Sign off" })).toHaveCount(0);
});
