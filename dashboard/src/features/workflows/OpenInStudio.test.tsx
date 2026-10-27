/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render as rawRender, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { LocaleProvider } from "@/lib/locale";

const inLocale = (ui: ReactElement) => <LocaleProvider serverLocale="en">{ui}</LocaleProvider>;
const render = (ui: ReactElement) => {
  const result = rawRender(inLocale(ui));
  return { ...result, rerender: (next: ReactElement) => result.rerender(inLocale(next)) };
};

import {
  StudioImportRequestError,
  type StudioImportInventory,
  type StudioSourceInspection,
  type WorkflowStudioImport,
  type WorkflowSummary,
} from "@/api/control-plane";

import { OpenInStudio } from "./OpenInStudio";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

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

const inventory = (disposition: "unresolved" | "attached" = "attached") => ({
  document_id: "edoc_old",
  source_key: KEY,
  revision: 2,
  items: [
    {
      item_id: "footage_000",
      role: "footage",
      order: 0,
      label: "Footage 1",
      platform: "tiktok",
      media_kind: "video",
      scene_id: "scene_002",
      reason: null,
      disposition,
    },
  ],
}) as unknown as StudioImportInventory;

function client(found = inspection(), result = opened(), resumed = inventory()) {
  return {
    inspectWorkflowStudioImport: mock(async () => found),
    openWorkflowInStudio: mock(async () => result),
    getStudioImportInventory: mock(async () => resumed),
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
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_old", false));
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
      getStudioImportInventory: mock(async () => inventory()),
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
    getStudioImportInventory: mock(async () => inventory()),
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

test("a cut-off import is finished after a page reload", async () => {
  const failing = {
    getStudioImportInventory: mock(async () => inventory()),
    inspectWorkflowStudioImport: mock(async () => inspection()),
    openWorkflowInStudio: mock(async (_project: string, _workflow: string, _key: string) => {
      throw new StudioImportRequestError(null, null);
    }),
  };
  render(<OpenInStudio client={failing} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByText("Offline — reconnect and try again.")).toBeDefined();
  const [[, , firstKey]] = failing.openWorkflowInStudio.mock.calls;
  cleanup(); // the page reloads: the component and its memory are gone

  const drafts = [{ document_id: "edoc_1", source_key: KEY, revision: 1, created_at: "2026-10-20T00:00:00Z" }];
  const after = {
    getStudioImportInventory: mock(async () => inventory()),
    inspectWorkflowStudioImport: mock(async () => inspection({ drafts })),
    openWorkflowInStudio: mock(async (_project: string, _workflow: string, _key: string) => opened()),
  };
  const onOpen = mock(() => {});
  render(<OpenInStudio client={after} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
  expect(after.openWorkflowInStudio.mock.calls[0][2]).toBe(firstKey);
  expect(after.inspectWorkflowStudioImport).not.toHaveBeenCalled();
  cleanup();

  // Finished: the next open asks again instead of replaying.
  render(<OpenInStudio client={after} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByRole("button", { name: /Resume draft/ })).toBeDefined();
});

test("an unfinished import belongs to its own project and run", async () => {
  localStorage.setItem("thoth.studioImport.p1.wf_other", JSON.stringify({ key: "k-other", leftOut: false }));
  localStorage.setItem("thoth.studioImport.p1.wf_1", "not json");
  const c = client();
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  await waitFor(() => expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1));
  expect(c.inspectWorkflowStudioImport).toHaveBeenCalledTimes(1);
  expect((c.openWorkflowInStudio.mock.calls[0] as unknown[])[2]).not.toBe("k-other");
});

test("a resumed draft with items still undecided opens with the gate", async () => {
  const drafts = [{ document_id: "edoc_old", source_key: KEY, revision: 2, created_at: "2026-10-19T00:00:00Z" }];
  const c = client(inspection({ drafts }), opened(), inventory("unresolved"));
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await userEvent.setup().click(await screen.findByRole("button", { name: /Resume draft/ }));
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_old", true));
  expect(c.getStudioImportInventory).toHaveBeenCalledWith("p1", "edoc_old");
});

test("the button says what it is doing", async () => {
  let answer: (value: StudioSourceInspection) => void = () => {};
  const c = {
    ...client(),
    inspectWorkflowStudioImport: mock(() => new Promise<StudioSourceInspection>((resolve) => { answer = resolve; })),
    openWorkflowInStudio: mock(() => new Promise<WorkflowStudioImport>(() => {})),
  };
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={() => {}} />);
  await open();
  expect(await screen.findByRole("button", { name: "Opening…" })).toBeDefined();
  answer(inspection());
  // Behind the progress dialog, which is modal while the import runs.
  expect(await screen.findByRole("button", { name: "Importing media…", hidden: true })).toBeDefined();
});


test("a not-placed card does not count as unfinished", async () => {
  const result = opened();
  result.items = [
    { item_id: "main_000", outcome: "copied", reason: null },
    { item_id: "comment_card_003", outcome: "not_placed", reason: null },
  ];
  const c = client(inspection(), result);
  const onOpen = mock(() => {});
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />);
  await open();
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
});

test("figures left out ask in a dialog whose new draft opens Studio, in the chosen language", async () => {
  // The live gate run wf_9fe5cf449eb84149005d2e5f: every Content Set with figures reaches this.
  const figures = {
    item_id: "figures",
    role: null,
    order: null,
    label: "figures",
    platform: null,
    media_kind: "none",
    scene_id: null,
    reason: "Figures are context, not scenes",
    disposition: "unresolved",
  } as unknown as StudioSourceInspection["items"][number];
  const c = client(inspection({ items: [figures] }));
  const onOpen = mock((_project: string, _document: string, _resolve: boolean) => {});
  rawRender(
    <LocaleProvider serverLocale="id">
      <OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={done()} onOpen={onOpen} />
    </LocaleProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Buka di Studio" }));

  const dialog = await screen.findByRole("dialog");
  expect(within(dialog).getByText("Tokoh tetap sebagai konteks: orang dan organisasi tidak menjadi scene.")).toBeDefined();
  await user.click(within(dialog).getByRole("button", { name: "Buat draf baru" }));
  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", true));
  expect(c.openWorkflowInStudio).toHaveBeenCalledTimes(1);
});

test("while the import runs a dialog shows its steps until Studio opens", async () => {
  let finish: (value: WorkflowStudioImport) => void = () => {};
  const c = {
    ...client(),
    openWorkflowInStudio: mock(() => new Promise<WorkflowStudioImport>((resolve) => { finish = resolve; })),
  };
  const onOpen = mock(() => {});
  const summary = { ...done(), title: "Kabut asap Kalteng" } as WorkflowSummary;
  render(<OpenInStudio client={c} projectId="p1" workflowId="wf_1" summary={summary} onOpen={onOpen} />);
  await open();

  const dialog = await screen.findByRole("dialog", { name: "Opening in Studio" });
  expect(dialog.textContent).toContain("Kabut asap Kalteng · Content Set from the run");
  const steps = within(within(dialog).getByRole("list", { name: "Import progress" }));
  expect(steps.getByText("Copy, probe and place media")).toBeDefined();
  expect(steps.getByText("Draft ready")).toBeDefined();
  finish(opened());

  await waitFor(() => expect(onOpen).toHaveBeenCalledWith("p1", "edoc_1", false));
  await waitFor(() => expect(screen.queryByRole("dialog", { name: "Opening in Studio" })).toBeNull());
});
