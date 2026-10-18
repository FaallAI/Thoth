/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useParams } from "react-router";

import { StudioDocumentsPage } from "./StudioDocumentsPage";

afterEach(cleanup);

function Opened() {
  const { projectId, documentId } = useParams();
  return <p>{`studio ${projectId} ${documentId}`}</p>;
}

test("lists drafts and opens one by URL", async () => {
  const client = {
    listEditDocuments: mock(async () => ({
      items: [{ document_id: "doc_1", revision: 3, updated_at: "2026-10-18T00:00:00Z", label: "Kucing", imported: true }],
      next_cursor: null,
    })),
  };
  render(
    <MemoryRouter initialEntries={["/studio"]}>
      <Routes>
        <Route path="/studio" element={<StudioDocumentsPage client={client} projectId="p1" />} />
        <Route path="/studio/:projectId/:documentId" element={<Opened />} />
      </Routes>
    </MemoryRouter>,
  );
  await userEvent.setup().click(await screen.findByRole("button", { name: /Kucing/ }));
  expect(await screen.findByText("studio p1 doc_1")).toBeDefined();
});

test("an empty project says how to start a draft", async () => {
  const client = { listEditDocuments: mock(async () => ({ items: [], next_cursor: null })) };
  render(<MemoryRouter><StudioDocumentsPage client={client} projectId="p1" /></MemoryRouter>);
  expect(
    await screen.findByText("No Studio drafts in this project yet. Open a Content Set in Studio to start one."),
  ).toBeDefined();
});

test("more drafts load on request", async () => {
  const item = (id: string) => ({ document_id: id, revision: 1, updated_at: "", label: id, imported: false });
  const client = {
    listEditDocuments: mock(async (_project: string, cursor?: string) =>
      cursor ? { items: [item("doc_b")], next_cursor: null } : { items: [item("doc_a")], next_cursor: "c1" },
    ),
  };
  render(<MemoryRouter><StudioDocumentsPage client={client} projectId="p1" /></MemoryRouter>);
  await userEvent.setup().click(await screen.findByRole("button", { name: "Load more" }));
  expect(await screen.findByRole("button", { name: /doc_b/ })).toBeDefined();
});
