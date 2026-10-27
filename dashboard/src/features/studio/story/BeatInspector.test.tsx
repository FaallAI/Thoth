/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { EditorAsset, StudioMaterials } from "@/api/control-plane";
import { render } from "@/test-render";

import type { EditorAction } from "../editor_state";
import { BeatInspector } from "./BeatInspector";
import { computeBeats } from "./story_beats";
import { storyDocument, storyInventory } from "./story-test-fixtures";

afterEach(cleanup);

const inventory = storyInventory().map((entry) =>
  entry.item_id === "comment_card_001" ? { ...entry, reading_seconds: 3.2 } : entry,
);
const beats = computeBeats(storyDocument(), inventory);
const materials: StudioMaterials = {
  document_id: "edoc_story",
  provenance_available: true,
  items: [
    { item_id: "comment_card_000", role: "comment_card", label: "@viewer", media_kind: "image", disposition: "attached", asset_id: "asset_clip_comment_card_000" },
    { item_id: "comment_card_003", role: "comment_card", label: "@late", media_kind: "image", disposition: "excluded" },
    { item_id: "footage_000", role: "footage", label: "Banjir", media_kind: "video", disposition: "attached" },
  ],
  figures: [],
};
const fresh = { asset_id: "asset_late", kind: "image", width: 1080, height: 400, project_id: "project_001", validation_state: "ready" } as EditorAsset;

function mount(id: string, { locale = "en" as "en" | "id", attach = mock(async () => fresh) } = {}) {
  const dispatch = mock((_action: EditorAction) => {});
  render(
    <BeatInspector
      beat={beats.find((beat) => beat.id === id)!}
      beats={beats}
      document={storyDocument()}
      inventory={inventory}
      materials={materials}
      dispatch={dispatch}
      attachMaterial={attach}
    />,
    { locale },
  );
  const committed = () =>
    dispatch.mock.calls
      .map(([action]) => action)
      .filter((action): action is Extract<EditorAction, { type: "commit_operations" }> => action.type === "commit_operations")
      .map((action) => action.operations.map((operation) => [operation.kind, "clip_id" in operation ? operation.clip_id : ""]));
  return { dispatch, attach, committed };
}

test("the header names the beat, its place, its length and what is missing", () => {
  mount("reactions");

  expect(screen.getByRole("heading", { name: "Reactions" })).toBeDefined();
  expect(screen.getByText("Beat 3 of 4 · 2.7 s · 2 materials · 1 missing")).toBeDefined();
});

test("shown cards move, and leave the beat", () => {
  const { committed } = mount("reactions");

  fireEvent.click(screen.getByRole("button", { name: "Move @viewer later" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove comment_card_001 from the beat" }));

  expect(committed()).toEqual([
    [["move_clip", "clip_comment_card_001"], ["move_clip", "clip_comment_card_000"]],
    [["set_clip_hidden", "clip_comment_card_001"]],
  ]);
});

test("each card's length is set for every card, with the reading check", () => {
  const { committed } = mount("reactions");

  expect(screen.getByText("Reading speed 15 chars/s · longest card needs 3.2 s")).toBeDefined();
  const each = screen.getByLabelText("Each card (seconds)");
  fireEvent.change(each, { target: { value: "3" } });
  fireEvent.blur(each);

  expect(committed()).toEqual([[["trim_clip_end", "clip_comment_card_000"], ["trim_clip_end", "clip_comment_card_001"]]]);
});

test("position, motion and emphasis apply to every card of the beat", () => {
  const { committed } = mount("reactions");

  fireEvent.click(screen.getByRole("button", { name: "Lower third" }));
  fireEvent.click(screen.getByRole("button", { name: "Slow zoom" }));
  fireEvent.click(screen.getByRole("switch", { name: "Highlight box" }));

  expect(committed().map((operations) => operations.map(([kind]) => kind))).toEqual([
    ["set_clip_position", "set_clip_position"],
    ["set_clip_motion", "set_clip_motion"],
    ["set_clip_emphasis", "set_clip_emphasis"],
  ]);
});

test("a video beat shows its length read-only and no card controls", () => {
  mount("footage");

  expect(screen.getByText("5.0 s · follows the video; trim it in Timeline")).toBeDefined();
  expect(screen.queryByRole("group", { name: "Position" })).toBeNull();
  expect(screen.queryByLabelText("Each card (seconds)")).toBeNull();
});

test("a hook's text and length are its own", () => {
  const { committed } = mount("hook");

  const text = screen.getByLabelText("Text");
  fireEvent.change(text, { target: { value: "Banjir lagi" } });
  fireEvent.blur(text);
  const length = screen.getByLabelText("Length (seconds)");
  fireEvent.change(length, { target: { value: "3" } });
  fireEvent.blur(length);

  expect(committed()).toEqual([[["replace_text", "clip_hook"]], [["trim_clip_end", "clip_hook"]]]);
});

test("add from materials offers what the beat does not show, and attaches it", async () => {
  const { dispatch, attach, committed } = mount("reactions");

  fireEvent.click(screen.getByRole("button", { name: "Add from materials" }));
  const picker = screen.getByRole("listbox", { name: "Add from materials" });
  expect(within(picker).getAllByRole("option").map((option) => option.textContent)).toEqual(["@late"]);

  await act(async () => fireEvent.click(within(picker).getByRole("option", { name: "@late" })));

  expect(attach).toHaveBeenCalledWith("comment_card_003");
  expect(dispatch.mock.calls.map(([action]) => action.type)).toEqual(["assets_loaded", "commit_operations"]);
  expect(committed()[0]![0]![0]).toBe("add_clip_from_asset");
});

test("the inspector speaks Indonesian", () => {
  mount("reactions", { locale: "id" });

  expect(screen.getByRole("heading", { name: "Reaksi" })).toBeDefined();
  expect(screen.getByRole("group", { name: "Posisi" })).toBeDefined();
});
