/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { render } from "@/test-render";

import type { EditorAsset, EditorAssetPage } from "@/api/control-plane";
import { ASSET_PAGE_LIMIT, AssetLibrary } from "./AssetLibrary";

afterEach(cleanup);

const asset = (overrides: Partial<EditorAsset> = {}): EditorAsset => ({
  asset_id: "asset_video",
  project_id: "project_001",
  kind: "video",
  media_type: "video/mp4",
  has_audio: true,
  validation_state: "ready",
  duration_in_frames: 120,
  ...overrides,
});

const page = (overrides: Partial<EditorAssetPage> = {}): EditorAssetPage => ({
  assets: [asset(), asset({ asset_id: "asset_pending", validation_state: "pending" })],
  next_cursor: "cursor_2",
  ...overrides,
});

function mount(
  listEditorAssets: ReturnType<typeof mock>,
  createEditorPreviewCapability: ReturnType<typeof mock> = mock(async () => ({
    preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
    expires_at: "2026-09-20T00:00:00Z",
  })),
  generationRef = { current: 0 },
) {
  const added: EditorAsset[] = [];
  const sources: [string, string][] = [];
  const loaded: EditorAsset[][] = [];
  render(
    <AssetLibrary
      client={{
        listEditorAssets: listEditorAssets as never,
        createEditorPreviewCapability: createEditorPreviewCapability as never,
      }}
      projectId="project_001"
      generationRef={generationRef}
      onAssets={(assets) => loaded.push(assets)}
      onAdd={(value) => added.push(value)}
      onPreviewSource={(assetId, url) => sources.push([assetId, url])}
    />,
  );
  return { added, sources, loaded, createEditorPreviewCapability, generationRef };
}

test("loads one bounded page and shows only assets that are ready", async () => {
  const listEditorAssets = mock(async () => page());
  const { loaded } = mount(listEditorAssets);

  expect(await screen.findByText(/asset_video/)).toBeDefined();
  expect(listEditorAssets).toHaveBeenCalledWith("project_001", undefined, ASSET_PAGE_LIMIT);
  expect(ASSET_PAGE_LIMIT).toBeLessThanOrEqual(50);
  expect(screen.queryByText(/asset_pending/)).toBeNull();
  // Pending assets still reach the reducer: operations resolve against them.
  expect(loaded[0]?.map((value) => value.asset_id)).toEqual(["asset_video", "asset_pending"]);
});

test("asks for the next page only when the reader asks for it", async () => {
  let call = 0;
  const listEditorAssets = mock(async () =>
    call++ === 0
      ? page({ assets: [asset()], next_cursor: "cursor_2" })
      : page({ assets: [asset({ asset_id: "asset_second" })], next_cursor: null }),
  );
  mount(listEditorAssets);

  fireEvent.click(await screen.findByRole("button", { name: "Load more assets" }));
  await waitFor(() => expect(listEditorAssets).toHaveBeenCalledTimes(2));
  expect(listEditorAssets).toHaveBeenLastCalledWith("project_001", "cursor_2", ASSET_PAGE_LIMIT);
});

test("adds a ready asset to the timeline", async () => {
  const { added } = mount(mock(async () => page({ next_cursor: null })));
  fireEvent.click(await screen.findByRole("button", { name: "Add asset_video to timeline" }));
  expect(added.map((value) => value.asset_id)).toEqual(["asset_video"]);
});

test("requests a preview capability on demand and never shows a locator", async () => {
  const { sources, createEditorPreviewCapability } = mount(mock(async () => page()));
  await screen.findByText(/asset_video/);
  expect(createEditorPreviewCapability).toHaveBeenCalledTimes(0);

  fireEvent.click(screen.getByRole("button", { name: "Preview asset_video" }));
  await waitFor(() => expect(sources).toHaveLength(1));
  expect(sources[0]).toEqual([
    "asset_video",
    "/api/v1/projects/project_001/editor-assets/asset_video/preview",
  ]);
  expect(document.body.textContent).not.toContain("editor-assets");
});

test("drops a capability that arrives after the document moved on", async () => {
  let release: (value: { preview_url: string; expires_at: string }) => void = () => {};
  const capability = mock(
    () =>
      new Promise<{ preview_url: string; expires_at: string }>((resolve) => {
        release = resolve;
      }),
  );
  const generationRef = { current: 0 };
  const { sources } = mount(mock(async () => page()), capability, generationRef);

  fireEvent.click(await screen.findByRole("button", { name: "Preview asset_video" }));
  generationRef.current += 1;
  release({ preview_url: "/api/v1/projects/p/editor-assets/a/preview", expires_at: "2026-09-20" });

  await waitFor(() => expect(capability).toHaveBeenCalledTimes(1));
  expect(sources).toEqual([]);
});

