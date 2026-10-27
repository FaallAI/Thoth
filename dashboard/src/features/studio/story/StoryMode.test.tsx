/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useEffect, type ReactNode } from "react";

import type { EditDocument } from "@/api/control-plane";
import { render } from "@/test-render";
import type { Locale } from "@/lib/i18n";

import { FakePlayer } from "../timeline-test-fixtures";
import type { PlayerTimelineRef } from "../usePlayerTimeline";
import { storyDocument, storyInventory } from "./story-test-fixtures";

const player = new FakePlayer();
const preview = mock(async (_projectId: string, assetId: string) => ({
  preview_url: `/api/v1/projects/project_001/editor-assets/${assetId}/preview`,
  expires_at: "2026-10-30T00:00:00Z",
}));

// The real preview needs a Remotion Player; this one hands Studio a fake and shows the overlay.
mock.module("../StudioPreview", () => ({
  StudioPreview: ({ onPlayer, overlay }: { onPlayer?: (player: PlayerTimelineRef | null) => void; overlay?: ReactNode }) => {
    useEffect(() => {
      onPlayer?.(player);
      return () => onPlayer?.(null);
    }, [onPlayer]);
    return <div aria-label="Draft preview">{overlay}</div>;
  },
}));

afterEach(() => {
  cleanup();
  player.seeks.length = 0;
});

async function mountStory(locale: Locale = "en", overrides: Record<string, unknown> = {}) {
  const { GuidedStudio } = await import("../GuidedStudio");
  const document = storyDocument() as EditDocument;
  render(
    <GuidedStudio
      client={{
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
        getStudioImportInventory: mock(async () => ({
          document_id: "edoc_story",
          source_key: "a".repeat(64),
          revision: 3,
          items: storyInventory(),
        })),
        getStudioMaterials: mock(async () => ({
          document_id: "edoc_story",
          provenance_available: true,
          items: [
            {
              item_id: "main_000",
              role: "main" as const,
              label: "Kabut asap Kalteng",
              media_kind: "video" as const,
              disposition: "attached" as const,
              asset_id: "asset_clip_main_000",
              owner_handle: "creator",
              platform: "x",
              verdict: "original" as const,
            },
            {
              item_id: "footage_000",
              role: "footage" as const,
              label: "Banjir footage",
              media_kind: "video" as const,
              disposition: "attached" as const,
              asset_id: "asset_clip_footage_000",
            },
            {
              item_id: "comment_card_003",
              role: "comment_card" as const,
              label: "@late",
              media_kind: "image" as const,
              disposition: "excluded" as const,
            },
          ],
          figures: [],
        })),
        createEditorPreviewCapability: preview,
        listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
        listStudioReviewComments: mock(async () => ({ comments: [], next_cursor: null })),
        listStudioReviewDecisions: mock(async () => ({ decisions: [], next_cursor: null })),
        createStudioReviewComment: mock(async () => {
          throw new Error("unused");
        }),
        createStudioReviewDecision: mock(async () => {
          throw new Error("unused");
        }),
        ...overrides,
      }}
      projectId="project_001"
      documentId="edoc_story"
      onBack={() => {}}
    />,
    { locale },
  );
  await screen.findByRole("group", { name: locale === "id" ? "Mode editor" : "Editor mode" });
  await act(async () => {});
}

test("a draft from a run opens in Story, with Timeline one click away", async () => {
  await mountStory();

  const modes = screen.getByRole("group", { name: "Editor mode" });
  expect(within(modes).getByRole("button", { name: "Story" }).getAttribute("aria-pressed")).toBe("true");
  expect(within(modes).getByRole("button", { name: "Timeline" }).getAttribute("aria-pressed")).toBe("false");
  expect(screen.getByRole("toolbar", { name: "Story beats" })).toBeDefined();
});

test("the modes speak Indonesian", async () => {
  await mountStory("id");

  const modes = screen.getByRole("group", { name: "Mode editor" });
  expect(within(modes).getByRole("button", { name: "Cerita" })).toBeDefined();
});

