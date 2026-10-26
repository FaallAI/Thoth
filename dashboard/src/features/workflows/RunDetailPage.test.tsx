// Run detail (DESIGN §8.3-8.6): live progress, the approval card, failure and results.
import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import type { WorkflowStep, WorkflowSummary } from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { RunDetailPage, type DetailClient } from "./RunDetailPage";
import type { ContentSet } from "./RunResults";

afterEach(cleanup);

const projects = [{ project_id: "p1", name: "Haze watch", created_at: "", updated_at: "" }];

function summary(over: Partial<WorkflowSummary>): WorkflowSummary {
  return {
    workflow_id: "wf_1",
    status: "running",
    created_at: "2026-10-25T14:00:00Z",
    updated_at: "2026-10-25T14:08:12Z",
    source: { display_url: "https://x.com/namelesid/status/1", platform: "x" },
    stages: [
      { id: "source", label: "Fetch the source", status: "completed", started_at: "2026-10-25T14:00:00Z", finished_at: "2026-10-25T14:02:24Z" },
      { id: "footage", label: "Collect footage", status: "running", started_at: "2026-10-25T14:04:00Z" },
    ],
    artifacts: [],
    project_id: "p1",
    title: "Air quality in Central Kalimantan keeps getting worse",
    owner_handle: "namelesid",
    has_post_card: true,
    estimate_seconds_remaining: 150,
    ...over,
  };
}

const step = (seq: number, code: string, over: Partial<WorkflowStep> = {}): WorkflowStep => ({
  seq,
  stage: code.split(".")[0],
  attempt: 1,
  at: "2026-10-25T14:01:00Z",
  kind: "info",
  code,
  ...over,
});

const artifact = (kind: string) => ({ artifact_id: `art_${kind}`, kind, label: kind === "content_set" ? "Content set" : "Source investigation report", media_type: "application/json", location: `reports/wf_1/${kind}.json` });

function client(snapshot: WorkflowSummary, files: Record<string, unknown> = {}, steps: WorkflowStep[] = []) {
  return {
    getWorkflow: mock(async (_id: string) => snapshot),
    listWorkflowSteps: mock(async (_id: string, after: number) => ({ steps: steps.filter((item) => item.seq > after) })),
    downloadWorkflowArtifact: mock(async (_id: string, artifactId: string) => new Blob([JSON.stringify(files[artifactId] ?? {})])),
    approveWorkflow: mock(async (_id: string, _approval: unknown) => summary({ status: "running" })),
    cancelWorkflow: mock(async (_id: string) => summary({ status: "cancelled" })),
    listStylePresets: mock(async () => [{ preset_id: "news", label: "News", description: "" }]),
    startProjectWorkflow: mock(async (_project: string, _request: unknown, _key: string) => summary({ workflow_id: "wf_2" })),
    cardUrl: (id: string, card: string) => `/cards/${id}/${card}`,
    mediaUrl: (id: string, location: string) => `/media/${id}/${location}`,
    inspectWorkflowStudioImport: mock(async () => ({ project_id: "p1", source_key: "k", items: [], drafts: [], more_drafts: false })),
    openWorkflowInStudio: mock(async () => ({ draft: { document_id: "d1" }, items: [] })),
    getStudioImportInventory: mock(async () => ({ items: [] })),
  };
}

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function page(fake: ReturnType<typeof client>) {
  return render(
    <MemoryRouter initialEntries={["/workflows/wf_1"]}>
      <LocaleProvider serverLocale="en">
        <Routes>
          <Route
            path="/workflows/wf_1"
            element={<RunDetailPage client={fake as unknown as DetailClient} workflowId="wf_1" projects={projects} onOpenStudio={() => {}} />}
          />
          <Route path="*" element={<Where />} />
        </Routes>
      </LocaleProvider>
    </MemoryRouter>,
  );
}

test("a running run names its post, estimates the rest and logs its steps", async () => {
  const fake = client(summary({}), {}, [
    step(1, "source.fetch_post", { params: { platform: "x" } }),
    step(2, "footage.screen_clips", { kind: "progress", n: 6, total: 12 }),
  ]);
  page(fake);

  expect(await screen.findByRole("heading", { name: "Air quality in Central Kalimantan keeps getting worse" })).toBeDefined();
  expect(screen.getByText("X · @namelesid · Project: Haze watch")).toBeDefined();
  expect(screen.getByText("About 3 min left")).toBeDefined();
  expect(await screen.findByText("Fetched the post from X")).toBeDefined();
  expect(screen.getByText("Screening the clips")).toBeDefined();
  expect(screen.getByText("Post card captured")).toBeDefined();
});

test("cancelling asks first, names what staying means, and keeps the report", async () => {
  const fake = client(summary({}));
  page(fake);
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "Cancel run" }));
  const dialog = await screen.findByRole("alertdialog");
  expect(within(dialog).getByText(/source report and anything already made are kept/)).toBeDefined();
  await user.click(within(dialog).getByRole("button", { name: "Keep running" }));
  expect(fake.cancelWorkflow).not.toHaveBeenCalled();

  await user.click(screen.getByRole("button", { name: "Cancel run" }));
  await user.click(within(await screen.findByRole("alertdialog")).getByRole("button", { name: "Cancel run" }));
  await waitFor(() => expect(fake.cancelWorkflow).toHaveBeenCalledWith("wf_1"));
});

