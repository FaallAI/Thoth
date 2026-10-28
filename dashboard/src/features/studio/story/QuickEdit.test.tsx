/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { EditorAsset, StudioMaterial, StudioMaterials } from "@/api/control-plane";
import { render } from "@/test-render";

import type { EditorAction } from "../editor_state";
import { QuickEdit } from "./QuickEdit";
import { computeBeats } from "./story_beats";
import { storyDocument, storyInventory } from "./story-test-fixtures";

afterEach(cleanup);

const card = (item_id: string, author: string, likes: number, asset_id?: string): StudioMaterial => ({
  item_id,
  role: "comment_card",
  label: `@${author}`,
  media_kind: "image",
  disposition: asset_id ? "attached" : "excluded",
  asset_id,
  author,
  likes,
});
const materials: StudioMaterials = {
  document_id: "edoc_story",
  provenance_available: true,
  items: [
    card("comment_card_000", "rizkyptk", 12, "asset_clip_comment_card_000"),
    card("comment_card_001", "dewiayu_", 4, "asset_clip_comment_card_001"),
    card("comment_card_003", "bagas.wp", 9),
  ],
  figures: [],
};
const fresh = { asset_id: "asset_bagas", kind: "image", project_id: "project_001", validation_state: "ready" } as EditorAsset;

function mount({ items = materials, locale = "en" as "en" | "id", playhead = 0 } = {}) {
  const dispatch = mock((_action: EditorAction) => {});
  const attach = mock(async () => fresh);
  const document = storyDocument();
  render(
    <QuickEdit
      document={document}
      beats={computeBeats(document, storyInventory())}
      materials={items}
      revision={3}
      playheadFrame={playhead}
      dispatch={dispatch}
      attachMaterial={attach}
      captions={<p>Caption editor</p>}
    />,
    { locale },
  );
  return { dispatch, attach };
}

test("quick edit offers the hook text, captions and the comment card swap", () => {
  mount();

  expect(screen.getByRole("heading", { name: "Quick edit · Rev 3" })).toBeDefined();
  expect((screen.getByLabelText("Hook text") as HTMLInputElement).value).toBe("clip_hook");
  expect(screen.getByText("Caption editor")).toBeDefined();
  expect(screen.getByRole("button", { name: /Swap comment card/ }).textContent).toContain("Reactions · 2 cards");
  expect(screen.getByText("Beats and timeline editing need a larger screen")).toBeDefined();
});

test("editing the hook text commits replace_text", () => {
  const { dispatch } = mount();

  const hook = screen.getByLabelText("Hook text");
  fireEvent.change(hook, { target: { value: "Udara Kalteng tembus ISPU 1.533" } });
  fireEvent.blur(hook);

  expect(dispatch.mock.calls[0]![0]).toMatchObject({
    type: "commit_operations",
    operations: [{ kind: "replace_text", clip_id: "clip_hook", field: "heading", value: "Udara Kalteng tembus ISPU 1.533" }],
  });
});

test("the sheet lists the run's comment cards and marks the one in use", () => {
  mount();

  fireEvent.click(screen.getByRole("button", { name: /Swap comment card/ }));
  const sheet = screen.getByRole("dialog", { name: "Swap comment card 1" });
  const options = within(sheet).getAllByRole("radio");
  expect(options.map((option) => option.closest("label")?.textContent)).toEqual([
    expect.stringContaining("@rizkyptk"),
    expect.stringContaining("@dewiayu_"),
    expect.stringContaining("@bagas.wp"),
  ]);
  expect((options[0] as HTMLInputElement).checked).toBe(true);
  expect(options[0]!.closest("label")?.getAttribute("aria-current")).toBe("true");
  expect(within(sheet).getByText("12 likes")).toBeDefined();
});

test("the card under the playhead is the one swapped", () => {
  mount({ playhead: 110 });

  fireEvent.click(screen.getByRole("button", { name: /Swap comment card/ }));
  expect(screen.getByRole("dialog", { name: "Swap comment card 2" })).toBeDefined();
});

test("Swap card attaches the chosen card and replaces the clip's media", async () => {
  const { dispatch, attach } = mount();

  fireEvent.click(screen.getByRole("button", { name: /Swap comment card/ }));
  fireEvent.click(screen.getByRole("radio", { name: /@bagas.wp/ }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Swap card" })));

  expect(attach).toHaveBeenCalledWith("comment_card_003");
  expect(dispatch.mock.calls.map(([action]) => action.type)).toEqual(["assets_loaded", "commit_operations"]);
  expect(dispatch.mock.calls[1]![0]).toMatchObject({
    operations: [{ kind: "replace_clip_asset", clip_id: "clip_comment_card_000", asset_id: "asset_bagas" }],
  });
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("a run with no comment cards has no swap row", () => {
  mount({ items: { ...materials, items: [] } });

  expect(screen.queryByRole("button", { name: /Swap comment card/ })).toBeNull();
});

test("quick edit speaks Indonesian", () => {
  mount({ locale: "id" });

  expect(screen.getByRole("heading", { name: "Edit cepat · Rev 3" })).toBeDefined();
});

test("a swap that cannot attach the card says so and keeps the sheet open", async () => {
  const dispatch = mock((_action: EditorAction) => {});
  const document = storyDocument();
  render(
    <QuickEdit
      document={document}
      beats={computeBeats(document, storyInventory())}
      materials={materials}
      revision={3}
      playheadFrame={0}
      dispatch={dispatch}
      attachMaterial={mock(async () => {
        throw new Error("offline");
      })}
      captions={null}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /Swap comment card/ }));
  fireEvent.click(screen.getByRole("radio", { name: /@bagas.wp/ }));
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Swap card" })));

  expect(within(screen.getByRole("dialog")).getByRole("alert").textContent).toContain("could not be swapped");
  expect(dispatch).not.toHaveBeenCalled();
});