test("undo and redo sit in the top bar, not the tools menu", async () => {
  await mountStory();

  const undo = screen.getByRole("button", { name: "Undo" });
  expect(undo.closest("details")).toBeNull();
  expect(screen.getByRole("button", { name: "Redo" }).closest("details")).toBeNull();
});

test("Request review opens Review with the comment box focused", async () => {
  await mountStory();

  fireEvent.click(screen.getByRole("button", { name: "Request review" }));

  await waitFor(() => expect(document.activeElement).toBe(screen.getByLabelText("Review comment")));
  const review = within(screen.getByRole("navigation", { name: "Studio jobs" })).getByRole("button", { name: "Review" });
  expect(review.getAttribute("aria-current")).toBe("page");
});

test("the safe-zone toggle shades the top 10% and the bottom 18%", async () => {
  await mountStory();
  const toggle = screen.getByRole("button", { name: "Safe zone" });
  expect(toggle.getAttribute("aria-pressed")).toBe("false");
  expect(screen.queryByTestId("safe-zone-top")).toBeNull();

  fireEvent.click(toggle);

  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  expect((screen.getByTestId("safe-zone-top") as HTMLElement).style.height).toBe("10%");
  expect((screen.getByTestId("safe-zone-bottom") as HTMLElement).style.height).toBe("18%");
});

test("choosing a beat moves the playhead to its start", async () => {
  await mountStory();

  fireEvent.click(await screen.findByRole("button", { name: /^Reactions/ }));

  expect(player.seeks.at(-1)).toBe(60);
  expect(screen.getByRole("button", { name: /^Reactions/ }).getAttribute("aria-pressed")).toBe("true");
});

test("the inventory's missing material reaches the strip", async () => {
  await mountStory();

  expect((await screen.findByRole("button", { name: /^Reactions/ })).textContent).toContain("1 missing");
});

test("Story shows the run's materials beside the preview, with the draft's media previewed", async () => {
  await mountStory();

  const panel = await screen.findByRole("complementary", { name: "Materials" });
  expect(await within(panel).findByText("Banjir footage")).toBeDefined();
  expect(within(panel).getByText("Used in Footage")).toBeDefined();
  // The preview needs every video and still the draft draws, not only Timeline's library.
  await waitFor(() => expect(preview.mock.calls.map((call) => call[1])).toContain("asset_clip_footage_000"));
});

test("a chosen beat opens its inspector, and its edits save through the patch", async () => {
  await mountStory();
  // The first beat is open from the start, as the design shows.
  expect(await screen.findByRole("heading", { name: "Hook" })).toBeDefined();
  // The strip spans the whole workstation under the materials, preview and inspector.
  expect(screen.getByRole("toolbar", { name: "Story beats" }).closest("main")).toBeNull();

  fireEvent.click(await screen.findByRole("button", { name: /^Reactions/ }));
  expect(screen.getByRole("heading", { name: "Reactions" })).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Slow zoom" }));

  expect(screen.getByText("Unsaved changes")).toBeDefined();
  expect(screen.getByRole("button", { name: "Slow zoom" }).getAttribute("aria-pressed")).toBe("true");
});

test("a material dropped on a beat tile joins that beat", async () => {
  const attachStudioMaterial = mock(async () => ({
    asset_id: "asset_late",
    project_id: "project_001",
    kind: "image" as const,
    media_type: "image/png",
    width: 1080,
    height: 400,
    has_audio: false,
    validation_state: "ready" as const,
  }));
  await mountStory("en", { attachStudioMaterial });
  const reactions = await screen.findByRole("button", { name: /^Reactions/ });
  const dataTransfer = { types: ["application/x-thoth-material"], getData: () => "comment_card_003", dropEffect: "" };

  fireEvent.dragOver(reactions, { dataTransfer });
  await act(async () => fireEvent.drop(reactions, { dataTransfer }));

  expect(attachStudioMaterial).toHaveBeenCalledWith("project_001", "edoc_story", "comment_card_003");
  expect(screen.getByText("Unsaved changes")).toBeDefined();
});

