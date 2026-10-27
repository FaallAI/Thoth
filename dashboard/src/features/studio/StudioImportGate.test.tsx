/// <reference types="bun-types" />

import { afterEach, expect, mock, spyOn, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  StudioImportRequestError,
  type EditorAsset,
  type StudioImportInventory,
  type StudioImportItem,
} from "@/api/control-plane";
import { LocaleProvider } from "@/lib/locale";
import { StudioImportGate, type StudioImportClient } from "./StudioImportGate";

afterEach(() => cleanup());

const SOURCE_KEY = "b".repeat(64);

const mediaItem = (itemId: string, role: "main" | "footage", order: number, label: string): StudioImportItem => ({
  item_id: itemId,
  mute_audio: false,
  role,
  order,
  label,
  platform: "tiktok",
  media_kind: "video",
  scene_id: `scene_00${order + (role === "main" ? 1 : 2)}`,
  reason: null,
  disposition: "unresolved",
  asset_id: null,
});
const ITEMS: StudioImportItem[] = [
  mediaItem("main_000", "main", 0, "Neon Nights"),
  mediaItem("footage_000", "footage", 0, "City loop"),
  mediaItem("footage_001", "footage", 1, "React closeup"),
  mediaItem("footage_002", "footage", 2, "Skyline drone"),
  mediaItem("footage_003", "footage", 3, "Crowd pan"),
  {
    item_id: "unsupported_000",
    mute_audio: false,
    role: null,
    order: null,
    label: "figures",
    platform: null,
    media_kind: "none",
    scene_id: null,
    reason: "Figures are context, not scenes",
    disposition: "unresolved",
    asset_id: null,
  },
];
const inventoryOf = (documentId: string, revision = 1, items = ITEMS): StudioImportInventory => ({
  document_id: documentId,
  source_key: SOURCE_KEY,
  revision,
  items,
});
const asset = (assetId: string, kind: EditorAsset["kind"], state: EditorAsset["validation_state"] = "ready") =>
  ({
    asset_id: assetId,
    project_id: "project_001",
    kind,
    media_type: kind === "image" ? "image/png" : "video/mp4",
    has_audio: false,
    validation_state: state,
  }) as EditorAsset;

function fakeClient(overrides: Partial<StudioImportClient> = {}) {
  return {
    getStudioImportInventory: mock(async (_projectId: string, documentId: string) => inventoryOf(documentId)),
    resolveStudioImportItem: mock(async () => inventoryOf("edoc_003", 2)),
    uploadEditorAsset: mock(async () => asset("asset_uploaded", "video")),
    listEditorAssets: mock(async () => ({
      assets: [asset("asset_clip", "video"), asset("asset_still", "image"), asset("asset_pending", "video", "pending")],
      next_cursor: null,
    })),
    ...overrides,
  } satisfies StudioImportClient;
}

function renderGate(client = fakeClient(), locale: "en" | "id" = "en", documentId = "edoc_003") {
  const onOpen = mock((_documentId: string) => {});
  const onClose = mock(() => {});
  const view = render(
    <LocaleProvider serverLocale={locale}>
      <StudioImportGate client={client} projectId="project_001" documentId={documentId} onOpen={onOpen} onClose={onClose} />
    </LocaleProvider>,
  );
  return { client, onOpen, onClose, view, user: userEvent.setup() };
}

const inventory = () => screen.findByRole("list", { name: "Source inventory" });
const row = (label: string) => within(screen.getByRole("listitem", { name: label }));

test("the dialog opens the draft's inventory and every item has a way to resolve it", async () => {
  const { client } = renderGate();

  expect(await screen.findByRole("dialog", { name: "Source inventory" })).toBeDefined();
  expect(within(await inventory()).getAllByRole("listitem")).toHaveLength(6);
  expect(client.getStudioImportInventory).toHaveBeenCalledWith("project_001", "edoc_003");
  for (const label of ["Neon Nights", "City loop", "React closeup", "Skyline drone", "Crowd pan"]) {
    expect(row(label).getByRole("button", { name: "Attach…" })).toBeDefined();
    expect(row(label).getByRole("button", { name: "Exclude" })).toBeDefined();
    expect(row(label).getByText("Unresolved")).toBeDefined();
  }
  // A field with no media can only be left out; its reason reads in the chosen language.
  expect(row("figures").getByText("Figures stay as context: people and organisations do not become scenes.")).toBeDefined();
  expect(row("figures").queryByRole("button", { name: "Attach…" }) === null).toBe(true);
  expect(row("figures").getByRole("button", { name: "Exclude" })).toBeDefined();
  expect(screen.getByText("6 of 6 items need a decision before render")).toBeDefined();
});

