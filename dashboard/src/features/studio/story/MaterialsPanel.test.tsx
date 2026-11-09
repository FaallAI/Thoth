/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import type { EditorAsset, StudioMaterial, StudioMaterials } from "@/api/control-plane";
import { render } from "@/test-render";

import { MaterialsPanel } from "./MaterialsPanel";
import { computeBeats } from "./story_beats";
import { storyDocument, storyInventory } from "./story-test-fixtures";

afterEach(cleanup);

const material = (item_id: string, role: StudioMaterial["role"], extra: Partial<StudioMaterial> = {}): StudioMaterial => ({
  item_id,
  role,
  label: item_id,
  media_kind: "video",
  disposition: "attached",
  ...extra,
});

function materials(extra: Partial<StudioMaterials> = {}): StudioMaterials {
  return {
    document_id: "edoc_story",
    provenance_available: true,
    items: [
      material("main_000", "main", {
        label: "Banjir di Jakarta",
        platform: "tiktok",
        owner_handle: "creator",
        verdict: "replaced",
        ocr_outcome: "cover",
        trim_start_seconds: 1.5,
      }),
      material("comment_card_000", "comment_card", {
        media_kind: "image",
        asset_id: "asset_clip_comment_card_000",
        author: "viewer",
        likes: 12,
      }),
      ...Array.from({ length: 9 }, (_, index) =>
        material(`footage_00${index}`, "footage", {
          label: index === 0 ? "Cat rescue" : `Footage ${index}`,
          owner_handle: "kreator",
          query: "x",
          story_score: 0.8,
          shows_object: "yes",
        }),
      ),
      material("comment_000", "comment", { media_kind: "none", disposition: "excluded", label: "keren", author: "fan", likes: 9 }),
    ],
    figures: [{ name: "Ani", type: "person", role: "warga" }],
    ...extra,
  };
}

const upload = { asset_id: "asset_upload", kind: "image", media_type: "image/png", project_id: "project_001", has_audio: false, validation_state: "ready" } as EditorAsset;
const beats = computeBeats(storyDocument(), storyInventory());

function mount(value: StudioMaterials | null = materials(), locale: "en" | "id" = "en") {
  return render(<MaterialsPanel materials={value} uploads={[upload]} beats={beats} document={storyDocument()} previews={{}} />, { locale });
}

const group = (name: RegExp) => screen.getByRole("region", { name });

test("groups the run's materials with their counts", () => {
  mount();

  expect(screen.getByRole("button", { name: /^Main 1$/ })).toBeDefined();
  expect(screen.getByRole("button", { name: /^Cards 1$/ })).toBeDefined();
  expect(screen.getByRole("button", { name: /^Footage 9$/ })).toBeDefined();
  expect(screen.getByRole("button", { name: /^Figures 1$/ })).toBeDefined();
  expect(screen.getByRole("button", { name: /^Comments \(judged\) 1$/ })).toBeDefined();
  expect(screen.getByRole("button", { name: /^Uploads 1$/ })).toBeDefined();
});

test("a long group shows six, then the rest on request", () => {
  mount();

  const footage = group(/^Footage/);
  expect(within(footage).getAllByRole("listitem")).toHaveLength(6);
  fireEvent.click(within(footage).getByRole("button", { name: "Show 3 more" }));
  expect(within(footage).getAllByRole("listitem")).toHaveLength(9);
});

test("a group collapses", () => {
  mount();

  fireEvent.click(screen.getByRole("button", { name: /^Footage 9$/ }));
  expect(screen.getByRole("button", { name: /^Footage 9$/ }).getAttribute("aria-expanded")).toBe("false");
  expect(within(group(/^Footage/)).queryAllByRole("listitem")).toHaveLength(0);
});

test("search keeps only matching materials", () => {
  mount();

  fireEvent.change(screen.getByRole("searchbox", { name: "Search materials" }), { target: { value: "CAT" } });
  expect(within(group(/^Footage/)).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
    expect.stringContaining("Cat rescue"),
  ]);
  expect(within(group(/^Main/)).queryAllByRole("listitem")).toHaveLength(0);
});

test("the why popover says what the run knew", () => {
  mount();

  const footage = within(group(/^Footage/)).getAllByRole("listitem")[0]!;
  fireEvent.click(within(footage).getByRole("button", { name: "Why this material" }));
  const why = within(footage).getByRole("note");
  expect(why.textContent).toContain("Query: x");
  expect(why.textContent).toContain("Story score 80%");
  expect(why.textContent).toContain("Shows the object");

  const main = within(group(/^Main/)).getAllByRole("listitem")[0]!;
  fireEvent.click(within(main).getByRole("button", { name: "Why this material" }));
  expect(within(main).getByRole("note").textContent).toContain("Repost of @creator");
  expect(within(main).getByRole("note").textContent).toContain("trimmed 1.5 s");
});

test("a material used by a beat says where", () => {
  mount();

  const card = within(group(/^Cards/)).getAllByRole("listitem")[0]!;
  expect(card.textContent).toContain("Used in Reactions");
});

test("materials panel without provenance", () => {
  mount(materials({ provenance_available: false }));

  expect(screen.getByText("Provenance unavailable for this draft")).toBeDefined();
  expect(screen.queryAllByRole("button", { name: "Why this material" })).toHaveLength(0);
});

