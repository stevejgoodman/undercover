import { roundWaitingOnAChange, started } from "./api";
import { expect, test } from "./signed_in";

test("a change approved on the Improvement page reaches the agent's service", async ({
  page,
  request,
}) => {
  test.setTimeout(60_000);
  const { roundId, proposalId } = await roundWaitingOnAChange(request);

  await page.goto("/");
  await page.getByRole("link", { name: "Improvement" }).click();
  await expect(page).toHaveURL("/improvement");
  const stages = page.getByRole("list", { name: /stages/ });
  await expect(stages.locator('[aria-current="step"]')).toContainText(
    "A change is waiting for approval",
  );
  const proposal = page.getByRole("region", {
    name: "A change is waiting for approval",
  });
  await expect(proposal.getByText("Fewer wrongful approvals")).toBeVisible();
  await expect(
    proposal.getByText("Refer a claim missing a document."),
  ).toBeVisible();
  await expect(
    proposal.getByRole("row", { name: /Reasoning effort/ }),
  ).toContainText("medium");

  await proposal.getByRole("button", { name: "Approve" }).click();
  const dialog = page.getByRole("dialog", { name: "Approve the proposal?" });
  await dialog.getByRole("button", { name: "Approve" }).click();
  await expect
    .poll(() => started(request))
    .toContainEqual({
      path: `/api/rounds/${roundId}/proposals/${String(proposalId)}/decision`,
      body: { decision: "approve", reason: "", handler: "Dana Whitfield" },
    });
});
