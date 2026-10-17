/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { WorkflowWizard } from "./WorkflowWizard";

afterEach(cleanup);

test("starts a workflow from source and style without Scout executor controls", async () => {
  const user = userEvent.setup();
  const fakeClient = {
    listStylePresets: mock(async () => [
      { preset_id: "news-vertical", label: "News vertical", description: "Fast-paced" },
    ]),
    createWorkflow: mock(async () => ({ workflow_id: "wf_001", status: "queued" })),
  };
  render(<WorkflowWizard client={fakeClient} onStarted={() => {}} />);

  await user.type(screen.getByLabelText("Source URL"), "https://example.test/post/1");
  await user.selectOptions(await screen.findByLabelText("Style"), "news-vertical");
  await user.click(screen.getByRole("button", { name: "Start pipeline" }));

  expect(fakeClient.createWorkflow).toHaveBeenCalledWith(expect.objectContaining({
    source: { url: "https://example.test/post/1", intent: "produce_video" },
  }), expect.any(String));
  expect(screen.queryByLabelText(/max clips|cap|raw log/i)).toBeNull();
});

test("a retry after a failed start reuses the idempotency key; a changed request gets a new one", async () => {
  const user = userEvent.setup();
  let calls = 0;
  const fakeClient = {
    listStylePresets: mock(async () => [
      { preset_id: "news-vertical", label: "News vertical", description: "Fast-paced" },
    ]),
    createWorkflow: mock(async (_request: unknown, _key: string) => {
      calls += 1;
      if (calls === 1) throw new Error("503 Service Unavailable");
      return { workflow_id: "wf_001", status: "queued" };
    }),
  };
  render(<WorkflowWizard client={fakeClient} onStarted={() => {}} />);

  await user.type(screen.getByLabelText("Source URL"), "https://example.test/post/1");
  await user.selectOptions(await screen.findByLabelText("Style"), "news-vertical");
  const start = screen.getByRole("button", { name: "Start pipeline" });
  await user.click(start);
  await screen.findByText(/Could not start the workflow/);
  await user.click(start);
  await user.type(screen.getByLabelText("Source URL"), "2");
  await user.click(start);

  const keys = fakeClient.createWorkflow.mock.calls.map((call) => call[1]);
  expect(keys).toHaveLength(3);
  expect(keys[0]).toEqual(expect.any(String));
  expect(keys[1]).toBe(keys[0]);
  expect(keys[2]).not.toBe(keys[0]);
});
