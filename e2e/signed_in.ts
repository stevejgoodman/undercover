import { expect, type Page, test as base } from "@playwright/test";
import { DANA, HANDLER_PASSWORD } from "./api";

export async function signIn(page: Page, email: string) {
  await page.goto("/");
  await page.getByLabel("Email address").fill(email);
  await page.getByLabel("Password").fill(HANDLER_PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("button", { name: "Sign out" })).toBeVisible();
}

// Every spec's tests start with Dana Whitfield, our senior handler, signed in.
export const test = base.extend<{ signedIn: undefined }>({
  signedIn: [
    async ({ page }, use) => {
      await signIn(page, DANA);
      await use(undefined);
    },
    { auto: true },
  ],
});

export { expect };