test("Remove from beat excludes the missing material and adopts the decided revision", async () => {
  const resolveStudioImportItem = mock(async () => ({
    document_id: "edoc_story",
    source_key: "a".repeat(64),
    revision: 4,
    items: storyInventory().map((entry) => (entry.item_id === "comment_card_002" ? { ...entry, disposition: "excluded" as const } : entry)),
  }));
  await mountStory("en", { resolveStudioImportItem });
  fireEvent.click(await screen.findByRole("button", { name: /^Reactions/ }));

  await act(async () => fireEvent.click(within(screen.getByRole("alert")).getByRole("button", { name: "Remove from beat" })));

  expect(resolveStudioImportItem).toHaveBeenCalledWith("project_001", "edoc_story", "comment_card_002", {
    base_revision: 3,
    decision: { kind: "exclude" },
  });
  await waitFor(() => expect(screen.getByRole("button", { name: /^Reactions/ }).textContent).not.toContain("missing"));
});

test("a newer revision names itself and keeps the edits on this device", async () => {
  const latest = { ...storyDocument(), revision: 7 } as EditDocument;
  await mountStory("en", { patchEditDocument: mock(async () => ({ kind: "conflict" as const, latest })) });
  fireEvent.click(await screen.findByRole("button", { name: /^Reactions/ }));
  fireEvent.click(screen.getByRole("button", { name: "Slow zoom" }));

  expect(await screen.findByText("A newer revision 7 was saved · your changes are kept on this device", {}, { timeout: 3000 })).toBeDefined();
  expect(screen.getByRole("button", { name: "Keep Editing Locally" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Reload Latest" })).toBeDefined();
});

test("the Assist toggle opens the panel for the open beat, in Story only", async () => {
  const requestStoryAssist = mock(async () => ({ proposal_id: "a", title: "Shorter hook", reason: "r", operations: [] }));
  await mountStory("en", { requestStoryAssist });

  const toggle = screen.getByRole("button", { name: "Assist" });
  expect(toggle.getAttribute("aria-pressed")).toBe("false");
  expect(screen.queryByRole("region", { name: "Assist" })).toBeNull();
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-pressed")).toBe("true");
  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" })));
  expect(requestStoryAssist).toHaveBeenCalledWith("project_001", "edoc_story", { base_revision: 3, beat: "hook", clip_ids: ["clip_hook"] });

  fireEvent.click(within(screen.getByRole("group", { name: "Editor mode" })).getByRole("button", { name: "Timeline" }));
  expect(screen.queryByRole("button", { name: "Assist" })).toBeNull();
});

test("Add beat makes the missing Outro with the credit line", async () => {
  await mountStory();

  fireEvent.click(await screen.findByRole("button", { name: "Add beat" }));
  const menu = screen.getByRole("menu", { name: "Add beat" });
  expect(within(menu).getAllByRole("menuitem").map((item) => item.textContent)).toEqual(["Outro"]);
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Outro" }));

  expect(screen.getByText("Unsaved changes")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: /^Outro/ }));
  expect((screen.getByLabelText("Text") as HTMLInputElement).value).toBe("Video: @creator · X");
});

test("a phone gets the quick edit, without beats or timeline", async () => {
  const width = window.innerWidth;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 375 });
  try {
    const { GuidedStudio } = await import("../GuidedStudio");
    const document = storyDocument() as EditDocument;
    render(
      <GuidedStudio
        client={{
          getEditDocument: mock(async () => document),
          patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
          getStudioImportInventory: mock(async () => ({ document_id: "edoc_story", source_key: "a".repeat(64), revision: 3, items: storyInventory() })),
        }}
        projectId="project_001"
        documentId="edoc_story"
        onBack={() => {}}
      />,
    );

    expect(await screen.findByRole("heading", { name: "Quick edit · Rev 3" })).toBeDefined();
    expect(screen.queryByRole("toolbar", { name: "Story beats" })).toBeNull();
    expect(screen.queryByLabelText("Timeline")).toBeNull();
    expect(screen.getByLabelText("Draft preview")).toBeDefined();
  } finally {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
  }
});
