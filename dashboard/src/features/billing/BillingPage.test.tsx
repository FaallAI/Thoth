/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { BillingView } from "@/api/billing";

import { BillingPage } from "./BillingPage";

afterEach(cleanup);

const free = { plan_id: "free", name: "Free", price_idr: 0, workflows_per_period: 3, videos_per_period: 1, period_days: 30, active: true };
const pro = { ...free, plan_id: "pro", name: "Pro", price_idr: 99000, workflows_per_period: 50, videos_per_period: 20 };
const view: BillingView = {
  workspace_id: "ws_bob", unlimited: false, plan: free,
  period_start: "2026-10-20T00:00:00Z", period_end: "2026-11-19T00:00:00Z",
  workflows_used: 2, workflows_allowed: 3, videos_used: 1, videos_allowed: 1,
  plans: [free, pro], invoices: [],
};
const applied = mock(async () => ({ invoice_id: null, invoice_url: null, applied: true }));

test("shows the plan, what is left this period and the plans in rupiah", async () => {
  render(<BillingPage client={{ get: mock(async () => view), checkout: applied }} navigate={() => {}} />);
  expect(await screen.findByText("1 of 3 workflows left")).toBeDefined();
  expect(screen.getByText("0 of 1 videos left")).toBeDefined();
  expect(screen.getByText("Rp99.000 / 30 days")).toBeDefined();
});

test("choosing a paid plan goes to the payment page", async () => {
  const navigate = mock((url: string) => url);
  const checkout = mock(async () => ({ invoice_id: "inv_1", invoice_url: "https://checkout.x/1", applied: false }));
  render(<BillingPage client={{ get: mock(async () => view), checkout }} navigate={navigate} />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Choose Pro" }));
  expect(checkout).toHaveBeenCalledWith("pro");
  expect(navigate).toHaveBeenCalledWith("https://checkout.x/1");
});

test("the operator's workspace is unlimited", async () => {
  const operator = { ...view, unlimited: true, plan: null, workflows_allowed: null, videos_allowed: null };
  render(<BillingPage client={{ get: mock(async () => operator), checkout: applied }} navigate={() => {}} />);
  expect(await screen.findByText("Unlimited (operator)")).toBeDefined();
});

test("a failed checkout says so and stays on the page", async () => {
  const checkout = mock(async () => { throw new Error("checkout_failed_503"); });
  render(<BillingPage client={{ get: mock(async () => view), checkout }} navigate={() => {}} />);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Choose Pro" }));
  expect(await screen.findByText("Checkout is not available right now. Try again later.")).toBeDefined();
});
