// App-wide activity (DESIGN §7.6, §12.3): any run is notified from any page, once per event.
import { afterEach, expect, mock, test } from "bun:test";
import { useEffect } from "react";
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

// e2e audit 2026-11-05: the tray lagged the run page both ways, up to its 10 s beat. The run page
// now tells the tray what it sees; these beats are a minute long, so only that can move the tray.
function Observer({ id, status }: { id: string; status: WorkflowRun["status"] }) {
  const activity = useActivity();
  const observe = activity?.observe;
  useEffect(() => observe?.(id, status), [observe, id, status]);
  return <p data-testid="active">{activity?.active.map((item) => `${item.workflow_id}:${item.status}`).join(",")}</p>;
}

function observing(pages: WorkflowRun[][], id: string, status: WorkflowRun["status"], finals: Record<string, WorkflowSummary["status"]> = {}) {
  let call = 0;
  const client = {
    getInbox: mock(async () => ({})),
    listRuns: mock(async () => ({ items: pages[Math.min(call++, pages.length - 1)], next_cursor: null })),
    getWorkflow: mock(async (runId: string) => ({ status: finals[runId] }) as WorkflowSummary),
    acknowledgeWorkflow: mock(async () => {}),
  };
  const notify = mock((_id: string, _event: string, _title: string, _body: string) => {});
  const tree = (state: WorkflowRun["status"]) => (
    <LocaleProvider serverLocale="en">
      <ActivityProvider client={client as unknown as ActivityClient} notify={notify} activeMs={60_000} inboxMs={60_000}>
        <Observer id={id} status={state} />
      </ActivityProvider>
    </LocaleProvider>
  );
  const view = render(tree(status));
  return { client, notify, view, tree };
}

test("a run the page sees start shows in the tray without waiting for its beat", async () => {
  const { view } = observing([[], [run("a", "running")]], "a", "running");

  await waitFor(() => expect(view.getByTestId("active").textContent).toBe("a:running"));
});

test("a run the page sees finish leaves the tray at once, and is told once", async () => {
  // The mount's own read and the page's first look both see it running; the finish empties it.
  const { view, tree, notify } = observing([[run("a", "running")], [run("a", "running")], []], "a", "running", { a: "succeeded" });
  await waitFor(() => expect(view.getByTestId("active").textContent).toBe("a:running"));

  view.rerender(tree("succeeded"));

  await waitFor(() => expect(view.getByTestId("active").textContent).toBe(""));
  await waitFor(() => expect(notify.mock.calls.map(([id, event]) => [id, event])).toEqual([["a", "done"]]));
});

test("a status the tray already shows asks nothing, and a lagging list is asked once per status", async () => {
  const { client, view, tree } = observing([[run("a", "running")]], "a", "running");
  await waitFor(() => expect(view.getByTestId("active").textContent).toBe("a:running"));
  const reads = client.listRuns.mock.calls.length;

  view.rerender(tree("awaiting_approval"));
  await waitFor(() => expect(client.listRuns.mock.calls.length).toBe(reads + 1));
  view.rerender(tree("awaiting_approval"));
  await new Promise((done) => setTimeout(done, 50));

  // The stored list still says running: asking again on every page poll would hammer it.
  expect(client.listRuns.mock.calls.length).toBe(reads + 1);
});

test("a run in status unknown is not asked for as active", async () => {
  // e2e audit 2026-11-02, finding 9: 218 stored `unknown` rows read as "20 running" with nothing running.
  const { client } = setup([[]], {});
  await waitFor(() => expect(client.listRuns.mock.calls.length).toBeGreaterThan(0));

  const [query] = client.listRuns.mock.calls[0] as unknown as [{ status: string[] }];
  expect(query.status).toEqual(["queued", "running", "awaiting_approval"]);
});
