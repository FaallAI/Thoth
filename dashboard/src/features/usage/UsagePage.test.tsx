/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";

import type { UsageView } from "@/api/usage";
import { LocaleProvider } from "@/lib/locale";

import { UsagePage } from "./UsagePage";

afterEach(cleanup);

const usage: UsageView = {
  workspace_id: "ws_bob", month: "2026-10", workflows: 4, videos: 2, rendered_seconds: 75.5,
  stored_bytes: 3_500_000, leases: { instagram: 1 },
  quotas: [
    { platform: "instagram", daily_leases: 3, used_today: 1, remaining_today: 2 },
    { platform: "tiktok", daily_leases: 10, used_today: 0, remaining_today: 10 },
  ],
  days: [
    { day: "2026-10-03", workflows: 3, videos: 0 },
    { day: "2026-10-05", workflows: 1, videos: 2 },
  ],
};
const NOW = new Date("2026-10-06T12:00:00Z");

const inLocale = (children: ReactNode, locale: "en" | "id" = "en") =>
  render(<LocaleProvider serverLocale={locale}>{children}</LocaleProvider>);

test("shows this month's usage and today's remaining quota, never money", async () => {
  inLocale(<UsagePage client={{ get: mock(async () => usage) }} now={NOW} />);
  expect(await screen.findByText("1m 16s")).toBeDefined();
  const row = screen.getByText("Instagram").closest("tr")!;
  expect(within(row).getByText("2 of 3")).toBeDefined();
  expect(document.body.textContent?.includes("$")).toBe(false);
});

test("the bars hold every day of the month so far, zeros included", async () => {
  inLocale(<UsagePage client={{ get: mock(async () => usage) }} now={NOW} />);
  const chart = await screen.findByRole("img", { name: /^Workflows completed:/ });
  expect(chart.getAttribute("aria-label")).toBe("Workflows completed: 1: 0, 2: 0, 3: 3, 4: 0, 5: 1, 6: 0");
  expect(chart.querySelectorAll("rect")).toHaveLength(6);
});

test("the operator's workspace has no daily limit", async () => {
  const unlimited = { ...usage, quotas: [{ platform: "instagram", daily_leases: null, used_today: 5, remaining_today: null }] };
  inLocale(<UsagePage client={{ get: mock(async () => unlimited) }} now={NOW} />);
  const row = (await screen.findByText("Instagram")).closest("tr")!;
  expect(within(row).getByText("No limit")).toBeDefined();
});

test("a failed load says so, in the chosen language", async () => {
  inLocale(<UsagePage client={{ get: mock(async () => { throw new Error("down"); }) }} />, "id");
  expect(await screen.findByText("Pemakaian tidak bisa dimuat. Coba lagi.")).toBeDefined();
});

test("the page says the shared pool can run out before the limit, and promises no report flag", async () => {
  inLocale(<UsagePage client={{ get: mock(async () => ({ ...usage, days: [] })) }} now={NOW} />);
  expect(await screen.findByText(/The shared account pool can run out before your limit/)).toBeDefined();
  expect(screen.getByText("Nothing yet this month.")).toBeDefined();
  expect(document.body.textContent?.includes("report says so")).toBe(false);
});
