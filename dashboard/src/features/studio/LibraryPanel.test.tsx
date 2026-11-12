/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { EditorAsset, WorkspaceAsset } from "@/api/control-plane";
import { render } from "@/test-render";

import { LibraryPanel } from "./LibraryPanel";

afterEach(cleanup);

function item(asset_id: string, name: string, kind: WorkspaceAsset["kind"]): WorkspaceAsset {
  return {
    asset_id, name, kind, labels: {}, workspace_id: "ws_a", media_type: "audio/mpeg",
    checksum: `sha256:${asset_id}`, duration_seconds: 1.5, width: null, height: null, has_audio: true,
    created_at: "2026-11-13T00:00:00Z",
  };
}

const copied = { asset_id: "asset_copy", project_id: "p", kind: "audio" } as unknown as EditorAsset;

function client(items: WorkspaceAsset[]) {
  return {
    listLibrary: mock(async () => items),
    addLibraryItemToProject: mock(async (_projectId: string, _assetId: string) => copied),
  };
}

test("lists the workspace library with a kind filter", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx"), item("lib_2", "Yea Boi", "clip")]);
  await act(async () => { render(<LibraryPanel client={api} projectId="p" onAdd={() => {}} />); });
  const region = screen.getByRole("region", { name: "Library" });
  expect(within(region).getByText("Vine Boom")).toBeTruthy();
  fireEvent.click(within(region).getByRole("button", { name: "Clips" }));
  expect(within(region).queryByText("Vine Boom")).toBeNull();
  expect(within(region).getByText("Yea Boi")).toBeTruthy();
});

test("adds an item to the draft", async () => {
  const api = client([item("lib_1", "Vine Boom", "sfx")]);
  const onAdd = mock((_asset: EditorAsset) => {});
  await act(async () => { render(<LibraryPanel client={api} projectId="p" onAdd={onAdd} />); });
  await act(async () => { fireEvent.click(screen.getByRole("button", { name: "Add Vine Boom to the draft" })); });
  expect(api.addLibraryItemToProject).toHaveBeenCalledWith("p", "lib_1");
  expect(onAdd).toHaveBeenCalledWith(copied);
});

test("says the library is empty and points to the Assets page", async () => {
  await act(async () => { render(<LibraryPanel client={client([])} projectId="p" />); });
  expect(screen.getByText(/Your library is empty: upload files on the/)).toBeTruthy();
  expect(screen.getByRole("link", { name: "Assets page" }).getAttribute("href")).toBe("/assets");
});
