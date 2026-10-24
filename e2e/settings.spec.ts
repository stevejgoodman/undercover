import { expect, test } from "./signed_in";

test("a senior handler changes a setting after the confirmation", async ({
  page,
}) => {
  await page.goto("/settings");
  const settings = page.getByRole("region", {
    name: "The platform's settings",
  });
  const limit = settings.getByRole("spinbutton", {
    name: "Claim agents at once in a round",
  });
  await expect(limit).toHaveValue("25");
  await limit.fill("12");
  await settings.getByRole("button", { name: "Save changes" }).click();
  const dialog = page.getByRole("dialog", { name: "Save the settings?" });
  await dialog.getByRole("button", { name: "Save changes" }).click();
  await expect(dialog).toBeHidden();
  const row = settings.getByRole("row", {
    name: /Claim agents at once in a round/,
  });
  await expect(row.getByText(/Dana Whitfield/)).toBeVisible();
  await page.reload();
  await expect(limit).toHaveValue("12");
});

test("the appearance switches to dark and stays so", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "light" });
  await page.goto("/settings");
  const background = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await expect.poll(background).toBe("rgb(240, 244, 245)");
  await page
    .getByRole("radiogroup", { name: "Appearance" })
    .getByText("Dark")
    .click();
  await expect.poll(background).toBe("rgb(4, 35, 46)");
  await page.reload();
  await expect.poll(background).toBe("rgb(4, 35, 46)");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
});

test("light stays light on a computer set to dark", async ({ page }) => {
  await page.emulateMedia({ colorScheme: "dark" });
  await page.goto("/settings");
  const background = () =>
    page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  await expect.poll(background).toBe("rgb(4, 35, 46)");
  await page
    .getByRole("radiogroup", { name: "Appearance" })
    .getByText("Light")
    .click();
  await expect.poll(background).toBe("rgb(240, 244, 245)");
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
});
