// App-wide activity (DESIGN §7.6, §12.3): any run is notified from any page, once per event.
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, waitFor } from "@testing-library/react";

import type { Inbox, WorkflowRun, WorkflowSummary } from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { ActivityProvider, useActivity, type ActivityClient } from "./activity";

afterEach(() => {
  cleanup();
  document.title = "Thoth";
});

const run = (id: string, status: WorkflowRun["status"]): WorkflowRun => ({
  workflow_id: id,
  project_id: "p1",
  source: { display_url: `https://x.com/a/status/${id}`, platform: "x" },
  status,
  history_expired: false,
  artifact_count: 0,
  created_at: "2026-10-27T08:00:00Z",
  updated_at: "2026-10-27T08:00:00Z",
  title: `Title ${id}`,
});

function Probe() {
  const activity = useActivity();
  return <p data-testid="active">{activity?.active.map((item) => item.workflow_id).join(",")}</p>;
}

function setup(pages: WorkflowRun[][], finals: Record<string, WorkflowSummary["status"]>, inbox: Inbox = {}) {
  let call = 0;
  const client = {
    getInbox: mock(async () => inbox),
    listRuns: mock(async () => ({ items: pages[Math.min(call++, pages.length - 1)], next_cursor: null })),
    getWorkflow: mock(async (id: string) => ({ status: finals[id] }) as WorkflowSummary),
    acknowledgeWorkflow: mock(async () => {}),
  };
  const notify = mock((_id: string, _event: string, _title: string, _body: string) => {});
  render(
    <LocaleProvider serverLocale="en">
      <ActivityProvider client={client as unknown as ActivityClient} notify={notify} activeMs={20} inboxMs={1_000}>
        <Probe />
      </ActivityProvider>
    </LocaleProvider>,
  );
  return { client, notify };
}

test("runs that start waiting, finish or fail are told once; the first read only learns", async () => {
  const { notify } = setup(
    [
      [run("a", "running"), run("b", "running"), run("c", "awaiting_approval"), run("d", "running")],
      [run("a", "awaiting_approval"), run("c", "awaiting_approval")],
    ],
    { b: "succeeded", d: "failed" },
  );

  await waitFor(() => expect(notify.mock.calls.length).toBe(3));
  expect(notify.mock.calls.map(([id, event, title, body]) => [id, event, title, body])).toEqual([
    ["a", "waiting", "A run needs your review", "Title a"],
    ["b", "done", "A run is done", "Title b"],
    ["d", "failed", "A run failed", "Title d"],
  ]);
});

test("the tab title counts what waits in the inbox", async () => {
  setup([[]], {}, { approvals: [{ workflow_id: "w", project_id: null, display_url: "u", platform: "x", status: "awaiting_approval", updated_at: "" }], failures: [], accounts: [] });
  await waitFor(() => expect(document.title).toBe("(1) Thoth"));
});