test("Continue in Studio opens the draft", async () => {
  const { onOpen, user } = renderGate();
  await inventory();

  await user.click(screen.getByRole("button", { name: "Continue in Studio" }));
  expect(onOpen).toHaveBeenCalledWith("edoc_003");
});

test("an exclusion is saved on the draft and stays listed", async () => {
  const excluded = ITEMS.map((item) =>
    item.item_id === "footage_001" ? { ...item, disposition: "excluded" as const } : item,
  );
  const resolveStudioImportItem = mock(async () => inventoryOf("edoc_003", 2, excluded));
  const { user } = renderGate(fakeClient({ resolveStudioImportItem }));
  await inventory();

  await user.click(row("React closeup").getByRole("button", { name: "Exclude" }));

  expect(resolveStudioImportItem).toHaveBeenCalledWith("project_001", "edoc_003", "footage_001", {
    base_revision: 1,
    decision: { kind: "exclude" },
  });
  expect(await row("React closeup").findByText("Excluded")).toBeDefined();
  expect(row("React closeup").queryByRole("button", { name: "Attach…" }) === null).toBe(true);
  expect(screen.getByText("5 of 6 items need a decision before render")).toBeDefined();
});

test("with every item decided the footer says nothing is left", async () => {
  const decided = ITEMS.map((item) => ({ ...item, disposition: "excluded" as const }));
  renderGate(fakeClient({ getStudioImportInventory: mock(async () => inventoryOf("edoc_003", 1, decided)) }));
  await inventory();

  expect(screen.getByText("Every item is decided.")).toBeDefined();
});

test("a ready asset of the item's kind can be attached", async () => {
  const attached = ITEMS.map((item) =>
    item.item_id === "footage_000" ? { ...item, disposition: "attached" as const, asset_id: "asset_clip" } : item,
  );
  const resolveStudioImportItem = mock(async () => inventoryOf("edoc_003", 2, attached));
  const { client, user } = renderGate(fakeClient({ resolveStudioImportItem }));
  await inventory();

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  const choice = (await row("City loop").findByLabelText("Ready asset")) as HTMLSelectElement;
  expect([...choice.options].map((option) => option.value)).toEqual(["asset_clip"]);
  await user.click(row("City loop").getByRole("button", { name: "Attach selected asset" }));

  expect(client.listEditorAssets).toHaveBeenCalledWith("project_001", undefined, 50);
  expect(resolveStudioImportItem).toHaveBeenCalledWith("project_001", "edoc_003", "footage_000", {
    base_revision: 1,
    decision: { kind: "attach_asset", asset_id: "asset_clip" },
  });
  expect(await row("City loop").findByText("Attached")).toBeDefined();
});

test("ready assets beyond the first page are reached one page at a time", async () => {
  const listEditorAssets = mock(async (_projectId: string, cursor?: string, _limit?: number) =>
    cursor
      ? { assets: [asset("asset_late", "video")], next_cursor: null }
      : { assets: [asset("asset_clip", "video"), asset("asset_still", "image")], next_cursor: "page_2" },
  );
  const { user } = renderGate(fakeClient({ listEditorAssets }));
  await inventory();

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  const choice = (await row("City loop").findByLabelText("Ready asset")) as HTMLSelectElement;
  expect([...choice.options].map((option) => option.value)).toEqual(["asset_clip"]);
  await user.click(row("City loop").getByRole("button", { name: "Load more assets" }));

  await waitFor(() => expect([...choice.options].map((option) => option.value)).toEqual(["asset_clip", "asset_late"]));
  expect(listEditorAssets.mock.calls.map((call) => call.slice(1))).toEqual([
    [undefined, 50],
    ["page_2", 50],
  ]);
  expect(row("City loop").queryByRole("button", { name: "Load more assets" }) === null).toBe(true);
});

