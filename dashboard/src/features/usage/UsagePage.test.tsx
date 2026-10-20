/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";

import type { UsageView } from "@/api/usage";

import { UsagePage } from "./UsagePage";

afterEach(cleanup);

const usage: UsageView = {
  workspace_id: "ws_bob", month: "2026-10", workflows: 4, videos: 2, rendered_seconds: 75.5,
  stored_bytes: 3_500_000, leases: { instagram: 1 },
  quotas: [
    { platform: "instagram", daily_leases: 3, used_today: 1, remaining_today: 2 },
    { platform: "tiktok", daily_leases: 10, used_today: 0, remaining_today: 10 },
  ],
};

test("shows this month's usage and today's remaining quota, never money", async () => {
  render(<UsagePage client={{ get: mock(async () => usage) }} />);
  expect(await screen.findByText("4")).toBeDefined();
  const row = screen.getByText("instagram").closest("tr")!;
  expect(within(row).getByText("2 of 3")).toBeDefined();
  expect(document.body.textContent?.includes("$")).toBe(false);
});

test("the operator's workspace has no daily limit", async () => {
  const unlimited = { ...usage, quotas: [{ platform: "instagram", daily_leases: null, used_today: 5, remaining_today: null }] };
  render(<UsagePage client={{ get: mock(async () => unlimited) }} />);
  const row = (await screen.findByText("instagram")).closest("tr")!;
  expect(within(row).getByText("No limit")).toBeDefined();
});

test("a failed load says so", async () => {
  render(<UsagePage client={{ get: mock(async () => { throw new Error("down"); }) }} />);
  expect(await screen.findByText("Usage could not be loaded. Try again.")).toBeDefined();
});

test("the page says the shared pool can run out before the limit, and promises no report flag", async () => {
  render(<UsagePage client={{ get: mock(async () => usage) }} />);
  expect(await screen.findByText(/The shared account pool can run out before your limit/)).toBeDefined();
  expect(document.body.textContent?.includes("report says so")).toBe(false);
});