test("explains an unavailable library and retries on request", async () => {
  const listEditorAssets = mock(async () => {
    throw new Error("offline");
  });
  mount(listEditorAssets);

  expect((await screen.findByRole("alert")).textContent).toContain("Assets are unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Retry loading assets" }));
  await waitFor(() => expect(listEditorAssets).toHaveBeenCalledTimes(2));
});

test("overlapping continuation pages render one row per asset", async () => {
  let call = 0;
  const listEditorAssets = mock(async () =>
    call++ === 0
      ? page({ assets: [asset({ asset_id: "asset_a" }), asset({ asset_id: "asset_b" })] })
      : page({
          assets: [
            asset({ asset_id: "asset_b", duration_in_frames: 240 }),
            asset({ asset_id: "asset_c" }),
          ],
          next_cursor: null,
        }),
  );
  const { added } = mount(listEditorAssets);

  fireEvent.click(await screen.findByRole("button", { name: "Load more assets" }));
  await screen.findByText("asset_c");

  expect(screen.getAllByText(/^asset_[abc]$/).map((row) => row.textContent)).toEqual([
    "asset_a",
    "asset_b",
    "asset_c",
  ]);
  expect(screen.getAllByRole("button", { name: "Add asset_b to timeline" })).toHaveLength(1);
  // The newest page wins for an asset both pages describe.
  expect(screen.getByText(/240f/)).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "Add asset_b to timeline" }));
  expect(added.map((value) => value.asset_id)).toEqual(["asset_b"]);
});

test("asset rows name assets, never by id, and number repeated names", async () => {
  // Studio shell v2 (spec 2026-11-01, goal 4): a row says what the asset is, never its id.
  render(
    <AssetLibrary
      client={{
        listEditorAssets: mock(async () =>
          page({ assets: [asset(), asset({ asset_id: "asset_second" }), asset({ asset_id: "asset_voice", kind: "audio" })], next_cursor: null }),
        ) as never,
        createEditorPreviewCapability: mock(async () => ({ preview_url: "/x", expires_at: "2026-09-20T00:00:00Z" })) as never,
      }}
      projectId="project_001"
      generationRef={{ current: 0 }}
      onAssets={() => {}}
      onAdd={() => {}}
      onPreviewSource={() => {}}
      describe={(item) =>
        item.asset_id === "asset_voice"
          ? { label: "Narration · Main", detail: "Voice · 14.2 s" }
          : { label: "Upload · Video", detail: "Video · 4.0 s" }
      }
    />,
  );

  expect(await screen.findByRole("button", { name: "Add Narration · Main to timeline" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Add Upload · Video to timeline" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Add Upload · Video · 2 to timeline" })).toBeDefined();
  expect(screen.getAllByText("Video · 4.0 s")).toHaveLength(2);
  expect(screen.queryByText(/asset_/)).toBeNull();
});

test("without an add action the rows offer preview only", async () => {
  // Final review, Important 3: a view-only Timeline (below 1024) adds nothing to the draft.
  render(
    <AssetLibrary
      client={{ listEditorAssets: mock(async () => page({ next_cursor: null })) as never, createEditorPreviewCapability: mock(async () => ({ preview_url: "/x", expires_at: "2026-09-20T00:00:00Z" })) as never }}
      projectId="project_001"
      generationRef={{ current: 0 }}
      onAssets={() => {}}
      onPreviewSource={() => {}}
    />,
  );

  expect(await screen.findByRole("button", { name: "Preview asset_video" })).toBeDefined();
  expect(screen.queryByRole("button", { name: /to timeline$/ })).toBeNull();
});

