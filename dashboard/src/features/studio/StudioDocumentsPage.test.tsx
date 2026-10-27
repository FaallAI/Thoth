/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";

import type { EditDocumentListItem, WorkflowRun } from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { StudioDocumentsPage, type DocumentsClient } from "./StudioDocumentsPage";

afterEach(cleanup);

function Opened() {
  const { projectId, documentId } = useParams();
  return <p>{`studio ${projectId} ${documentId}`}</p>;
}

function Runs() {
  return <p>runs page</p>;
}

const doc = (id: string, fields: Partial<EditDocumentListItem> = {}): EditDocumentListItem => ({
  document_id: id,
  revision: 1,
  updated_at: "2026-10-27T08:00:00Z",
  label: id,
  imported: false,
  state: "draft",
  source_has_post_card: false,
  ...fields,
});

const finished = (id: string, title: string): WorkflowRun => ({
  workflow_id: id,
  project_id: "p1",
  source: { display_url: `https://x.com/a/status/${id}`, platform: "x" },
  status: "succeeded",
  history_expired: false,
  artifact_count: 2,
  created_at: "2026-10-27T07:00:00Z",
  updated_at: "2026-10-27T07:30:00Z",
  title,
  has_post_card: false,
});

function client(items: EditDocumentListItem[], runs: WorkflowRun[] = [finished("wf_1", "Kabut asap")]) {
  return {
    listEditDocuments: mock(async (_project: string, _cursor?: string) => ({ items, next_cursor: null as string | null })),
    createBlankDocument: mock(async () => ({ document_id: "edoc_blank" }) as never),
    listRuns: mock(async () => ({ items: runs, next_cursor: null })),
    cardUrl: mock((workflowId: string, card: string) => `/cards/${workflowId}/${card}`),
    inspectWorkflowStudioImport: mock(async () => ({ project_id: "p1", source_key: "k".repeat(64), items: [], drafts: [], more_drafts: false })),
    openWorkflowInStudio: mock(async (_project: string, _workflow: string, _key: string) => ({ draft: { document_id: "edoc_new" }, items: [] }) as never),
    getStudioImportInventory: mock(async () => ({ items: [] }) as never),
  } satisfies DocumentsClient;
}

function show(fake: DocumentsClient, locale: "en" | "id" = "en"): ReactElement {
  return (
    <LocaleProvider serverLocale={locale}>
      <MemoryRouter initialEntries={["/studio"]}>
        <Routes>
          <Route path="/studio" element={<StudioDocumentsPage client={fake} projectId="p1" />} />
          <Route path="/studio/:projectId/:documentId" element={<Opened />} />
          <Route path="/workflows" element={<Runs />} />
        </Routes>
      </MemoryRouter>
    </LocaleProvider>
  );
}

test("each document card shows its state, source run, revision and opens by URL", async () => {
  const fake = client([
    doc("edoc_1", {
      label: "Kabut asap Kalteng",
      revision: 4,
      state: "rendering",
      render_percent: 62,
      source_workflow_id: "wf_1",
      source_platform: "x",
      source_owner_handle: "namelesid",
      source_has_post_card: true,
    }),
  ]);
  render(show(fake));

  const card = await screen.findByRole("link", { name: /Kabut asap Kalteng/ });
  expect(within(card).getByText("Rendering 62%")).toBeDefined();
  expect(card.textContent).toContain("from run · X · @namelesid");
  expect(card.textContent).toContain("Rev 4");
  // The picture is the run's post card; a card the browser cannot load falls back to a plain panel.
  expect(fake.cardUrl).toHaveBeenCalledWith("wf_1", "post");
  await userEvent.setup().click(card);
  expect(await screen.findByText("studio p1 edoc_1")).toBeDefined();
});

test("a draft with no source run shows no source line and no picture", async () => {
  const fake = client([doc("edoc_1", { label: "Untitled video" })]);
  render(show(fake));

  const card = await screen.findByRole("link", { name: /Untitled video/ });
  expect(card.textContent).not.toContain("from run");
  expect(card.querySelector("img")).toBeNull();
  expect(within(card).getByText("Draft")).toBeDefined();
  expect(fake.cardUrl).not.toHaveBeenCalled();
});

