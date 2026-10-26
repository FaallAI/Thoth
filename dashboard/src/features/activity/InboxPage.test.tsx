// Inbox (DESIGN §8.7), the bell and the run tray (§7.6).
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";

import type { Inbox, WorkflowRun } from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { ActivityProvider, type ActivityClient } from "./activity";
import { InboxPage } from "./InboxPage";
import { InboxBell, RunTray } from "./TopBarActivity";

afterEach(() => {
  cleanup();
  document.title = "Thoth";
});

const projects = [{ project_id: "p1", name: "Haze watch", created_at: "", updated_at: "" }];
const at = "2026-10-27T08:00:00Z";

const INBOX: Inbox = {
  approvals: [{ workflow_id: "wf_wait", project_id: "p1", display_url: "https://x.com/a/status/1", platform: "x", status: "awaiting_approval", updated_at: at, title: "Firefighters dig peat trenches" }],
  failures: [{ workflow_id: "wf_fail", project_id: null, display_url: "https://www.instagram.com/p/x/", platform: "instagram", status: "failed", updated_at: at, failure_code: "assembly_failed" }],
  accounts: [{ account_id: "acc_1", platform: "tiktok", label: "Main TikTok", status: "cooldown", cooldown_until: at }],
};

const active = (id: string, status: WorkflowRun["status"]): WorkflowRun => ({
  workflow_id: id,
  project_id: "p1",
  source: { display_url: `https://x.com/a/status/${id}`, platform: "x" },
  status,
  history_expired: false,
  artifact_count: 0,
  created_at: at,
  updated_at: at,
  title: `Run ${id}`,
  stages: [{ id: "source", label: "Fetch the source", status: status === "awaiting_approval" ? "completed" : "running" }],
});

function setup(inbox: Inbox, runs: WorkflowRun[] = []) {
  const client = {
    getInbox: mock(async () => inbox),
    listRuns: mock(async () => ({ items: runs, next_cursor: null })),
    getWorkflow: mock(async () => ({})),
    acknowledgeWorkflow: mock(async (_id: string) => {}),
  };
  render(
    <MemoryRouter>
      <LocaleProvider serverLocale="en">
        <ActivityProvider client={client as unknown as ActivityClient} notify={() => {}}>
          <RunTray projects={projects} />
          <InboxBell />
          <InboxPage projects={projects} />
        </ActivityProvider>
      </LocaleProvider>
    </MemoryRouter>,
  );
  return client;
}

test("the inbox groups approvals, failed runs and accounts, each with one action", async () => {
  setup(INBOX);

  const approvals = await screen.findByRole("heading", { name: "Approvals" });
  const approval = approvals.parentElement!;
  expect(within(approval).getByText("Firefighters dig peat trenches")).toBeDefined();
  expect(within(approval).getByText(/Haze watch · Waiting since/)).toBeDefined();
  expect(within(approval).getByRole("link", { name: "Review" }).getAttribute("href")).toBe("/workflows/wf_wait");

  const failures = screen.getByRole("heading", { name: "Failed runs" }).parentElement!;
  expect(within(failures).getByText(/No project · Failed/)).toBeDefined();
  const accounts = screen.getByRole("heading", { name: "Accounts" }).parentElement!;
  expect(within(accounts).getByText("Main TikTok · TikTok")).toBeDefined();
  expect(within(accounts).getByText(/Cooling down until/)).toBeDefined();
});

test("acknowledging a failed run tells the server and re-reads the inbox", async () => {
  const client = setup(INBOX);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Acknowledge" }));

  expect(client.acknowledgeWorkflow).toHaveBeenCalledWith("wf_fail");
  await waitFor(() => expect(client.getInbox.mock.calls.length).toBeGreaterThan(1));
});

test("an empty inbox says nothing needs you, and the bell carries no count", async () => {
  setup({ approvals: [], failures: [], accounts: [] });

  expect(await screen.findByText("Nothing needs you.")).toBeDefined();
  expect(screen.getByRole("link", { name: "Inbox" })).toBeDefined();
});

test("the bell names the count; the tray lists active runs and sends a waiting one to review", async () => {
  setup(INBOX, [active("wf_a", "running"), active("wf_b", "awaiting_approval")]);
  const user = userEvent.setup();

  expect(await screen.findByRole("link", { name: "Inbox: 3 decisions waiting" })).toBeDefined();
  await user.click(await screen.findByRole("button", { name: "1 running · 1 waiting" }));
  const tray = await screen.findByRole("dialog");
  expect(within(tray).getByText("Active runs")).toBeDefined();
  expect(within(tray).getByRole("link", { name: "Run wf_a" })).toBeDefined();
  expect(within(tray).getByRole("link", { name: "Review" }).getAttribute("href")).toBe("/workflows/wf_b");
  expect(within(tray).getByRole("link", { name: "All runs" }).getAttribute("href")).toBe("/workflows");
});

test("the tray stays out of the top bar while nothing runs", async () => {
  setup({ approvals: [], failures: [], accounts: [] });
  await screen.findByText("Nothing needs you.");
  expect(screen.queryByRole("button", { name: /running/ })).toBeNull();
});
