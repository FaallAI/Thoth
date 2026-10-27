// The run list (DESIGN §8.1) and the New run dialog (§8.2).
import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import { PlanLimitError, type RunMetrics, type RunQuery, type WorkflowRun } from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { RunsPage, type RunsClient } from "./RunsPage";

afterEach(cleanup);

const projects = [
  { project_id: "p1", name: "Haze watch", created_at: "", updated_at: "" },
  { project_id: "p2", name: "News", created_at: "", updated_at: "" },
];

function run(over: Partial<WorkflowRun>): WorkflowRun {
  return {
    workflow_id: "wf_1",
    project_id: "p1",
    source: { display_url: "https://www.tiktok.com/@a/video/1", platform: "tiktok" },
    status: "succeeded",
    history_expired: false,
    artifact_count: 1,
    created_at: "2026-10-25T07:00:00Z",
    updated_at: "2026-10-25T07:06:48Z",
    ...over,
  };
}

const NO_METRICS: RunMetrics = { runs_this_week: 0, median_run_seconds: null, success_rate: null, content_sets: 0 };

function client(items: WorkflowRun[], metrics: RunMetrics = NO_METRICS) {
  return {
    listRuns: mock(async (_query: RunQuery, _cursor?: string) => ({ items, next_cursor: null })),
    runMetrics: mock(async (_project: string | null) => metrics),
    moveWorkflow: mock(async (workflowId: string, projectId: string) => run({ workflow_id: workflowId, project_id: projectId })),
    cardUrl: (workflowId: string, card: string) => `/cards/${workflowId}/${card}`,
    listStylePresets: mock(async () => [{ preset_id: "news", label: "News vertical", description: "" }]),
    startProjectWorkflow: mock(async (_project: string, _request: unknown, _key: string) => ({ workflow_id: "wf_new" })),
  };
}

function Where() {
  const location = useLocation();
  return <p data-testid="where">{`${location.pathname}${location.search}`}</p>;
}

function page(fake: ReturnType<typeof client>, projectId: string | null = "p1", path = "/workflows") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <LocaleProvider serverLocale="en">
        <Routes>
          <Route
            path="/workflows"
            element={
              <>
                <RunsPage client={fake as unknown as RunsClient} projectId={projectId} projects={projects} />
                <Where />
              </>
            }
          />
          <Route path="/workflows/:id" element={<Where />} />
        </Routes>
      </LocaleProvider>
    </MemoryRouter>,
  );
}

test("rows show the post, where the run is, and its time; the project column only for all projects", async () => {
  const fake = client([
    run({
      workflow_id: "wf_live",
      status: "running",
      title: "Central Kalimantan air quality keeps getting worse",
      has_post_card: true,
      stages: [
        { id: "source", label: "Fetch the source", status: "completed" },
        { id: "footage", label: "Collect footage", status: "running" },
      ],
      current_step: { seq: 9, stage: "footage", attempt: 1, at: "2026-10-25T07:05:00Z", kind: "progress", code: "footage.screen_clips", n: 6, total: 12 },
    }),
    run({ workflow_id: "wf_wait", status: "awaiting_approval", title: null, project_id: null }),
  ]);
  page(fake);

  const live = await screen.findByRole("link", { name: "Central Kalimantan air quality keeps getting worse" });
  const row = live.closest("tr")!;
  expect(within(row).getByText(/Collect footage · Screening the clips/)).toBeDefined();
  expect(row.querySelector("img")?.getAttribute("src")).toBe("/cards/wf_live/post");
  // No title yet: the link stands in, and a waiting run has no duration.
  const waiting = screen.getByRole("link", { name: "https://www.tiktok.com/@a/video/1" }).closest("tr")!;
  expect(within(waiting).getByText(/Your review · waiting since/)).toBeDefined();
  expect(within(waiting).getByText("–")).toBeDefined();
  expect(screen.queryByRole("columnheader", { name: "Project" })).toBeNull();
  expect(fake.listRuns.mock.calls[0][0]).toEqual({ projectId: "p1", status: [], platform: undefined, q: undefined });
});

test("all projects lists every project, names each row's, and moves an unassigned run", async () => {
  const fake = client([run({ workflow_id: "wf_a" }), run({ workflow_id: "wf_b", project_id: null })]);
  page(fake, "all");

  expect(await screen.findByRole("columnheader", { name: "Project" })).toBeDefined();
  expect(fake.listRuns.mock.calls[0][0].projectId).toBeNull();
  expect(fake.runMetrics).toHaveBeenCalledWith(null);
  expect(screen.getByRole("cell", { name: "Haze watch" })).toBeDefined();
  await userEvent.setup().selectOptions(screen.getByRole("combobox", { name: /Move .* to a project/ }), "p2");
  expect(fake.moveWorkflow).toHaveBeenCalledWith("wf_b", "p2");
});