test("a row shows its picture or kind icon, and other drafts' uploads list last", async () => {
  // e2e audit 2026-11-02, finding 6 and the minor on "Upload · Image" rows listing first.
  const assets = [
    asset({ asset_id: "asset_other", kind: "image" }),
    asset({ asset_id: "asset_main", kind: "image" }),
    asset({ asset_id: "asset_voice", kind: "audio" }),
  ];
  render(
    <AssetLibrary
      client={{ listEditorAssets: mock(async () => ({ assets, next_cursor: null })), createEditorPreviewCapability: mock(async () => ({ preview_url: "", expires_at: "" })) }}
      projectId="project_001"
      generationRef={{ current: 0 }}
      onAssets={() => {}}
      onPreviewSource={() => {}}
      previews={{ asset_main: "/preview/main" }}
      describe={(item) => ({
        label: item.asset_id,
        detail: item.kind,
        kind: item.asset_id === "asset_other" ? "upload" : "video",
      })}
    />,
  );

  const rows = await screen.findAllByRole("listitem");
  expect(rows.map((row) => row.querySelector("span.font-medium")?.textContent)).toEqual(["asset_main", "asset_voice", "asset_other"]);
  expect(rows[0]!.querySelector("img")?.getAttribute("src")).toBe("/preview/main");
  expect(rows[1]!.querySelector("svg")).not.toBeNull();
});

