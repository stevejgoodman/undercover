import { expect, test } from "@playwright/test";
import {
  AUTH_STAND_IN,
  DANA,
  MARCUS,
  askToPay,
  recordDecision,
  startClaim,
} from "./api";
import { signIn } from "./signed_in";

test("the Auth stand-in serves its key and answers the browser's checks", async ({
  request,
}) => {
  const keys = await request.get(
    `${AUTH_STAND_IN}/auth/v1/.well-known/jwks.json`,
  );
  expect(((await keys.json()) as { keys: { alg: string }[] }).keys[0].alg).toBe(
    "ES256",
  );
  const preflight = await request.fetch(
    `${AUTH_STAND_IN}/auth/v1/token?grant_type=password`,
    { method: "OPTIONS" },
  );
  expect(preflight.status()).toBe(204);
  expect(preflight.headers()["access-control-allow-origin"]).toBe("*");
});

test("a handler signs in and out, and a wrong password is refused", async ({
  page,
}) => {
  await page.goto("/scoreboard");
  await page.getByLabel("Email address").fill(DANA);
  await page.getByLabel("Password").fill("not the password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText(
    "That email address and password don't match.",
  );

  await signIn(page, DANA);
  await expect(page.getByText("Dana Whitfield")).toBeVisible();
  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("heading", { name: "Sign in" })).toBeVisible();
});

test("a handler who can't sign off over the limit is told why", async ({
  page,
  request,
}) => {
  await startClaim(request, "CLM-1021", "e2e-sign-in");
  await recordDecision(request, "CLM-1021", {
    decision: "approve",
    payout: 1350,
    section: "Section 5, Baggage and Personal Effects",
    reason: "The loss is covered.",
  });
  expect((await askToPay(request, "CLM-1021", 1350)).status()).toBe(403);
  await signIn(page, MARCUS);
  await page.goto("/claims/CLM-1021");
  await expect(
    page.getByText(
      "Marcus Oyelaran can't sign off payouts over $1,000.00. A senior handler can.",
    ),
  ).toBeVisible();
  await expect(page.getByRole("button", { name: /Sign off as/ })).toHaveCount(
    0,
  );
});
