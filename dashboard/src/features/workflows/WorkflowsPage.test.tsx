/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";

import type { WorkflowRun } from "@/api/control-plane";

import { WorkflowsPage } from "./WorkflowsPage";

afterEach(cleanup);

const run = (id: string, extra: Partial<WorkflowRun> = {}): WorkflowRun => ({
  workflow_id: id,
  project_id: "p1",
  source: { display_url: `https://x.test/${id}`, platform: "x" },
  status: "succeeded",
  history_expired: false,
  artifact_count: 2,
  created_at: "2026-10-18T00:00:00Z",
  updated_at: "2026-10-18T00:00:00Z",
  ...extra,
});

function client() {
  return {
    listStylePresets: mock(async () => [{ preset_id: "news", label: "News", description: "" }]),
    startProjectWorkflow: mock(async () => ({ workflow_id: "wf_new" })),
    listProjectWorkflows: mock(async (_project: string, cursor?: string) =>
      cursor ? { items: [run("wf_b")], next_cursor: null } : { items: [run("wf_a")], next_cursor: "c1" },
    ),
    listUnassignedWorkflows: mock(async () => ({
      items: [run("wf_old", { project_id: null, status: "unknown", history_expired: true })],
      next_cursor: null,
    })),
    moveWorkflow: mock(async () => run("wf_old")),
  };
}

const PROJECTS = [{ project_id: "p1", name: "News", created_at: "", updated_at: "" }];

test("without a project the start button is disabled and says why", async () => {
  render(<MemoryRouter><WorkflowsPage client={client() as never} projectId={null} projects={[]} /></MemoryRouter>);
  const start = (await screen.findByRole("button", { name: /Start pipeline/ })) as HTMLButtonElement;
  expect(start.disabled).toBe(true);
  expect(screen.getAllByText("Select or create a project to start a workflow.").length).toBeGreaterThan(0);
});

test("lists the project's runs, loads more, and moves an unassigned run", async () => {
  const c = client();
  render(<MemoryRouter><WorkflowsPage client={c as never} projectId="p1" projects={PROJECTS} /></MemoryRouter>);
  const user = userEvent.setup();
  expect(await screen.findByRole("button", { name: "https://x.test/wf_a" })).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Load more" }));
  expect(await screen.findByRole("button", { name: "https://x.test/wf_b" })).toBeDefined();
  const unassigned = (await screen.findByText(/Unassigned/)).closest("details")!;
  expect(within(unassigned).getByText(/history expired/)).toBeDefined();
  await user.selectOptions(within(unassigned).getByRole("combobox"), "p1");
  expect(c.moveWorkflow).toHaveBeenCalledWith("wf_old", "p1");
});

test("a started workflow opens its detail route and the copy is honest", async () => {
  const c = client();
  render(
    <MemoryRouter initialEntries={["/workflows"]}>
      <Routes>
        <Route path="/workflows" element={<WorkflowsPage client={c as never} projectId="p1" projects={PROJECTS} />} />
        <Route path="/workflows/:id" element={<p>detail page</p>} />
      </Routes>
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await within(screen.getByLabelText("Style")).findByRole("option", { name: "News" });
  await user.type(screen.getByLabelText("Source URL"), "https://www.tiktok.com/@a/video/1");
  await user.click(screen.getByRole("button", { name: /Start pipeline/ }));
  expect(await screen.findByText("detail page")).toBeDefined();
  expect(c.startProjectWorkflow).toHaveBeenCalledTimes(1);
});

test("the wizard no longer promises a finished cut or unavailable review", async () => {
  render(<MemoryRouter><WorkflowsPage client={client() as never} projectId="p1" projects={PROJECTS} /></MemoryRouter>);
  expect(await screen.findByText("From source to content set")).toBeDefined();
  expect(screen.queryByText("From source to finished cut")).toBeNull();
  expect(screen.queryByText(/every stage/)).toBeNull();
  expect(screen.getByRole("option", { name: "Approval before the content set is final" })).toBeDefined();
});

test("a failed unassigned listing or load-more says so instead of vanishing", async () => {
  const c = client();
  c.listUnassignedWorkflows.mockImplementation(async () => {
    throw new Error("503");
  });
  render(<MemoryRouter><WorkflowsPage client={c as never} projectId="p1" projects={PROJECTS} /></MemoryRouter>);
  expect(await screen.findByText("Unassigned runs could not be loaded. Try again.")).toBeDefined();
  c.listProjectWorkflows.mockImplementation(async () => {
    throw new Error("503");
  });
  await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
  expect(await screen.findByText("Runs could not be loaded. Try again.")).toBeDefined();
});