test("the library speaks Indonesian", async () => {
  const client = {
    listEditorAssets: mock(async () => ({ assets: [asset()], next_cursor: null })),
    createEditorPreviewCapability: mock(async () => ({ preview_url: "/p", expires_at: "2099-01-01T00:00:00Z" })),
  };
  render(
    <AssetLibrary client={client as never} projectId="p" generationRef={{ current: 0 }} onAssets={() => {}} onPreviewSource={() => {}} onAdd={() => {}} describe={() => ({ label: "Klip", detail: "Video" })} />,
    { locale: "id" },
  );

  expect(await screen.findByRole("button", { name: "Tambahkan Klip ke timeline" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Pratinjau Klip" })).toBeDefined();
  expect(screen.getByRole("heading", { name: "Aset" })).toBeDefined();
});

// Found by the e2e audit: an older draft's own assets sat two "Load more" presses behind newer ones.
const pagedList = () =>
  mock(async (_projectId: string, cursor?: string) =>
    cursor === "cursor_2"
      ? page({ assets: [asset({ asset_id: "asset_mine" })], next_cursor: "cursor_3" })
      : cursor === "cursor_3"
        ? page({ assets: [asset({ asset_id: "asset_last" })], next_cursor: null })
        : page({ assets: [asset({ asset_id: "asset_new" })], next_cursor: "cursor_2" }),
  );

function mountWanted(listEditorAssets: ReturnType<typeof mock>, extra: Record<string, unknown>) {
  render(
    <AssetLibrary
      client={{
        listEditorAssets: listEditorAssets as never,
        createEditorPreviewCapability: mock(async () => ({ preview_url: "", expires_at: "" })) as never,
      }}
      projectId="project_001"
      generationRef={{ current: 0 }}
      onAssets={() => {}}
      onAdd={() => {}}
      onPreviewSource={() => {}}
      {...extra}
    />,
  );
}

test("write-audit: pages load by themselves until the draft's own assets are in, then stop", async () => {
  const listEditorAssets = pagedList();
  mountWanted(listEditorAssets, { wanted: ["asset_mine"] });

  expect(await screen.findByText(/asset_mine/)).toBeDefined();
  await waitFor(() => expect(listEditorAssets).toHaveBeenCalledTimes(2));
  await new Promise((done) => setTimeout(done, 20));
  expect(listEditorAssets).toHaveBeenCalledTimes(2);
  expect(screen.getByRole("button", { name: "Load more assets" })).toBeDefined();
});

test("write-audit: an asset the project no longer lists ends at the last page", async () => {
  const listEditorAssets = pagedList();
  mountWanted(listEditorAssets, { wanted: ["asset_gone"] });

  await waitFor(() => expect(listEditorAssets).toHaveBeenCalledTimes(3));
  await new Promise((done) => setTimeout(done, 20));
  expect(listEditorAssets).toHaveBeenCalledTimes(3);
});

test("write-audit: a failed page stops the search and offers the retry", async () => {
  let call = 0;
  const listEditorAssets = mock(async () => {
    call += 1;
    if (call === 2) throw new Error("down");
    return page({ assets: [asset({ asset_id: "asset_new" })], next_cursor: "cursor_2" });
  });
  mountWanted(listEditorAssets, { wanted: ["asset_mine"] });

  expect(await screen.findByRole("button", { name: "Retry loading assets" })).toBeDefined();
  await new Promise((done) => setTimeout(done, 20));
  expect(listEditorAssets).toHaveBeenCalledTimes(2);
});

// Found by the write audit: a draft with no run behind it had no way to get media.
test("write-audit: an uploaded file joins the list and the reducer's assets", async () => {
  const uploaded = asset({ asset_id: "asset_uploaded" });
  const upload = mock(async () => uploaded);
  const loaded: EditorAsset[][] = [];
  mountWanted(mock(async () => page({ assets: [], next_cursor: null })), {
    upload,
    onAssets: (assets: EditorAsset[]) => loaded.push(assets),
  });
  const file = new File(["x"], "clip.mp4", { type: "video/mp4" });

  fireEvent.change(await screen.findByLabelText("Upload file"), { target: { files: [file] } });

  expect(await screen.findByText(/asset_uploaded/)).toBeDefined();
  expect(upload).toHaveBeenCalledWith(file);
  expect(loaded.at(-1)?.[0]?.asset_id).toBe("asset_uploaded");
});

test("write-audit: a refused upload says why and leaves the list alone", async () => {
  const upload = mock(async () => {
    throw new Error("nope");
  });
  mountWanted(mock(async () => page({ assets: [], next_cursor: null })), { upload });
  const file = new File(["x"], "clip.mp4", { type: "video/mp4" });

  fireEvent.change(await screen.findByLabelText("Upload file"), { target: { files: [file] } });

  expect((await screen.findByRole("alert")).textContent).toContain("The upload failed");
});

test("write-audit: a view-only library offers no upload", async () => {
  mountWanted(mock(async () => page({ assets: [], next_cursor: null })), { onAdd: undefined, upload: undefined });
  await screen.findByText("No ready assets yet");
  expect(screen.queryByLabelText("Upload file")).toBeNull();
});

// Tier 2 (spec 2026-11-08 §6): find an asset, and drag it onto a lane.
const twoKinds = () =>
  mock(async () =>
    page({
      assets: [asset(), asset({ asset_id: "asset_music", kind: "audio", media_type: "audio/mpeg", has_audio: true })],
      next_cursor: null,
    }),
  );

test("search narrows the rows by name", async () => {
  mount(twoKinds());
  await screen.findByText(/asset_music/);
  fireEvent.change(screen.getByRole("searchbox", { name: "Search assets" }), { target: { value: "MUSIC" } });
  expect(screen.queryByText(/asset_video/)).toBeNull();
  expect(screen.getByText(/asset_music/)).toBeDefined();
});

test("the Audio filter shows audio only", async () => {
  mount(twoKinds());
  await screen.findByText(/asset_music/);
  fireEvent.click(screen.getByRole("button", { name: "Audio" }));
  expect(screen.getByRole("button", { name: "Audio" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.queryByText(/asset_video/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "All" }));
  expect(screen.getByText(/asset_video/)).toBeDefined();
});

test("a row carries its asset when dragged", async () => {
  mount(twoKinds());
  const row = (await screen.findByText(/asset_video/)).closest("li")!;
  expect(row.getAttribute("draggable")).toBe("true");
  const setData = mock((_type: string, _value: string) => {});
  fireEvent.dragStart(row, { dataTransfer: { setData, effectAllowed: "" } });
  expect(setData).toHaveBeenCalledWith("application/x-thoth-asset", "asset_video");
});

// Side-agent note 2026-11-09 (operator: "Pesan jujur + muat lagi"): search and the filter see the
// loaded pages only, so an empty result says so instead of "no assets", and offers the next page.
test("a search with no match says what it searched and offers the next page", async () => {
  mount(mock(async () => page({ assets: [asset(), asset({ asset_id: "asset_music", kind: "audio" })], next_cursor: "cursor_2" })));
  await screen.findByText(/asset_music/);
  fireEvent.change(screen.getByRole("searchbox", { name: "Search assets" }), { target: { value: "zzz" } });
  expect(screen.getByText("No match among the 2 assets loaded so far. Load more to look further.")).toBeDefined();
  expect(screen.queryByText("No ready assets yet")).toBeNull();
  expect(screen.getByRole("button", { name: "Load more assets" })).toBeDefined();
});

test("a search with no match when everything is loaded says so plainly", async () => {
  mount(twoKinds());
  await screen.findByText(/asset_music/);
  fireEvent.click(screen.getByRole("button", { name: "Image" }));
  expect(screen.getByText("No match among the 2 assets loaded.")).toBeDefined();
  expect(screen.queryByText("No ready assets yet")).toBeNull();
});