test("a ready-asset page announces loading and a failure it can retry", async () => {
  let fail: (error: Error) => void = () => {};
  const listEditorAssets = mock(
    (): Promise<{ assets: EditorAsset[]; next_cursor: string | null }> =>
      listEditorAssets.mock.calls.length === 1
        ? new Promise((_resolve, reject) => {
            fail = reject;
          })
        : Promise.resolve({ assets: [asset("asset_clip", "video")], next_cursor: null }),
  );
  const { user } = renderGate(fakeClient({ listEditorAssets }));
  await inventory();

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  expect(row("City loop").getByRole("status").textContent).toContain("Loading ready assets");
  fail(new Error("offline"));

  expect((await row("City loop").findByRole("alert")).textContent).toContain("could not be loaded");
  await user.click(row("City loop").getByRole("button", { name: "Retry loading assets" }));
  expect(await row("City loop").findByLabelText("Ready asset")).toBeDefined();
  expect(row("City loop").queryByRole("alert") === null).toBe(true);
});

test.each([
  ["trim_exceeds_asset", "starts after that asset ends"],
  ["asset_duration_unknown", "length of that asset is unknown"],
  ["main_not_attached", "Attach the main item first"],
  ["no_room_in_reaction_beat", "no room left in the reaction beat"],
])("a source range the asset cannot hold (%s) is stated and leaves the item unresolved", async (code, text) => {
  const resolveStudioImportItem = mock(async () => {
    throw new StudioImportRequestError(422, code);
  });
  const { user } = renderGate(fakeClient({ resolveStudioImportItem }));
  await inventory();

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  await row("City loop").findByLabelText("Ready asset");
  await user.click(row("City loop").getByRole("button", { name: "Attach selected asset" }));

  expect((await screen.findByRole("alert")).textContent).toContain(text);
  expect(row("City loop").getByText("Unresolved")).toBeDefined();
});

test("an uploaded file is attached to the item it was chosen for", async () => {
  const { client, user } = renderGate();
  await inventory();
  const file = new File(["frames"], "city.mp4", { type: "video/mp4" });

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  await user.upload(row("City loop").getByLabelText("Upload file"), file);

  expect(client.uploadEditorAsset).toHaveBeenCalledWith("project_001", file);
  await waitFor(() =>
    expect(client.resolveStudioImportItem).toHaveBeenCalledWith("project_001", "edoc_003", "footage_000", {
      base_revision: 1,
      decision: { kind: "attach_asset", asset_id: "asset_uploaded" },
    }),
  );
});

test("a failed upload keeps the inventory and the open attach choice", async () => {
  const { client, user } = renderGate(
    fakeClient({
      uploadEditorAsset: mock(async () => {
        throw new StudioImportRequestError(413, "upload_too_large");
      }),
    }),
  );
  await inventory();

  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));
  await user.upload(row("City loop").getByLabelText("Upload file"), new File(["x"], "big.mp4", { type: "video/mp4" }));

  expect((await screen.findByRole("alert")).textContent).toContain("too large");
  expect(client.resolveStudioImportItem).toHaveBeenCalledTimes(0);
  expect(row("City loop").getByText("Unresolved")).toBeDefined();
  expect(row("City loop").getByLabelText("Upload file")).toBeDefined();
});

test("a decision on a stale revision refreshes the inventory", async () => {
  const getStudioImportInventory = mock(async (_projectId: string, documentId: string) => inventoryOf(documentId));
  const { user } = renderGate(
    fakeClient({
      getStudioImportInventory,
      resolveStudioImportItem: mock(async () => {
        throw new StudioImportRequestError(409, "document_revision_conflict");
      }),
    }),
  );
  await inventory();

  await user.click(row("Crowd pan").getByRole("button", { name: "Exclude" }));

  expect((await screen.findByRole("alert")).textContent).toContain("changed elsewhere");
  expect(getStudioImportInventory).toHaveBeenCalledTimes(2);
});

test("no local path or asset id reaches the dialog or the console", async () => {
  const attached = ITEMS.map((item) =>
    item.item_id === "main_000" ? { ...item, disposition: "attached" as const, asset_id: "asset_secret_1" } : item,
  );
  const logs = (["log", "info", "warn", "error"] as const).map((level) => spyOn(console, level));
  const { user } = renderGate(fakeClient({ getStudioImportInventory: mock(async () => inventoryOf("edoc_003", 1, attached)) }));
  await inventory();
  await user.click(row("City loop").getByRole("button", { name: "Attach…" }));

  const text = globalThis.document.body.textContent ?? "";
  for (const leak of ["https://", "C:\\", "/mnt/", "asset_secret_1"]) expect(text).not.toContain(leak);
  for (const spy of logs) spy.mockRestore();
});

