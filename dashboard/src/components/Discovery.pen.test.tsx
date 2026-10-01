import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Discovery } from "./Discovery";

const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("visible discovery filters use the existing Scout request", async () => {
  const calls: { path: string; body: unknown }[] = [];
  globalThis.fetch = Object.assign(mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (init?.method === "POST") calls.push({ path, body: JSON.parse(String(init.body)) });
    return Response.json(path.endsWith("/status") ? { browser_attached: false, run: null } : {});
  }), { preconnect: originalFetch.preconnect });
  const user = userEvent.setup();
  render(<Discovery />);
  await user.type(screen.getByLabelText("Search query"), "quiet travel");
  await user.selectOptions(screen.getByLabelText("Window"), "168");
  await user.click(screen.getByRole("button", { name: "TikTok" }));
  await user.click(screen.getByRole("button", { name: "Refresh signals" }));
  expect(calls).toContainEqual({ path: "/api/scout/discover", body: { include: "quiet travel", hours: 168, tiktok: true } });
  await user.click(screen.getByRole("button", { name: "Saved" }));
  expect(screen.getByRole("status").textContent).toContain("Saved signals are not available");
});

test("building a selected topic keeps forced footage disabled without a planner", async () => {
  let submitted: Record<string, unknown> | undefined;
  globalThis.fetch = Object.assign(mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    if (path.endsWith("/run") && init?.method === "POST") submitted = JSON.parse(String(init.body));
    return Response.json(path.endsWith("/status") ? { browser_attached: false, main_footage_ready: false, run: { status: "done", kind: "discover" } } : path.endsWith("/topics") ? [{ url: "https://example.test/topic", title: "Quiet morning", score: 94 }] : {});
  }), { preconnect: originalFetch.preconnect });
  const user = userEvent.setup();
  render(<Discovery />);
  await user.click(await screen.findByRole("button", { name: /Quiet morning.*94/ }));
  await user.click(screen.getByText("Scout controls & pipeline options"));
  expect((screen.getByLabelText("Use URL media as main footage") as HTMLInputElement).disabled).toBe(true);
  await user.click(screen.getByRole("button", { name: "Build content brief" }));
  expect(submitted).toEqual({ url: "https://example.test/topic", no_comments: false, use_input_as_main: false });
});
