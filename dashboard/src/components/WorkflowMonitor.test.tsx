/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { WorkflowSummary } from "@/api/control-plane";

import { WorkflowMonitor } from "./WorkflowMonitor";

afterEach(cleanup);

function summary(overrides: Partial<WorkflowSummary> = {}): WorkflowSummary {
  return {
    workflow_id: "wf_001",
    status: "running",
    created_at: "2026-08-28T08:00:00Z",
    updated_at: "2026-08-28T08:01:00Z",
    source: { display_url: "https://example.test/p", platform: "example" },
    stages: [{ id: "source", label: "Finding source", status: "running", progress: 0.5 }],
    artifacts: [],
    approval: null,
    failure: null,
    ...overrides,
  };
}

test("shows human workflow status before optional diagnostics", async () => {
  const summary: WorkflowSummary = {
    workflow_id: "wf_001",
    status: "awaiting_approval",
    created_at: "2026-08-28T08:00:00Z",
    updated_at: "2026-08-28T08:01:00Z",
    source: { display_url: "https://example.test/p", platform: "example" },
    stages: [{ id: "review", label: "Review video", status: "waiting", progress: 0.8 }],
    artifacts: [
      {
        artifact_id: "video_001",
        kind: "video",
        label: "Video",
        media_type: "video/mp4",
        location: "output/video.mp4",
      },
    ],
    approval: {
      approval_id: "approval_001",
      kind: "publish",
      prompt: "Publish this video?",
      allowed_decisions: ["approve", "reject"],
    },
    failure: null,
  };
  const client = {
    getWorkflow: mock(async () => summary),
    streamWorkflow: mock((_id: string, accept: (value: WorkflowSummary) => void) => {
      accept(summary);
      return () => {};
    }),
    cancelWorkflow: mock(async () => summary),
    retryWorkflow: mock(async () => summary),
    approveWorkflow: mock(async () => summary),
    downloadWorkflowArtifact: mock(async () => new Blob()),
  };
  render(<WorkflowMonitor workflowId="wf_001" client={client} />);

  expect(await screen.findByText(/Review video/)).toBeDefined();
  expect(screen.getByText("Progress")).toBeDefined();
  expect(screen.getByText("Needs your decision")).toBeDefined();
  expect(screen.getByText("Results")).toBeDefined();
  await userEvent.setup().click(screen.getByText("Actions & results"));
  expect(screen.getByRole("button", { name: "Retry" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Cancel" })).toBeDefined();
  expect(screen.queryByText("Diagnostics")).toBeNull();
});

test("does not let a stale initial fetch overwrite the live stream snapshot", async () => {
  let resolveInitial: (value: WorkflowSummary) => void = () => {};
  const initial = new Promise<WorkflowSummary>((resolve) => { resolveInitial = resolve; });
  const live = summary({ status: "running" });
  const client = {
    getWorkflow: mock(() => initial),
    streamWorkflow: mock((_id: string, accept: (value: WorkflowSummary) => void) => {
      accept(live);
      return () => {};
    }),
    cancelWorkflow: mock(async () => live),
    retryWorkflow: mock(async () => live),
    approveWorkflow: mock(async () => live),
    downloadWorkflowArtifact: mock(async () => new Blob()),
  };
  render(<WorkflowMonitor workflowId="wf_001" client={client} />);

  expect(await screen.findByText("running")).toBeDefined();
  resolveInitial(summary({ status: "queued" }));
  await Promise.resolve();

  expect(screen.getByText("running")).toBeDefined();
  expect(client.getWorkflow).not.toHaveBeenCalled();
});

test("renders action summaries and errors, and averages all stage progress", async () => {
  const user = userEvent.setup();
  const running = summary({
    stages: [
      { id: "source", label: "Source", status: "completed", progress: 1 },
      { id: "assets", label: "Assets", status: "running", progress: 0.5 },
      { id: "render", label: "Render", status: "queued", progress: null },
    ],
  });
  const cancelled = summary({ status: "cancelled" });
  const client = {
    getWorkflow: mock(async () => running),
    streamWorkflow: mock((_id: string, accept: (value: WorkflowSummary) => void) => {
      accept(running);
      return () => {};
    }),
    cancelWorkflow: mock(async () => cancelled),
    retryWorkflow: mock(async () => { throw new Error("checkpoint is unavailable"); }),
    approveWorkflow: mock(async () => running),
    downloadWorkflowArtifact: mock(async () => new Blob()),
  };
  render(<WorkflowMonitor workflowId="wf_001" client={client} />);

  await user.click(screen.getByText("Actions & results"));
  await user.click(screen.getByRole("button", { name: "Cancel" }));
  expect(await screen.findByText("cancelled")).toBeDefined();
  expect(screen.getByRole("progressbar").getAttribute("aria-valuenow")).toBe("50");

  await user.click(screen.getByRole("button", { name: "Retry" }));
  expect(await screen.findByText("checkpoint is unavailable")).toBeDefined();
});

test("results download through the client and an expired history is announced", async () => {
  const blob = new Blob(["{}"]);
  const downloadWorkflowArtifact = mock(async () => blob);
  const client = {
    streamWorkflow: (_id: string, onSnapshot: (snapshot: WorkflowSummary) => void) => {
      onSnapshot(
        summary({
          status: "succeeded",
          history_expired: true,
          artifacts: [
            { artifact_id: "content_set", kind: "content_set", label: "Content set", media_type: "application/json", location: "reports/wf_001/content-set.json" },
          ],
        }),
      );
      return () => {};
    },
    downloadWorkflowArtifact,
    cancelWorkflow: mock(),
    retryWorkflow: mock(),
    approveWorkflow: mock(),
  };
  const createObjectURL = URL.createObjectURL;
  const revokeObjectURL = URL.revokeObjectURL;
  URL.createObjectURL = () => "blob:x";
  URL.revokeObjectURL = () => {};
  try {
    render(<WorkflowMonitor workflowId="wf_001" client={client as never} />);
    expect(await screen.findByText("History expired; showing the stored result.")).toBeDefined();
    await userEvent.setup().click(screen.getByRole("button", { name: "Content set" }));
    expect(downloadWorkflowArtifact).toHaveBeenCalledWith("wf_001", "content_set");
  } finally {
    URL.createObjectURL = createObjectURL;
    URL.revokeObjectURL = revokeObjectURL;
  }
});

test("a downloaded artifact keeps the extension of its stored object", async () => {
  const { downloadName } = await import("@/lib/download-name");
  const artifact = (location: string) => ({ artifact_id: "clip", kind: "footage", label: "Clip", media_type: "video/mp4", location });
  expect(downloadName(artifact("reports/wf_001/footage/clip.mp4"))).toBe("clip.mp4");
  expect(downloadName(artifact("reports/wf_001/content-set.json"))).toBe("clip.json");
  expect(downloadName(artifact("reports/wf_001/noext"))).toBe("clip");
});