test("filters live in the URL and narrow the list", async () => {
  const fake = client([run({})]);
  page(fake, "p1", "/workflows?status=waiting&platform=x");
  const user = userEvent.setup();

  await screen.findByRole("link");
  expect(fake.listRuns.mock.calls[0][0]).toEqual({ projectId: "p1", status: ["awaiting_approval"], platform: "x", q: undefined });
  expect(screen.getByRole("button", { name: "Waiting" }).getAttribute("aria-pressed")).toBe("true");

  await user.click(screen.getByRole("button", { name: "Failed" }));
  await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/workflows?status=failed&platform=x"));
  await user.type(screen.getByRole("searchbox", { name: "Search runs" }), "haze{Enter}");
  await waitFor(() => expect(fake.listRuns.mock.lastCall?.[0]).toEqual({ projectId: "p1", status: ["failed"], platform: "x", q: "haze" }));
});

test("metric tiles appear only for real figures", async () => {
  page(client([run({})], { runs_this_week: 14, median_run_seconds: 460, success_rate: 0.92, content_sets: 0 }));

  expect(await screen.findByText("14")).toBeDefined();
  expect(screen.getByText("7m 40s")).toBeDefined();
  expect(screen.getByText("92%")).toBeDefined();
  expect(screen.queryByText("Content sets")).toBeNull();
});

test("an empty project invites a link, and a filtered list says nothing matches", async () => {
  const fake = client([]);
  page(fake);
  const user = userEvent.setup();

  expect(await screen.findByText("Paste a TikTok, X, Instagram or YouTube link to start.")).toBeDefined();
  await user.type(screen.getByRole("textbox", { name: "Post link" }), "https://x.com/a/status/1");
  await user.click(screen.getAllByRole("button", { name: "New run" }).at(-1)!);
  const dialog = await screen.findByRole("dialog");
  expect((within(dialog).getByRole("textbox", { name: "Post link" }) as HTMLInputElement).value).toBe("https://x.com/a/status/1");
  cleanup();

  page(client([]), "p1", "/workflows?q=nothing");
  expect(await screen.findByText("No runs match these filters.")).toBeDefined();
});

test("the New run dialog detects the platform, refuses other hosts, and opens the run", async () => {
  const fake = client([run({})]);
  page(fake);
  const user = userEvent.setup();
  await screen.findByRole("link");
  await user.click(screen.getByRole("button", { name: "New run" }));
  const dialog = await screen.findByRole("dialog");
  const link = within(dialog).getByRole("textbox", { name: "Post link" });

  await user.type(link, "https://facebook.com/a/1");
  expect(within(dialog).getByText(/This link is not supported/)).toBeDefined();
  expect((within(dialog).getByRole("button", { name: "Start run" }) as HTMLButtonElement).disabled).toBe(true);

  await user.clear(link);
  await user.type(link, "https://vt.tiktok.com/ZSj4kR8Lp/");
  expect(within(dialog).getByText("TikTok")).toBeDefined();
  await waitFor(() => expect((within(dialog).getByRole("button", { name: "Start run" }) as HTMLButtonElement).disabled).toBe(false));
  await user.click(within(dialog).getByRole("checkbox", { name: /Review before production work/ }));
  await user.click(within(dialog).getByRole("button", { name: "Start run" }));

  await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/workflows/wf_new"));
  const [project, request] = fake.startProjectWorkflow.mock.calls[0];
  expect(project).toBe("p1");
  expect(request).toEqual({
    source: { url: "https://vt.tiktok.com/ZSj4kR8Lp/", intent: "produce_video" },
    style: { preset_id: "news" },
    output: { format: "mp4", language: "id" },
    review: { require_publish_approval: false },
  });
});

test("from all projects the dialog asks for one; a retry reuses its key; the allowance says so", async () => {
  const fake = client([run({})]);
  fake.startProjectWorkflow.mockImplementationOnce(async () => {
    throw new Error("503");
  });
  fake.startProjectWorkflow.mockImplementationOnce(async () => {
    throw new PlanLimitError();
  });
  page(fake, "all");
  const user = userEvent.setup();
  await screen.findByRole("link");
  await user.click(screen.getByRole("button", { name: "New run" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByRole("textbox", { name: "Post link" }), "https://x.com/a/status/1");
  const start = within(dialog).getByRole("button", { name: "Start run" }) as HTMLButtonElement;
  await waitFor(() => expect(within(dialog).getByRole("combobox", { name: "Style" })).toBeDefined());
  expect(start.disabled).toBe(true);
  await user.selectOptions(within(dialog).getByRole("combobox", { name: "Project" }), "p2");

  await user.click(start);
  expect(await within(dialog).findByText(/Could not start the run/)).toBeDefined();
  await user.click(start);
  expect(await within(dialog).findByText(/allowance is used up/)).toBeDefined();
  const keys = fake.startProjectWorkflow.mock.calls.map((call) => call[2]);
  expect(fake.startProjectWorkflow.mock.calls[0][0]).toBe("p2");
  expect(keys[0]).toBe(keys[1]);
});