test("Escape closes the dialog", async () => {
  const { onClose, user } = renderGate();
  await inventory();
  await user.keyboard("{Escape}");
  expect(onClose).toHaveBeenCalledTimes(1);
});

test("while the inventory loads the dialog says so", async () => {
  renderGate(fakeClient({ getStudioImportInventory: mock(() => new Promise<never>(() => {})) }));
  expect(await screen.findByText("Loading the draft's source items…")).toBeDefined();
});

test("a failed open can be retried and a missing draft is worded for itself", async () => {
  let calls = 0;
  renderGate(
    fakeClient({
      getStudioImportInventory: mock(async (_projectId: string, documentId: string) => {
        calls += 1;
        if (calls === 1) throw new StudioImportRequestError(500);
        return inventoryOf(documentId);
      }),
    }),
  );
  await userEvent.setup().click(await screen.findByRole("button", { name: "Try again" }));
  expect(await inventory()).toBeDefined();
  cleanup();

  renderGate(
    fakeClient({
      getStudioImportInventory: mock(async () => {
        throw new StudioImportRequestError(404);
      }),
    }),
    "en",
    "edoc_gone",
  );
  expect(await screen.findByText("This draft is no longer available.")).toBeDefined();
});

test("overlay items show their role and the not-placed reason", async () => {
  const card = (itemId: string, role: "profile_card" | "comment_card" | "slide", label: string) => ({
    ...mediaItem(itemId, "main", 0, label),
    role,
    media_kind: "image" as const,
  });
  const items: StudioImportItem[] = [
    mediaItem("main_000", "main", 0, "Neon Nights"),
    card("slide_000", "slide", "Slide 2"),
    card("profile_card_000", "profile_card", "@creator"),
    {
      ...card("comment_card_003", "comment_card", "@viewer"),
      disposition: "excluded",
      reason: "Not placed: no room in the reaction beat",
    },
  ];
  renderGate(fakeClient({ getStudioImportInventory: mock(async () => inventoryOf("edoc_003", 1, items)) }));
  await inventory();

  const unplaced = screen.getByRole("listitem", { name: "@viewer" });
  expect(unplaced.textContent).toContain("Comment card");
  expect(unplaced.textContent).toContain("Not placed: no room in the reaction beat.");
  expect(screen.getByRole("listitem", { name: "Slide 2" }).textContent).toContain("Slide");
  expect(screen.getByRole("listitem", { name: "@creator" }).textContent).toContain("Profile card");
});

test("style A items show their roles", async () => {
  // Spec 5c-2, G5: the post card, the profile page and the creator's own media.
  const item = (itemId: string, role: StudioImportItem["role"], label: string): StudioImportItem => ({
    ...mediaItem(itemId, "main", 0, label),
    role,
    media_kind: "image",
  });
  const items: StudioImportItem[] = [
    mediaItem("main_000", "main", 0, "Neon Nights"),
    item("post_card_000", "post_card", "Post of @creator"),
    item("profile_page_000", "profile_page", "Page of @creator"),
    item("creator_footage_000", "creator_footage", "Clip of @creator"),
    item("creator_photo_000", "creator_photo", "Photo of @creator"),
  ];
  renderGate(fakeClient({ getStudioImportInventory: mock(async () => inventoryOf("edoc_003", 1, items)) }));
  await inventory();

  const labels: [string, string][] = [
    ["Post of @creator", "Post card"],
    ["Page of @creator", "Profile page"],
    ["Clip of @creator", "Creator footage"],
    ["Photo of @creator", "Creator photo"],
  ];
  for (const [name, label] of labels) {
    expect(screen.getByRole("listitem", { name }).textContent).toContain(label);
  }
});

test("the inventory reads in Indonesian", async () => {
  renderGate(fakeClient(), "id");

  expect(await screen.findByRole("dialog", { name: "Inventaris sumber" })).toBeDefined();
  const list = await screen.findByRole("list", { name: "Inventaris sumber" });
  const main = within(within(list).getByRole("listitem", { name: "Neon Nights" }));
  expect(main.getByText("Utama")).toBeDefined();
  expect(main.getByText("Belum diputuskan")).toBeDefined();
  expect(main.getByRole("button", { name: "Kecualikan" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Lanjut di Studio" })).toBeDefined();
});
