/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { EditorAsset, StudioMaterials } from "@/api/control-plane";
import { render } from "@/test-render";

import type { EditorAction } from "../editor_state";
import { BeatInspector } from "./BeatInspector";
import { beatOwnFrames, computeBeats } from "./story_beats";
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

test("a credit is no heading: its beat offers no heading position for it", () => {
  // 2026-11-12: a footage beat's @account credit must keep its corner.
  const place = (slot: string) => {
    const document = storyDocument();
    Object.assign(document.clips!.find((clip) => clip.clip_id === "clip_source")!, { style_slot: slot });
    const own = computeBeats(document, inventory);
    render(
      <BeatInspector
        beat={own.find((beat) => beat.id === "footage")!}
        beats={own}
        document={document}
        inventory={inventory}
        materials={materials}
        dispatch={mock(() => {})}
        attachMaterial={mock(async () => fresh)}
      />,
    );
    const found = screen.queryByRole("group", { name: "Heading position" });
    cleanup();
    return found;
  };
  expect(place("title")).not.toBeNull();
  expect(place("credit")).toBeNull();
});

test("the header names the beat, its place, its length and what is missing", () => {
  mount("reactions");

  expect(screen.getByRole("heading", { name: "Reactions" })).toBeDefined();
  expect(screen.getByText("Beat 3 of 4 · 2.7 s · 2 materials · 1 missing")).toBeDefined();
});

test("shown cards move, and leave the beat", () => {
  const { committed } = mount("reactions");

  fireEvent.click(screen.getByRole("button", { name: "Move Comment card · @viewer later" }));
  fireEvent.click(screen.getByRole("button", { name: "Remove Comment card · comment_card_001 from the beat" }));

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
  expect(within(picker).getAllByRole("option").map((option) => option.textContent)).toEqual(["Comment card · @late"]);

  await act(async () => fireEvent.click(within(picker).getByRole("option", { name: "Comment card · @late" })));

  expect(attach).toHaveBeenCalledWith("comment_card_003");
  expect(dispatch.mock.calls.map(([action]) => action.type)).toEqual(["assets_loaded", "commit_operations"]);
  // The card opens its own b-roll track when the beat's slot is taken (final review C1).
  expect(committed()[0]!.at(-1)![0]).toBe("add_clip_from_asset");
});

test("the inspector speaks Indonesian", () => {
  mount("reactions", { locale: "id" });

  expect(screen.getByRole("heading", { name: "Reaksi" })).toBeDefined();
  expect(screen.getByRole("group", { name: "Posisi" })).toBeDefined();
});

test("a missing profile page offers the profile card, and leaves the beat on request", async () => {
  const missing = [...inventory, { ...inventory[0]!, item_id: "profile_page_000", role: "profile_page" as const, label: "Profile page", disposition: "unresolved" as const }];
  const evidence = computeBeats(storyDocument(), missing).find((beat) => beat.id === "evidence")!;
  const dispatch = mock((_action: EditorAction) => {});
  const attach = mock(async () => fresh);
  const onRemoveMissing = mock(async (_itemId: string) => {});
  render(
    <BeatInspector
      beat={evidence}
      beats={beats}
      document={storyDocument()}
      inventory={missing}
      materials={{ ...materials, items: [...materials.items, { item_id: "profile_card_000", role: "profile_card", label: "@creator", media_kind: "image", disposition: "excluded" }] }}
      dispatch={dispatch}
      attachMaterial={attach}
      onRemoveMissing={onRemoveMissing}
    />,
  );

  const alert = screen.getByRole("alert");
  expect(alert.textContent).toContain("Profile page is missing");
  await act(async () => fireEvent.click(within(alert).getByRole("button", { name: "Use profile card" })));
  expect(attach).toHaveBeenCalledWith("profile_card_000");
  expect(dispatch.mock.calls.at(-1)![0]).toMatchObject({ type: "commit_operations" });

  await act(async () => fireEvent.click(within(alert).getByRole("button", { name: "Remove from beat" })));
  expect(onRemoveMissing).toHaveBeenCalledWith("profile_page_000");
});

