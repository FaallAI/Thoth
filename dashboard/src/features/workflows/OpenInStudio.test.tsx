/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import {
  StudioImportRequestError,
  type StudioSourceInspection,
  type WorkflowStudioImport,
  type WorkflowSummary,
} from "@/api/control-plane";

import { OpenInStudio } from "./OpenInStudio";

afterEach(cleanup);

const KEY = "a".repeat(64);
const done = (artifacts = [{ artifact_id: "content_set", kind: "content_set" }], status = "succeeded") =>
  ({ workflow_id: "wf_1", status, artifacts }) as unknown as WorkflowSummary;
const inspection = (extra: Partial<StudioSourceInspection> = {}): StudioSourceInspection => ({
  project_id: "p1",
  source_key: KEY,
  items: [],
  drafts: [],
  more_drafts: false,
  ...extra,
});
const opened = (outcome: "copied" | "unresolved" = "copied"): WorkflowStudioImport => ({
  draft: { document_id: "edoc_1", source_key: KEY, revision: 2, created_at: "2026-10-20T00:00:00Z" },
  items: [{ item_id: "main_000", outcome, reason: outcome === "unresolved" ? "media_missing" : null }],
});

function client(found = inspection(), result = opened()) {
  return {
    inspectWorkflowStudioImport: mock(async () => found),
    openWorkflowInStudio: mock(async () => result),
  };
}

const open = () => userEvent.setup().click(screen.getByRole("button", { name: "Open in Studio" }));

test("the button shows only for a finished run with a Content Set", () => {
  const props = { client: client(), projectId: "p1", workflowId: "wf_1", onOpen: () => {} };
  const { rerender } = render(<OpenInStudio {...props} summary={null} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done([])} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done(undefined, "running")} />);
  expect(screen.queryByRole("button", { name: "Open in Studio" })).toBeNull();
  rerender(<OpenInStudio {...props} summary={done()} />);
  expect(screen.getByRole("button", { name: "Open in Studio" })).toBeDefined();
});

test("without an active project the button waits for one", () => {
  render(<OpenInStudio client={client()} projectId={null} workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  expect((screen.getByRole("button", { name: "Open in Studio" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText("Choose a project first.")).toBeDefined();
});

test("a first open imports straight away and opens the draft", async () => {
  const c = client();
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
  expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1);
});

test("an item left unresolved opens the draft with the gate", async () => {
  const onOpen = mock(() => {});
  render(<OpenInStudio client={client(inspection(), opened("unresolved"))} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", true));
});

test("an earlier draft can be resumed instead of imported again", async () => {
  const drafts = [{ document_id: "edoc_old", source_key: KEY, revision: 2, created_at: "2026-10-19T00:00:00Z" }];
  const c = client(inspection({ drafts }));
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await userEvent.setup().click(await screen.findByRole("button", { name: /Resume draft/ }));
  expect(onOpen).toHaveBeenCalledWith("p1", "edoc_old", false);
  expect(c.openWorkflowInStudio).not.toHaveBeenCalled();
  await userEvent.setup().click(screen.getByRole("button", { name: "Create new draft" }));
  await waitFor(() => expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1));
});

test("what Studio leaves out is listed before the import", async () => {
  const items = [
    {
      item_id: "unsupported_000",
      role: "main",
      order: 0,
      label: "main.profile_card",
      platform: null,
      media_kind: "none",
      scene_id: null,
      reason: "Cards wait for Stage 5c",
      disposition: "unresolved",
    },
  ] as StudioSourceInspection["items"];
  const c = client(inspection({ items }));
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByText("main.profile_card: Cards wait for Stage 5c")).toBeDefined();
  expect(c.openWorkflowInStudio).not.toHaveBeenCalled();
});

test("each refusal has its own words", async () => {
  const cases: [number | null, string | null, string][] = [
    [409, "workflow_in_other_project", "This run belongs to another project. Switch to that project to open it."],
    [409, "content_set_unavailable", "This run has no Content Set to open yet."],
    [409, "content_set_invalid", "Studio cannot read this run's Content Set."],
    [404, null, "This run was not found in this workspace."],
    [503, null, "Studio is not available right now. Try again later."],
    [null, null, "Offline — reconnect and try again."],
  ];
  for (const [status, code, text] of cases) {
    const c = {
      inspectWorkflowStudioImport: mock(async () => {
        throw new StudioImportRequestError(status, code);
      }),
      openWorkflowInStudio: mock(async () => opened()),
    };
    render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
    await open();
    expect(await screen.findByText(text)).toBeDefined();
    cleanup();
  }
});

const LEFT_OUT = [
  {
    item_id: "unsupported_000",
    role: "main",
    order: 0,
    label: "main.profile_card",
    platform: null,
    media_kind: "none",
    scene_id: null,
    reason: "Cards wait for Stage 5c",
    disposition: "unresolved",
  },
] as StudioSourceInspection["items"];

test("a retry after a cut-off import finishes the same draft", async () => {
  let attempts = 0;
  const c = {
    inspectWorkflowStudioImport: mock(async () => inspection()),
    openWorkflowInStudio: mock(async (_project: string, _workflow: string, _key: string) => {
      attempts += 1;
      if (attempts === 1) throw new StudioImportRequestError(503, null);
      return opened();
    }),
  };
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  expect(await screen.findByText("Studio is not available right now. Try again later.")).toBeDefined();
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
  const keys = c.openWorkflowInStudio.mock.calls.map((call) => call[2]);
  expect(keys).toHaveLength(2);
  expect(keys[1]).toBe(keys[0]);
  expect(c.inspectWorkflowStudioImport).toHaveBeenCalledTimes(1);
});

test("what Studio left out opens the draft with the gate", async () => {
  const onOpen = mock(() => {});
  render(<OpenInStudio client={client(inspection({ items: LEFT_OUT }))} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await userEvent.setup().click(await screen.findByRole("button", { name: "Create new draft" }));
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", true));
});

test("a project switch drops the choices made for the old project", async () => {
  const drafts = [{ document_id: "edoc_old", source_key: KEY, revision: 2, created_at: "2026-10-19T00:00:00Z" }];
  const c = client(inspection({ drafts }));
  const { rerender } = render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByRole("button", { name: /Resume draft/ })).toBeDefined();
  rerender(<OpenInStudio client={c} projectId="p2" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  expect(screen.queryByRole("button", { name: /Resume draft/ })).toBeNull();
});