test("the state tabs and the search narrow the documents", async () => {
  const fake = client([
    doc("edoc_a", { label: "Kabut asap", state: "draft" }),
    doc("edoc_b", { label: "Hotspot map", state: "rendered" }),
    doc("edoc_c", { label: "Free masks", state: "in_review", source_owner_handle: "warga.plk", source_workflow_id: "wf_c" }),
  ]);
  render(show(fake));
  const user = userEvent.setup();
  await screen.findByRole("link", { name: /Kabut asap/ });

  await user.click(screen.getByRole("button", { name: "Rendered" }));
  expect(screen.getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(["Hotspot map"]);

  await user.click(screen.getByRole("button", { name: "All" }));
  await user.type(screen.getByRole("searchbox", { name: "Search documents" }), "warga");
  expect(screen.getAllByRole("link").map((link) => link.getAttribute("aria-label"))).toEqual(["Free masks"]);

  await user.clear(screen.getByRole("searchbox", { name: "Search documents" }));
  await user.type(screen.getByRole("searchbox", { name: "Search documents" }), "nothing like it");
  expect(screen.getByText("No documents match.")).toBeDefined();
});

test("an empty project says how to start and leads to the runs", async () => {
  render(show(client([])));

  expect(await screen.findByText("Finish a run, then open it in Studio.")).toBeDefined();
  await userEvent.setup().click(screen.getByRole("button", { name: "Go to runs" }));
  expect(await screen.findByText("runs page")).toBeDefined();
});

test("more documents load on request", async () => {
  const fake = client([]);
  fake.listEditDocuments = mock(async (_project: string, cursor?: string) =>
    cursor ? { items: [doc("edoc_b")], next_cursor: null } : { items: [doc("edoc_a")], next_cursor: "c1" },
  );
  render(show(fake));

  await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
  expect(await screen.findByRole("link", { name: "edoc_b" })).toBeDefined();
});

test("Blank creates a document and opens it", async () => {
  const fake = client([]);
  render(show(fake));

  await userEvent.setup().click(await screen.findByRole("button", { name: "Blank" }));
  expect(await screen.findByText("studio p1 edoc_blank")).toBeDefined();
  expect(fake.createBlankDocument).toHaveBeenCalledWith("p1");
});

test("New from a run lists finished runs and opens the chosen one in Studio", async () => {
  const fake = client([], [finished("wf_1", "Hotspot map"), finished("wf_2", "Free masks")]);
  render(show(fake));
  const user = userEvent.setup();

  await user.click(await screen.findByRole("button", { name: "New from a run" }));
  const dialog = await screen.findByRole("dialog", { name: "New from a run" });
  expect(fake.listRuns).toHaveBeenCalledWith({ projectId: "p1", status: ["succeeded"], q: undefined });
  await user.click(within(dialog).getByRole("radio", { name: /Free masks/ }));
  await user.click(within(dialog).getByRole("button", { name: "Open in Studio" }));

  expect(await screen.findByText("studio p1 edoc_new")).toBeDefined();
  expect(fake.openWorkflowInStudio.mock.calls[0]?.slice(0, 2)).toEqual(["p1", "wf_2"]);
});

test("with no finished run, New from a run waits and says why", async () => {
  render(show(client([], [])));

  const button = await screen.findByRole("button", { name: "New from a run" });
  expect(await screen.findByText("No finished runs yet")).toBeDefined();
  expect((button as HTMLButtonElement).disabled).toBe(true);
});

test("the page reads in Indonesian", async () => {
  render(show(client([doc("edoc_1", { label: "Kabut", state: "in_review", revision: 3 })]), "id"));

  const card = await screen.findByRole("link", { name: /Kabut/ });
  expect(within(card).getByText("Ditinjau")).toBeDefined();
  expect(screen.getByRole("button", { name: "Baru dari run" })).toBeDefined();
  expect(screen.getByRole("searchbox", { name: "Cari dokumen" })).toBeDefined();
});

test("a document whose time does not parse still shows its revision", async () => {
  render(show(client([doc("edoc_1", { label: "Kabut", revision: 2, updated_at: "" })])));

  const card = await screen.findByRole("link", { name: /Kabut/ });
  expect(card.textContent).toContain("Rev 2");
});