test("without the run's provenance, Add from materials offers only what already has an asset", () => {
  render(
    <BeatInspector
      beat={beats.find((beat) => beat.id === "reactions")!}
      beats={beats}
      document={storyDocument()}
      inventory={inventory}
      materials={{
        ...materials,
        provenance_available: false,
        items: [
          ...materials.items,
          { item_id: "comment_card_004", role: "comment_card", label: "@kept", media_kind: "image", disposition: "excluded", asset_id: "asset_kept" },
        ],
      }}
      dispatch={mock(() => {})}
      attachMaterial={mock(async () => fresh)}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: "Add from materials" }));
  expect(within(screen.getByRole("listbox", { name: "Add from materials" })).getAllByRole("option").map((option) => option.textContent)).toEqual(["Comment card · @kept"]);
});

test("the timing fields follow the draft after an undo", () => {
  const props = {
    beats,
    inventory,
    materials,
    dispatch: mock(() => {}),
  };
  const first = storyDocument();
  const { rerender } = render(<BeatInspector {...props} beat={beats.find((beat) => beat.id === "reactions")!} document={first} />);
  expect((screen.getByLabelText("Each card (seconds)") as HTMLInputElement).value).toBe("1.3");

  const longer = storyDocument();
  for (const clip of longer.clips!) if (clip.clip_id.startsWith("clip_comment_card_00")) clip.duration_in_frames = 90;
  rerender(<BeatInspector {...props} beat={beats.find((beat) => beat.id === "reactions")!} document={longer} />);

  expect((screen.getByLabelText("Each card (seconds)") as HTMLInputElement).value).toBe("3.0");
});

// Operator 2026-10-28 (option 2): photos in the Footage beat may move; its videos already do.
test("a photo in the Footage beat offers Motion, and only Motion", () => {
  const document = storyDocument();
  document.asset_refs!.find((ref) => ref.asset_id === "asset_clip_footage_000")!.kind = "image";
  const dispatch = mock((_action: EditorAction) => {});
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "footage")!} beats={beats} document={document} inventory={inventory} materials={materials} dispatch={dispatch} />,
  );

  expect(screen.getByRole("group", { name: "Motion" })).toBeDefined();
  expect(screen.queryByRole("group", { name: "Position" })).toBeNull();
  expect(screen.queryByRole("group", { name: "Emphasis" })).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Slow zoom" }));
  expect(dispatch.mock.calls[0]![0]).toMatchObject({
    type: "commit_operations",
    operations: [{ kind: "set_clip_motion", clip_id: "clip_footage_000", motion: "slow_zoom" }],
  });
});

test("a Footage beat of videos offers no Motion", () => {
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "footage")!} beats={beats} document={storyDocument()} inventory={inventory} materials={materials} dispatch={mock(() => {})} />,
  );

  expect(screen.queryByRole("group", { name: "Motion" })).toBeNull();
});

test("a card beat lists Position, Motion and Emphasis in that order", () => {
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "reactions")!} beats={beats} document={storyDocument()} inventory={inventory} materials={materials} dispatch={mock(() => {})} />,
  );

  expect(screen.getAllByRole("group").map((group) => group.getAttribute("aria-label"))).toEqual(["Position", "Motion", "Background", "Moves", "Emphasis"]);
});

test("the Shown list uses labels: kind and source, never an id", () => {
  // Studio shell v2 (spec 2026-11-01, goal 4).
  mount("reactions");

  const shown = screen.getByRole("region", { name: "Shown" });
  expect(within(shown).getByText("Comment card · @viewer")).toBeDefined();
  expect(within(shown).queryByText(/asset_|clip_/)).toBeNull();
});

test("a narrated beat's cards follow the voice: no per-card length", () => {
  // Studio shell v2 (spec 2026-11-01, anti-goals): narration shares a beat by each card's length.
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "reactions")!} beats={beats} document={storyDocument()} inventory={inventory} materials={materials} dispatch={mock(() => {})} narrated />,
  );

  expect(screen.getByText("Cards follow the voice · 2.7 s")).toBeDefined();
  expect(screen.queryByLabelText(/Each card/)).toBeNull();
});

