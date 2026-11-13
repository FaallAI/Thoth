/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import { StudioImportRequestError, type WorkspaceAsset } from "@/api/control-plane";
import { render } from "@/test-render";

import { AssetsPage } from "./AssetsPage";

afterEach(cleanup);

function item(asset_id: string, name: string, kind: WorkspaceAsset["kind"], labels: Record<string, unknown> = {}): WorkspaceAsset {
  return {
    asset_id, name, kind, labels, workspace_id: "ws_a", media_type: kind === "clip" ? "video/mp4" : kind === "image" ? "image/png" : "audio/mpeg",
    checksum: `sha256:${asset_id}`, duration_seconds: 1.5, width: null, height: null, has_audio: true,
    created_at: "2026-11-13T00:00:00Z",
  };
}

function client(items: WorkspaceAsset[] = []) {
  return {
    listLibrary: mock(async () => items),
    uploadLibraryItem: mock(async (file: File) => item(`lib_${file.name.replace(/\W/g, "_")}`, file.name.replace(/\.\w+$/, ""), "sfx")),
    updateLibraryItem: mock(async (assetId: string, patch: { name?: string }) => ({ ...items.find((entry) => entry.asset_id === assetId)!, ...patch })),
    deleteLibraryItem: mock(async (_assetId: string) => {}),
    libraryMediaUrl: (assetId: string) => `/api/v1/library/${assetId}/media`,
  };
}

test("uploads every picked file and keeps going past a refused one", async () => {
  const api = client();
  api.uploadLibraryItem.mockImplementation(async (file: File) => {
    if (file.name === "notes.txt") throw new StudioImportRequestError(415, "unsupported_media_type");
    return item(`lib_${file.name.replace(/\W/g, "_")}`, file.name.replace(/\.\w+$/, ""), "sfx");
  });
  await act(async () => { render(<AssetsPage client={api as never} />); });
  const files = [
    new File(["a"], "boom.mp3", { type: "audio/mpeg" }),
    new File(["b"], "notes.txt", { type: "text/plain" }),
    new File(["c"], "yeah.mp3", { type: "audio/mpeg" }),
  ];
  await act(async () => { fireEvent.change(screen.getByLabelText("Upload files"), { target: { files } }); });

  expect(api.uploadLibraryItem).toHaveBeenCalledTimes(3);
  const library = screen.getByRole("list", { name: "Library" });
  expect(within(library).getAllByRole("listitem")).toHaveLength(2);
  const uploads = screen.getByRole("list", { name: "Uploads" });
  expect(within(uploads).getByText("notes.txt")).toBeTruthy();
  expect(within(uploads).getByText("This file type is not supported.")).toBeTruthy();
});

test("filters by kind and searches names and labels", async () => {
  const api = client([
    item("lib_1", "Vine Boom", "sfx", { category: "meme" }),
    item("lib_2", "Yea Boi", "clip"),
    item("lib_3", "Calm piano", "backsound", { mood: "sad" }),
  ]);
  await act(async () => { render(<AssetsPage client={api as never} />); });
  const names = () => within(screen.getByRole("list", { name: "Library" })).getAllByRole("listitem").map((row) => row.getAttribute("data-name"));

  expect(names()).toEqual(["Vine Boom", "Yea Boi", "Calm piano"]);
  fireEvent.click(screen.getByRole("button", { name: "Clips" }));
  expect(names()).toEqual(["Yea Boi"]);
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  fireEvent.change(screen.getByLabelText("Search assets"), { target: { value: "sad" } });
  expect(names()).toEqual(["Calm piano"]);
});

test("renames an item inline", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx")]);
  await act(async () => { render(<AssetsPage client={api as never} />); });
  const name = screen.getByLabelText("Name of Vine Boom");
  fireEvent.change(name, { target: { value: "Boom" } });
  await act(async () => { fireEvent.blur(name); });
  expect(api.updateLibraryItem).toHaveBeenCalledWith("lib_1", { name: "Boom" });
});

test("deletes the selected items after confirming", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx"), item("lib_2", "Yea Boi", "clip"), item("lib_3", "Keep", "sfx")]);
  await act(async () => { render(<AssetsPage client={api as never} />); });
  fireEvent.click(screen.getByLabelText("Select Vine Boom"));
  fireEvent.click(screen.getByLabelText("Select Yea Boi"));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete selected (2)" })); });
  expect(api.deleteLibraryItem).not.toHaveBeenCalled();
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete assets" })); });

  expect(api.deleteLibraryItem.mock.calls.map((call) => call[0])).toEqual(["lib_1", "lib_2"]);
  const rows = within(screen.getByRole("list", { name: "Library" })).getAllByRole("listitem");
  expect(rows.map((row) => row.getAttribute("data-name"))).toEqual(["Keep"]);
});

test("says what can be uploaded when the library is empty", async () => {
  await act(async () => { render(<AssetsPage client={client() as never} />); });
  expect(screen.getByText(/Your library is empty/)).toBeTruthy();
});

test("says the library is unavailable when it cannot be listed", async () => {
  const api = client();
  api.listLibrary.mockImplementation(async () => { throw new StudioImportRequestError(503, "library_unavailable"); });
  await act(async () => { render(<AssetsPage client={api as never} />); });
  expect(screen.getByText("The asset library is unavailable right now.")).toBeTruthy();
});

test("deletes only the selected items the filter still shows", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx"), item("lib_2", "Yea Boi", "clip")]);
  await act(async () => { render(<AssetsPage client={api as never} />); });
  fireEvent.click(screen.getByLabelText("Select Vine Boom"));
  fireEvent.click(screen.getByLabelText("Select Yea Boi"));
  fireEvent.click(screen.getByRole("button", { name: "Clips" }));
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete selected (1)" })); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Delete assets" })); });

  expect(api.deleteLibraryItem.mock.calls.map((call) => call[0])).toEqual(["lib_2"]);
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  const rows = within(screen.getByRole("list", { name: "Library" })).getAllByRole("listitem");
  expect(rows.map((row) => row.getAttribute("data-name"))).toEqual(["Vine Boom"]);
});

test("offers only the kinds that fit each item's media", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx"), item("lib_2", "Yea Boi", "clip"), item("lib_3", "Paper", "image")]);
  await act(async () => { render(<AssetsPage client={api as never} />); });
  const options = (name: string) =>
    within(screen.getByLabelText(`Kind of ${name}`)).getAllByRole("option").map((option) => option.textContent);

  expect(options("Vine Boom")).toEqual(["SFX", "Backsound"]);
  expect(options("Yea Boi")).toEqual(["Clips"]);
  expect(options("Paper")).toEqual(["Images"]);
});

test("says when a change was not saved", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx")]);
  api.updateLibraryItem.mockImplementation(async () => { throw new StudioImportRequestError(422, "kind_mismatch"); });
  await act(async () => { render(<AssetsPage client={api as never} />); });
  await act(async () => {
    fireEvent.change(screen.getByLabelText("Kind of Vine Boom"), { target: { value: "backsound" } });
  });
  expect(screen.getByText("The change was not saved. Try again.")).toBeTruthy();
});
