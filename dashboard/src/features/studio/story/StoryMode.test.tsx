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

async function mountStory(locale: Locale = "en") {
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
        listStudioReviewComments: mock(async () => ({ comments: [], next_cursor: null })),
        listStudioReviewDecisions: mock(async () => ({ decisions: [], next_cursor: null })),
        createStudioReviewComment: mock(async () => {
          throw new Error("unused");
        }),
        createStudioReviewDecision: mock(async () => {
          throw new Error("unused");
        }),
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