test("a beat that spans others reads its own seconds, as its tile does", () => {
  // e2e audit 2026-11-02, finding 4: Main read 13.6 s in the inspector and 8.9 s on its tile.
  const canvas = storyDocument().canvas.duration_in_frames;
  const spanning = beats.map((beat, index) => (index === 0 ? { ...beat, startFrame: 0, durationInFrames: canvas } : beat));
  const own = beatOwnFrames(spanning, canvas).get(spanning[0]!.id)!;
  expect(own).toBeLessThan(canvas);
  render(<BeatInspector beat={spanning[0]!} beats={spanning} document={storyDocument()} inventory={inventory} materials={materials} dispatch={mock(() => {})} />);

  expect(screen.getByText(new RegExp(`^Beat 1 of 4 · ${(own / 30).toFixed(1)} s`))).toBeDefined();
});

// Spec 2026-11-08 §5.2: a right click on a Shown item gathers its edits.
const shownItems = () => within(screen.getByRole("region", { name: "Shown" })).getAllByRole("listitem");
const itemNames = () => screen.getAllByRole("menuitem").map((entry) => entry.getAttribute("aria-label"));

test("a Shown item's menu offers the beat's edits, with what does not apply disabled", () => {
  mount("reactions");
  fireEvent.contextMenu(shownItems()[0]!, { clientX: 5, clientY: 5 });
  expect(itemNames()).toEqual([
    "Move earlier",
    "Move later",
    "Remove from beat",
    "Replace media…",
    "Top",
    "Middle",
    "Lower third",
    "Highlight box",
    "Arrow",
    "Play from here",
    "Show in Timeline",
  ]);
  expect(screen.getByRole("menuitem", { name: "Move earlier" }).getAttribute("title")).toBe("Already first");
  const menu = screen.getByRole("menu");
  expect(within(within(menu).getByRole("group", { name: "Position" })).getAllByRole("menuitem")).toHaveLength(3);
  expect(within(within(menu).getByRole("group", { name: "Emphasis" })).getAllByRole("menuitem")).toHaveLength(2);
});

