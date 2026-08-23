import { expect, test } from "@playwright/test";

/**
 * End-to-end smoke test against a fully running stack (frontend + backend
 * + Postgres + Redis, e.g. via `docker compose up`). Covers the critical
 * user-facing path: register as a seller, create an auction, register as
 * a buyer in a second browser context, place a bid, and confirm the price
 * updates live over the WebSocket without a page reload.
 *
 * Not run in the default CI job (requires the full stack up), but is the
 * test you'd run locally / in a staging smoke-test job.
 */

function uniqueEmail(prefix: string) {
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 10000)}@example.com`;
}

test("seller creates an auction and a buyer's bid appears live", async ({ browser }) => {
  const sellerContext = await browser.newContext();
  const sellerPage = await sellerContext.newPage();

  const sellerEmail = uniqueEmail("seller");
  await sellerPage.goto("/register");
  await sellerPage.getByLabel("Full name").fill("Test Seller");
  await sellerPage.getByLabel("Email").fill(sellerEmail);
  await sellerPage.getByLabel(/Password/).fill("supersecret123");
  await sellerPage.getByLabel("I mostly want to").selectOption("seller");
  await sellerPage.getByRole("button", { name: "Sign up" }).click();
  await expect(sellerPage).toHaveURL("/");

  await sellerPage.goto("/seller");
  await sellerPage.getByRole("button", { name: "+ New Auction" }).click();
  await sellerPage.getByLabel("Title").fill("Playwright Test Item");
  await sellerPage.getByLabel("Starting price (₹)").fill("100");
  await sellerPage.getByLabel("Minimum increment (₹)").fill("5");
  await sellerPage.getByRole("button", { name: "Create auction" }).click();

  await expect(sellerPage.getByText("Playwright Test Item")).toBeVisible();
  await sellerPage.getByText("Playwright Test Item").click();
  const auctionUrl = sellerPage.url();

  const buyerContext = await browser.newContext();
  const buyerPage = await buyerContext.newPage();
  const buyerEmail = uniqueEmail("buyer");
  await buyerPage.goto("/register");
  await buyerPage.getByLabel("Full name").fill("Test Buyer");
  await buyerPage.getByLabel("Email").fill(buyerEmail);
  await buyerPage.getByLabel(/Password/).fill("supersecret123");
  await buyerPage.getByLabel("I mostly want to").selectOption("buyer");
  await buyerPage.getByRole("button", { name: "Sign up" }).click();

  await buyerPage.goto(auctionUrl);
  await buyerPage.getByLabel(/Your bid/).fill("110");
  await buyerPage.getByRole("button", { name: "Place bid" }).click();

  // Buyer's own page reflects the new price.
  await expect(buyerPage.getByText("₹110")).toBeVisible();

  // Seller's page (still open, no reload) receives the live broadcast.
  await expect(sellerPage.getByText("₹110")).toBeVisible({ timeout: 10_000 });
  await expect(sellerPage.getByText("Test Buyer")).toBeVisible();
});