test("materials are draggable onto a beat", () => {
  mount();

  const card = within(group(/^Cards/)).getAllByRole("listitem")[0]!;
  const data = new Map<string, string>();
  fireEvent.dragStart(card, { dataTransfer: { setData: (type: string, value: string) => data.set(type, value), effectAllowed: "" } });
  expect(data.get("application/x-thoth-material")).toBe("comment_card_000");
});

test("the panel speaks Indonesian", () => {
  mount(materials(), "id");

  expect(screen.getByRole("button", { name: /^Kartu 1$/ })).toBeDefined();
  expect(screen.getByRole("searchbox", { name: "Cari materi" })).toBeDefined();
});

test("an upload row names its kind, never its id", () => {
  // Studio shell v2 (spec 2026-11-01, goal 4).
  mount();

  expect(screen.getByText("Upload · Image")).toBeDefined();
  expect(screen.queryByText(/asset_upload/)).toBeNull();
});

test("rows say what each material is, so a creator's cards stay apart", () => {
  // e2e audit 2026-11-02, finding 5: three identical "@kabinet_rakyat" rows.
  mount(
    materials({
      items: [
        material("post_card_000", "post_card", { media_kind: "image", label: "@kabinet_rakyat", owner_handle: "kabinet_rakyat" }),
        material("profile_card_000", "profile_card", { media_kind: "image", label: "@kabinet_rakyat", owner_handle: "kabinet_rakyat" }),
        material("footage_000", "footage", { label: "Cat rescue", owner_handle: "kreator" }),
        material("comment_000", "comment", { media_kind: "none", label: "Sangat setuju" }),
      ],
    }),
  );

  expect(screen.getByText("Post card · @kabinet_rakyat")).toBeDefined();
  expect(screen.getByText("Profile card · @kabinet_rakyat")).toBeDefined();
  expect(screen.getByText("Footage · Cat rescue")).toBeDefined();
  // A judged comment stays its own words.
  expect(screen.getByText("Sangat setuju")).toBeDefined();
});

test("the narration has its own group, with each beat's voice and length; none, no group", () => {
  // e2e audit 2026-11-02, finding 6: nothing in Materials named the narration.
  mount();
  expect(screen.queryByRole("region", { name: /^Narration/ })).toBeNull();
  cleanup();

  const source = storyDocument();
  const voice = {
    kind: "audio",
    clip_id: "clip_narration_main",
    track_id: source.tracks[0]!.track_id,
    asset_id: "asset_voice",
    from_frame: 0,
    duration_in_frames: 219,
  } as unknown as NonNullable<typeof source.clips>[number];
  render(<MaterialsPanel materials={materials()} uploads={[]} beats={beats} document={{ ...source, clips: [...(source.clips ?? []), voice] }} previews={{}} />);

  const voices = group(/^Narration/);
  expect(within(voices).getByText("Narration · Main")).toBeDefined();
  expect(within(voices).getByText("Audio · 7.3 s")).toBeDefined();
});

// Spec 2026-11-08 §5.2: a right click on a material.
test("a material's menu adds it to the open beat, or shows where it is used", () => {
  const added: string[] = [];
  const played: number[] = [];
  const beats = computeBeats(storyDocument(), storyInventory());
  render(
    <MaterialsPanel
      materials={materials()}
      uploads={[]}
      beats={beats}
      document={storyDocument()}
      previews={{}}
      openBeat={beats.find((beat) => beat.id === "reactions")}
      onAddToOpenBeat={(itemId) => added.push(itemId)}
      onShowUse={(frame) => played.push(frame)}
    />,
  );
  const used = screen.getByText("Used in Reactions").closest("li")!;
  fireEvent.contextMenu(used, { clientX: 5, clientY: 5 });
  expect(screen.getAllByRole("menuitem").map((entry) => entry.getAttribute("aria-label"))).toEqual(["Add to the open beat", "Show where it is used", "Why this material"]);
  expect(screen.getByRole("menuitem", { name: "Add to the open beat" }).getAttribute("title")).toBe("Already in this beat");
  fireEvent.click(screen.getByRole("menuitem", { name: "Show where it is used" }));

  const unused = screen.getByText(/Cat rescue/).closest("li")!;
  fireEvent.contextMenu(unused, { clientX: 5, clientY: 5 });
  expect(screen.getByRole("menuitem", { name: "Show where it is used" }).getAttribute("title")).toBe("Not used in the draft yet");
  fireEvent.click(screen.getByRole("menuitem", { name: "Add to the open beat" }));

  expect(played).toEqual([60]);
  expect(added).toEqual(["footage_000"]);
});

// Tier 1 review leftovers (2026-11-08): a right click inside the open menu does not reopen it.
test("a right click inside a material's open menu leaves it where it is", () => {
  const beats = computeBeats(storyDocument(), storyInventory());
  render(<MaterialsPanel materials={materials()} uploads={[]} beats={beats} document={storyDocument()} previews={{}} />);
  const row = screen.getByText("Used in Reactions").closest("li")!;
  fireEvent.contextMenu(row, { clientX: 5, clientY: 5 });
  fireEvent.contextMenu(screen.getAllByRole("menuitem")[0]!, { clientX: 300, clientY: 300 });
  expect(screen.getByRole("menu").style.left).toBe("5px");
});
