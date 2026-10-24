import { expect, test } from "./signed_in";
import {
  askToPay,
  payClaim,
  recordDecision,
  recordStep,
  resumed,
  startClaim,
} from "./api";

// These tests stand in for the agent by calling the API through the
// dashboard's proxy, and watch the claim page update without a reload.

test("the claim page shows the agent at work", async ({ page, request }) => {
  await page.goto("/claims/CLM-1003");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting")).toBeVisible();
  await expect(page.getByText(/No steps yet/)).toBeVisible();

  await startClaim(request, "CLM-1003", "e2e-1");
  await recordStep(
    request,
    "CLM-1003",
    "tool_call",
    'get_claim(claim_id="CLM-1003")',
  );
  await recordStep(
    request,
    "CLM-1003",
    "tool_result",
    'get_claim: {"claim_id":"CLM-1003"}',
  );
  await expect(heading.getByText("In progress")).toBeVisible();
  await expect(
    page.getByText("The agent is working on this claim."),
  ).toBeVisible();
  await expect(page.getByText('get_claim(claim_id="CLM-1003")')).toBeVisible();
  await expect(
    page.getByText('get_claim: {"claim_id":"CLM-1003"}').first(),
  ).toBeVisible();

  await recordDecision(request, "CLM-1003", {
    decision: "approve",
    payout: 500,
    section: "Section 7, Emergency Medical",
    reason: "The treatment was necessary and covered.",
  });
  const decision = page.locator("section", {
    has: page.getByRole("heading", { name: "Decision" }),
  });
  await expect(decision.getByText("Approved")).toBeVisible();
  await expect(heading.getByText("In progress")).toBeVisible();
  await payClaim(request, "CLM-1003", 500);
  await recordStep(
    request,
    "CLM-1003",
    "message",
    "Approved and paid $500.00.",
  );
  await expect(heading.getByText("Decided")).toBeVisible();
  await expect(decision.getByText("Paid $500.00")).toBeVisible();
  await expect(page.getByText("Approved and paid $500.00.")).toBeVisible();
});

test("a sign-off on the dashboard reaches the agent's service", async ({
  page,
  request,
}) => {
  await startClaim(request, "CLM-1020", "e2e-2");
  await recordDecision(request, "CLM-1020", {
    decision: "approve",
    payout: 1350,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered.",
  });
  const refused = await askToPay(request, "CLM-1020", 1350);
  expect(refused.status()).toBe(403);

  await page.goto("/claims/CLM-1020");
  const heading = page.locator(".claim-heading");
  await expect(heading.getByText("Waiting for sign-off")).toBeVisible();
  expect(await resumed(request)).not.toContain("CLM-1020");
  await page
    .getByRole("button", { name: "Sign off as Dana Whitfield" })
    .click();
  await expect(heading.getByText("In progress")).toBeVisible();
  await expect(page.getByText(/Signed off by Dana Whitfield/)).toBeVisible();
  await expect.poll(() => resumed(request)).toContain("CLM-1020");

  // The test plays the agent, which pays the claim once it is told.
  await payClaim(request, "CLM-1020", 1350);
  await expect(heading.getByText("Decided")).toBeVisible();
  await expect(
    page.getByText(/^Paid \$1,350\.00, signed off by Dana Whitfield at /),
  ).toBeVisible();
});