test("a run waiting for review shows what was found and approves or stops", async () => {
  const waiting = summary({
    status: "awaiting_approval",
    stages: [
      { id: "source", label: "Fetch the source", status: "completed" },
      { id: "approval", label: "Your review", status: "waiting", started_at: "2026-10-25T14:03:00Z" },
    ],
    approval: { approval_id: "ap_1", kind: "publish", prompt: "Review", allowed_decisions: ["approve", "reject"] },
    artifacts: [artifact("source_report")],
  });
  const fake = client(waiting, {
    art_source_report: { post: { owner_handle: "namelesid" }, media: [{}, {}], comments: [{ card: {} }, {}, { card: {} }] },
  });
  page(fake);
  const user = userEvent.setup();

  const card = await screen.findByRole("region", { name: "Review the source before production work" });
  await waitFor(() => expect(within(card).getByText("@namelesid")).toBeDefined());
  const rows = within(card).getAllByRole("definition").map((cell) => cell.textContent);
  expect(rows).toEqual(["2", "3", "2", "@namelesid"]);
  await user.click(within(card).getByRole("button", { name: "Stop here" }));
  expect(fake.approveWorkflow).toHaveBeenCalledWith("wf_1", { approval_id: "ap_1", decision: "reject" });
});

test("a failed run says where it failed and retries as a new run of the same link", async () => {
  const fake = client(
    summary({
      status: "failed",
      stages: [{ id: "assembly", label: "Build the content set", status: "failed" }],
      artifacts: [artifact("source_report")],
    }),
  );
  page(fake);
  const user = userEvent.setup();

  expect(await screen.findByText("Kept: Source investigation report")).toBeDefined();
  expect(screen.getByText("Build the content set failed")).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Retry run" }));
  await waitFor(() => expect(screen.getByTestId("where").textContent).toBe("/workflows/wf_2"));
  const [project, request] = fake.startProjectWorkflow.mock.calls[0];
  expect(project).toBe("p1");
  expect((request as { source: { url: string } }).source.url).toBe("https://x.com/namelesid/status/1");
});

test("a finished run shows its results from the content set, and its log on demand", async () => {
  const set: ContentSet = {
    attribution_verdict: "original",
    style_a: true,
    main: { title: "Air quality", owner_handle: "namelesid", platform: "x", kind: "card", card: { location: "reports/wf_1/cards/post.png", media_type: "image/png" } },
    comments: [{ author: "rinarahma", text: "Tiap pagi sesak", likes: 1200, card: { location: "reports/wf_1/cards/c1.png", media_type: "image/png" } }],
    figures: [{ name: "Sabran", type: "person", role: "Governor of Central Kalimantan" }],
    footage: [{ platform: "tiktok", owner_handle: "a", video: { location: "reports/wf_1/footage/1.mp4", media_type: "video/mp4" } }],
  };
  const fake = client(summary({ status: "succeeded", artifacts: [artifact("source_report"), artifact("content_set")] }), { art_content_set: set }, [
    step(1, "source.read_link"),
  ]);
  page(fake);

  expect(await screen.findByText("Original")).toBeDefined();
  expect(screen.getByText("Finished in 8m 12s")).toBeDefined();
  expect(screen.getByText("Sabran")).toBeDefined();
  expect(screen.getByText("Person · Governor of Central Kalimantan")).toBeDefined();
  expect(screen.getByText("Footage · 1 clip")).toBeDefined();
  expect(screen.getByText("Kept comments · 1")).toBeDefined();
  // Style A sets name the cards they missed.
  expect(screen.getAllByText("Not captured")).toHaveLength(2);
  expect(screen.getByAltText("Post").getAttribute("src")).toBe("/media/wf_1/reports/wf_1/cards/post.png");
  expect(screen.getByText("Show activity (1 steps)")).toBeDefined();
  expect(screen.getByRole("button", { name: "Download content set" })).toBeDefined();
});

test("polling stops once the run has ended", async () => {
  const fake = client(summary({ status: "succeeded" }));
  page(fake);
  await screen.findByText("Finished in 8m 12s");
  const calls = fake.getWorkflow.mock.calls.length;
  await act(() => new Promise((resolve) => setTimeout(resolve, 1_200)));
  expect(fake.getWorkflow.mock.calls.length).toBe(calls);
});

test("a stage change is announced once in the live region", async () => {
  let current = summary({});
  const fake = client(current);
  fake.getWorkflow.mockImplementation(async () => current);
  const { container } = page(fake);
  await screen.findByText("About 3 min left");

  current = summary({
    stages: [
      { id: "source", label: "Fetch the source", status: "completed" },
      { id: "footage", label: "Collect footage", status: "completed" },
    ],
  });
  await waitFor(() => expect(container.querySelector("[aria-live]")?.textContent).toBe("Collect footage: Done"), { timeout: 2_500 });
});