test("Move later from the menu makes the same edit as the arrow", () => {
  const { committed } = mount("reactions");
  fireEvent.contextMenu(shownItems()[0]!, { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Move later" }));
  fireEvent.click(screen.getAllByRole("button", { name: /later$/ })[0]!);
  const [fromMenu, fromArrow] = committed();
  expect(fromMenu).toEqual(fromArrow);
});

test("Play from here and Show in Timeline hand the clip back", () => {
  const played: number[] = [];
  const shown: string[] = [];
  render(
    <BeatInspector
      beat={beats.find((beat) => beat.id === "reactions")!}
      beats={beats}
      document={storyDocument()}
      inventory={inventory}
      materials={materials}
      dispatch={() => {}}
      onPlayFrom={(frame) => played.push(frame)}
      onShowInTimeline={(clipId) => shown.push(clipId)}
    />,
  );
  fireEvent.contextMenu(shownItems()[0]!, { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Play from here" }));
  fireEvent.contextMenu(shownItems()[0]!, { clientX: 5, clientY: 5 });
  fireEvent.click(screen.getByRole("menuitem", { name: "Show in Timeline" }));
  expect(played).toEqual([60]);
  expect(shown).toEqual(["clip_comment_card_000"]);
});

// Tier 1 review leftovers (2026-11-08): a pick request opens the picker once and says it was handled.
test("a request to add from materials opens the picker once and reports it handled", () => {
  const handled = mock(() => {});
  render(
    <BeatInspector
      beat={beats.find((beat) => beat.id === "reactions")!}
      beats={beats}
      document={storyDocument()}
      inventory={inventory}
      materials={materials}
      dispatch={() => {}}
      attachMaterial={mock(async () => fresh)}
      pickRequest={1}
      onPickHandled={handled}
    />,
  );
  expect(screen.getByRole("listbox", { name: "Add from materials" })).toBeDefined();
  expect(handled).toHaveBeenCalledTimes(1);
});

// Studio effects layer (spec 2026-11-09): Background, Dim and moves per beat; marks named.
function committedBatches(dispatch: ReturnType<typeof mock>) {
  return dispatch.mock.calls
    .map(([action]) => action as EditorAction)
    .filter((action): action is Extract<EditorAction, { type: "commit_operations" }> => action.type === "commit_operations")
    .map((action) => action.operations);
}

test("Blur-fill applies to every card of the beat as one batch", () => {
  const { dispatch } = mount("reactions");
  fireEvent.click(screen.getByRole("button", { name: "Blur-fill" }));
  const [batch] = committedBatches(dispatch);
  expect(batch!.length).toBeGreaterThan(1);
  expect(batch!.every((operation) => operation.kind === "set_clip_background")).toBe(true);
});

test("Push in writes each card's own keyframes", () => {
  const { dispatch } = mount("reactions");
  fireEvent.click(screen.getByRole("button", { name: "Push in" }));
  const [batch] = committedBatches(dispatch);
  const document = storyDocument();
  for (const operation of batch!) {
    const moves = (operation as Extract<typeof operation, { kind: "set_clip_moves" }>).moves;
    const clip = document.clips!.find((candidate) => candidate.clip_id === (operation as { clip_id: string }).clip_id)!;
    expect(moves.at(-1)!.frame).toBe(clip.duration_in_frames - 1);
  }
});

test("Dim applies to the Footage beat's photos", () => {
  const document = storyDocument();
  document.asset_refs!.find((ref) => ref.asset_id === "asset_clip_footage_000")!.kind = "image";
  const dispatch = mock((_action: EditorAction) => {});
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "footage")!} beats={beats} document={document} inventory={inventory} materials={materials} dispatch={dispatch} />,
  );
  const dim = screen.getByLabelText("Dim");
  fireEvent.change(dim, { target: { value: "50" } });
  fireEvent.pointerUp(dim);
  expect(committedBatches(dispatch)[0]).toMatchObject([{ kind: "set_clip_dim", clip_id: "clip_footage_000", dim: 0.5 }]);
});

test("the beat names the cards with marks", () => {
  const document = storyDocument();
  const card = document.clips!.find((clip) => clip.clip_id === beats.find((beat) => beat.id === "reactions")!.clipIds.find((id) => document.clips!.find((c) => c.clip_id === id)?.kind === "video"))!;
  Object.assign(card, {
    emphasis: { highlight: false, arrow: false, marks: [{ kind: "arrow", x: 0.5, y: 0.5, w: 0, h: 0, side: "top", from_frame: 0, to_frame: 30, color: "accent" }] },
  });
  render(
    <BeatInspector beat={beats.find((beat) => beat.id === "reactions")!} beats={beats} document={document} inventory={inventory} materials={materials} dispatch={mock(() => {})} />,
  );
  expect(screen.getByText(/^Marks set in Timeline: /)).toBeDefined();
});

test("a heading can become a card", () => {
  const { dispatch } = mount("hook");
  fireEvent.click(screen.getByRole("button", { name: "Card" }));
  expect(committedBatches(dispatch)[0]).toMatchObject([{ kind: "set_text_place", style_slot: "card" }]);
});

// Review 2026-11-10: a Motion choice replaces moves, so Story can remove the moves it adds.
test("a Motion choice clears the cards' moves, and no Motion reads as chosen while moves play", () => {
  const document = storyDocument();
  const reactions = beats.find((beat) => beat.id === "reactions")!;
  const card = document.clips!.find((clip) => reactions.clipIds.includes(clip.clip_id) && clip.kind === "video")!;
  Object.assign(card, { moves: [{ frame: 0, scale: 1, x: 0, y: 0, ease: "linear" }, { frame: 30, scale: 1.12, x: 0, y: 0, ease: "linear" }] });
  const dispatch = mock((_action: EditorAction) => {});
  render(<BeatInspector beat={reactions} beats={beats} document={document} inventory={inventory} materials={materials} dispatch={dispatch} />);
  const motion = within(screen.getByRole("group", { name: "Motion" }));
  const none = motion.getAllByRole("button", { name: "None" })[0]!;
  expect(none.getAttribute("aria-pressed")).toBe("false");
  fireEvent.click(none);
  const [batch] = committedBatches(dispatch);
  expect(batch).toContainEqual(expect.objectContaining({ kind: "set_clip_moves", clip_id: card.clip_id, moves: [] }));
  expect(batch!.some((operation) => operation.kind === "set_clip_motion")).toBe(true);
});
