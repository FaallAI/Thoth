/// <reference types="bun-types" />

import { afterEach, expect, jest, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { render } from "@/test-render";
import { useEffect } from "react";
import {
  StudioReviewRequestError,
  type CreateComment,
  type EditDocument,
  type EditDocumentPatch,
  type ReviewComment,
  type ReviewDecision,
} from "@/api/control-plane";
import { createC2ClientFixtureBase } from "./prompt-proposal-test-fixtures";
import { FakePlayer, timelineDocument, upgradedTextDocument } from "./timeline-test-fixtures";
import type { PlayerTimelineRef } from "./usePlayerTimeline";

let previewPlayer: FakePlayer | null = null;
let previewMounts = 0;

mock.module("./StudioPreview", () => ({
  StudioPreview: ({
    document,
    onPlayer,
  }: {
    document: EditDocument;
    onPlayer?: (player: PlayerTimelineRef | null) => void;
  }) => {
    useEffect(() => {
      previewMounts += 1;
    }, []);
    useEffect(() => {
      onPlayer?.(previewPlayer);
      return () => onPlayer?.(null);
    }, [onPlayer]);
    const text = document.clips?.find((clip) => clip.kind === "text");
    return <div aria-label="Draft preview">{text && "heading" in text ? text.heading : document.clips?.[0]?.kind}</div>;
  },
}));

const promptClientBase = createC2ClientFixtureBase();
const initialWidth = window.innerWidth;

const document = {
  schema_version: 1,
  document_id: "document_001",
  project_id: "project_001",
  revision: 1,
  canvas: { width: 1080, height: 1920, fps: 30, duration_in_frames: 150 },
  template: { template_id: "vertical_text_story", version: 1 },
  tracks: [{ track_id: "track_visual", kind: "visual", clip_ids: ["clip_001"] }],
  scenes: [{ scene_id: "scene_001", role: "title", start_frame: 0, duration_in_frames: 150, clip_ids: ["clip_001"] }],
  clips: [{
    kind: "text",
    clip_id: "clip_001",
    scene_id: "scene_001",
    track_id: "track_visual",
    start_frame: 0,
    duration_in_frames: 150,
    heading: "Original heading",
    body: "Original body",
    ownership: "ai_managed",
    style_slot: "title",
  }],
} satisfies EditDocument;

function resize(width: number) {
  act(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
  });
}

afterEach(() => {
  cleanup();
  jest.useRealTimers();
  previewPlayer = null;
  previewMounts = 0;
  Object.defineProperty(window, "innerWidth", { configurable: true, value: initialWidth });
});

/** A save that never settles keeps the draft dirty for as long as the test needs. */
const pendingSave = mock(
  (_projectId: string, _documentId: string, _patch: EditDocumentPatch) =>
    new Promise<{ kind: "saved"; document: EditDocument }>(() => {}),
);

async function renderStudio(
  width: number,
  editDocument: EditDocument = document,
  patchEditDocument = pendingSave,
  extraClient: object = {},
) {
  resize(width);
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => editDocument), patchEditDocument, ...extraClient }}
      projectId="project_001"
      documentId={editDocument.document_id}
      onBack={() => {}}
    />,
  );
  await screen.findByLabelText("Draft preview");
}

// Bun pretty-prints a mismatched DOM node without bound, so assertions compare booleans.
const isHidden = (element: Element) => element.closest("[hidden]") !== null;
const job = (name: string) =>
  fireEvent.click(within(screen.getByRole("navigation", { name: "Studio jobs" })).getByRole("button", { name }));
const pane = (name: string) =>
  fireEvent.click(within(screen.getByRole("navigation", { name: "Studio panes" })).getByRole("button", { name }));

test("offers the three destinations at every width and compact Edit panes only below desktop width", async () => {
  await renderStudio(375);
  expect(screen.getByRole("navigation", { name: "Studio jobs" })).toBeDefined();
  const panes = within(screen.getByRole("navigation", { name: "Studio panes" })).getAllByRole("button");
  expect(panes.map((button) => button.textContent)).toEqual(["Scenes", "Preview", "Controls"]);
  expect(screen.queryByRole("tablist") === null).toBe(true);
  expect(screen.queryByLabelText("Assets width") === null).toBe(true);
  expect(screen.getByText("Saved")).toBeDefined();

  resize(768);
  expect(screen.getByRole("navigation", { name: "Studio panes" })).toBeDefined();
  expect(screen.queryByLabelText("Inspector width") === null).toBe(true);

  resize(1024);
  expect(screen.queryByRole("navigation", { name: "Studio panes" }) === null).toBe(true);
  expect(screen.getByRole("navigation", { name: "Studio jobs" })).toBeDefined();
  // Studio shell v2 (spec 2026-11-01): from 1024 up the jobs sit in the header's single row.
  const header = screen.getByRole("banner");
  expect(screen.getByRole("navigation", { name: "Studio jobs" }).parentElement === header).toBe(true);
  expect(header.className.includes("flex-nowrap") && header.className.includes("h-14")).toBe(true);
  expect(screen.queryByRole("tablist") === null).toBe(true);
  // Simple mode's scene strip sits under the preview: it collapses but has no width.
  expect(screen.queryByLabelText("Assets width") === null).toBe(true);
  expect(screen.getByRole("button", { name: "Scene board panel" })).toBeDefined();

  resize(1440);
  expect(screen.getByLabelText("Inspector width")).toBeDefined();
});

test("scopes the dark workspace to Studio and marks the current job at every width", async () => {
  await renderStudio(375);
  const shell = screen.getByLabelText("Guided Studio");
  expect(shell.classList.contains("studio-shell")).toBe(true);
  expect(globalThis.document.documentElement.classList.contains("studio-shell")).toBe(false);
  expect(globalThis.document.body.classList.contains("studio-shell")).toBe(false);

  for (const width of [375, 820, 1024, 1440]) {
    resize(width);
    job("Review");
    const nav = screen.getByRole("navigation", { name: "Studio jobs" });
    const current = within(nav).getAllByRole("button").filter((button) => button.getAttribute("aria-current") === "page");
    expect(current.map((button) => button.textContent)).toEqual(["Review"]);
    job("Edit");
  }
  expect(previewMounts).toBe(1);
});

test("keeps one preview mounted across every viewport", async () => {
  await renderStudio(1024);
  for (const width of [375, 900, 1440, 1024]) {
    resize(width);
    expect(screen.getAllByLabelText("Draft preview").length).toBe(1);
  }
  expect(previewMounts).toBe(1);
});

test("reaches every job at phone and desktop widths", async () => {
  await renderStudio(375);
  for (const width of [375, 1440]) {
    resize(width);
    job("Review");
    expect(isHidden(screen.getByText("Reviewing saved revision 1"))).toBe(false);
    expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(false);
    job("Render");
    expect(isHidden(screen.getByText(/Rendering is not available/))).toBe(false);
    expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(true);
    job("Edit");
    expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(false);
    const current = within(screen.getByRole("navigation", { name: "Studio jobs" }))
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-current") === "page");
    expect(current.map((button) => button.textContent)).toEqual(["Edit"]);
  }
  expect(previewMounts).toBe(1);
});

test("the Timeline option is offered at every width for a version 2 draft", async () => {
  // Studio shell v2 (spec 2026-11-01, decided): phones and tablets edit Story or Timeline in panes.
  for (const width of [375, 900, 1024]) {
    await renderStudio(width, timelineDocument() as EditDocument);
    const modes = await screen.findByRole("group", { name: "Editor mode" });
    expect(within(modes).getByRole("button", { name: "Timeline" })).toBeDefined();
    cleanup();
  }
});

test("a phone edits a version 2 draft in Story panes, with the beats as chips", async () => {
  await renderStudio(375, timelineDocument() as EditDocument);

  const panes = within(screen.getByRole("navigation", { name: "Studio panes" })).getAllByRole("button");
  expect(panes.map((button) => button.textContent)).toEqual(["Materials", "Preview", "Inspector"]);
  expect(screen.getByRole("toolbar", { name: "Story beats" }).getAttribute("data-variant")).toBe("chips");
  expect(screen.queryByRole("heading", { name: /^Quick edit/ }) === null).toBe(true);
});

test("Timeline on a phone edits by menu only, with the preview above the lanes and Inspect", async () => {
  await renderStudio(375, timelineDocument() as EditDocument);
  fireEvent.click(within(await screen.findByRole("group", { name: "Editor mode" })).getByRole("button", { name: "Timeline" }));

  const panes = within(screen.getByRole("navigation", { name: "Studio panes" })).getAllByRole("button");
  expect(panes.map((button) => button.textContent)).toEqual(["Assets", "Preview", "Timeline", "Inspector"]);
  pane("Timeline");
  // Operator, 2026-11-09: menu-only editing on phones, with the preview stacked above the lanes.
  expect(screen.getByText(/Press and hold for its menu/)).toBeDefined();
  const preview = screen.getByLabelText("Draft preview");
  expect(preview.closest("[hidden]")).toBeNull();
  expect(preview.compareDocumentPosition(screen.getByTestId("timeline-lanes")) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  expect(screen.queryByRole("button", { name: /^Trim start of/ }) === null).toBe(true);
  expect(screen.queryByRole("group", { name: "Clip actions" }) === null).toBe(true);
  // Final review, Important 3: lane toggles edit the draft too, so a view hides them.
  expect(screen.queryByRole("button", { name: /^(Mute|Unmute|Hide|Show|Lock|Unlock) / }) === null).toBe(true);
  fireEvent.click(screen.getByRole("button", { name: "Music clip" }));
  fireEvent.click(screen.getByRole("button", { name: "Inspect" }));
  expect(screen.getByRole("button", { name: "Inspector" }).getAttribute("aria-current")).toBe("page");
});

test("a version 1 draft keeps the scene board on a phone", async () => {
  await renderStudio(375);
  const panes = within(screen.getByRole("navigation", { name: "Studio panes" })).getAllByRole("button");
  expect(panes.map((button) => button.textContent)).toEqual(["Scenes", "Preview", "Controls"]);
});

test("desktop Timeline keeps every tool and inspector field", async () => {
  // Studio shell v2 (spec 2026-11-01, anti-goals): the redesign removes no tool and no field.
  await renderStudio(1440, timelineDocument() as EditDocument);
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  fireEvent.click(screen.getByRole("button", { name: "Main video clip" }));

  for (const name of ["Move clip to playhead", "Trim start to playhead", "Trim end to playhead", "Split clip at playhead", "Zoom in", "Zoom out"]) {
    expect(screen.getByRole("button", { name })).toBeDefined();
  }
  // A switch is named by its text, a field by its label.
  const control = (name: string) => screen.queryByRole("switch", { name }) ?? screen.queryByLabelText(name);
  // Position presets need a positioned clip; TimelineInspector's own tests hold them.
  for (const name of ["Ripple", "Snap", "Zoom", "Start frame", "End frame", "Fit", "Crop", "Hidden", "Locked", "Edited by"]) {
    expect(control(name) === null).toBe(false);
  }
});
test("explains a missing review or render capability instead of hiding the job", async () => {
  await renderStudio(1440);
  job("Review");
  expect(screen.getByRole("status").textContent).toContain("Review is not available");
  job("Render");
  expect(screen.getByRole("status").textContent).toContain("Rendering is not available");
});

test("shows one pane at a time on a phone and keeps hidden panes out of the tab order", async () => {
  await renderStudio(375);
  const heading = screen.getByLabelText("Heading");
  expect(screen.getByRole("button", { name: "Preview" }).getAttribute("aria-current")).toBe("page");
  expect(isHidden(heading)).toBe(true);
  expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(false);

  pane("Controls");
  expect(isHidden(heading)).toBe(false);
  expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(true);
});

test("pauses the preview when its pane is hidden and does not resume on return", async () => {
  previewPlayer = new FakePlayer();
  await renderStudio(375);
  const player = previewPlayer;

  pane("Controls");
  expect(player.calls).toEqual(["pause"]);
  pane("Preview");
  job("Review");
  expect(player.calls).toEqual(["pause"]);
  job("Render");
  expect(player.calls).toEqual(["pause", "pause"]);
});

test("reviews the saved revision while the draft keeps its unsaved edit", async () => {
  await renderStudio(375);
  pane("Controls");
  fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "Draft heading" } });
  expect(screen.getByText("Unsaved changes")).toBeDefined();

  job("Review");
  expect(screen.getByLabelText("Draft preview").textContent).toBe("Original heading");
  expect(screen.getByText("Reviewing saved revision 1")).toBeDefined();

  job("Edit");
  pane("Preview");
  expect(screen.getByLabelText("Draft preview").textContent).toBe("Draft heading");
});

test("reviews the saved revision on desktop and returns to the draft heading in Edit", async () => {
  await renderStudio(1440);
  fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "Draft heading" } });

  job("Review");
  expect(screen.getByLabelText("Draft preview").textContent).toBe("Original heading");
  expect(isHidden(screen.getByLabelText("Heading"))).toBe(true);
  expect(isHidden(screen.getByLabelText("Scene board"))).toBe(true);

  job("Edit");
  expect(screen.getByLabelText("Draft preview").textContent).toBe("Draft heading");
  expect((screen.getByLabelText("Heading") as HTMLInputElement).value).toBe("Draft heading");
  expect(previewMounts).toBe(1);
});

test("a pending timeline edit survives phone to tablet to desktop", async () => {
  const saved = mock(async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
    kind: "saved" as const,
    document: timelineDocument() as EditDocument,
  }));
  await renderStudio(1440, timelineDocument() as EditDocument, saved);
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  jest.useFakeTimers();
  fireEvent.click(screen.getByRole("button", { name: "Music clip" }));
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  expect(screen.getByText("Unsaved changes")).toBeDefined();

  resize(375);
  const modeTimeline = () => within(screen.getByRole("group", { name: "Editor mode" })).getByRole("button", { name: "Timeline" });
  expect(modeTimeline().getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByText("Unsaved changes")).toBeDefined();

  resize(900);
  pane("Assets");
  // This client lists no assets, so the pane is chosen but holds no library.
  expect(screen.getByRole("button", { name: "Assets" }).getAttribute("aria-current")).toBe("page");

  resize(1440);
  expect(modeTimeline().getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "Unmute Music" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Music clip" }).getAttribute("aria-pressed")).toBe("true");

  act(() => jest.advanceTimersByTime(500));
  expect(saved).toHaveBeenCalledTimes(1);
  expect(saved.mock.calls[0]![2].operations.map((operation) => operation.kind)).toEqual(["set_track_muted"]);
});
/** The upgraded text story plus one caption clip over its only scene. */
function captionDocument(): EditDocument {
  const document = upgradedTextDocument();
  document.tracks.push({
    track_id: "track_captions",
    kind: "caption",
    label: "Captions",
    order: 4,
    hidden: false,
    muted: false,
    locked: false,
    clip_ids: ["clip_caption"],
  });
  document.clips!.push({
    kind: "caption",
    clip_id: "clip_caption",
    track_id: "track_captions",
    from_frame: 0,
    duration_in_frames: 90,
    ownership: "ai_managed",
    hidden: false,
    locked: false,
    style_slot: "caption_default",
    cues: [{ from_frame: 0, duration_in_frames: 90, text: "First cue" }],
  });
  return document;
}

test("edits caption text on a tablet through the shared draft and keeps it on a phone", async () => {
  const saved = mock(async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
    kind: "saved" as const,
    document: captionDocument(),
  }));
  await renderStudio(900, captionDocument(), saved);
  jest.useFakeTimers();
  pane("Inspector");
  fireEvent.change(screen.getByLabelText("Caption cue 1 text"), { target: { value: "New subtitle" } });
  expect(screen.getByText("Unsaved changes")).toBeDefined();

  resize(375);
  // Studio shell v2 (spec 2026-11-01): a phone edits captions in the Story inspector pane.
  expect((screen.getByLabelText("Caption cue 1 text") as HTMLTextAreaElement).value).toBe("New subtitle");

  resize(900);
  expect((screen.getByLabelText("Caption cue 1 text") as HTMLTextAreaElement).value).toBe("New subtitle");
  act(() => jest.advanceTimersByTime(500));
  expect(saved).toHaveBeenCalledTimes(1);
  expect(saved.mock.calls[0]![2].operations.map((operation) => operation.kind)).toEqual(["set_caption_cue_text"]);
});
test("collapses a compact-desktop side region from a trigger that keeps focus", async () => {
  await renderStudio(1024);
  const trigger = screen.getByRole("button", { name: "Scene board panel" });
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  trigger.focus();
  fireEvent.click(trigger);
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(isHidden(screen.getByLabelText("Scene board"))).toBe(true);
  expect(window.document.activeElement === trigger).toBe(true);

  resize(1440);
  expect(screen.queryByRole("button", { name: "Scene board panel" }) === null).toBe(true);
  expect(isHidden(screen.getByLabelText("Scene board"))).toBe(false);
});

test("monitors renders on a phone without offering render mutations", async () => {
  const renderClient = {
    getRenderCapability: mock(async () => ({ available: true, preset_id: "standard_vertical_mp4_v1" as const, renderer_version: "r" })),
    listRenderJobs: mock(async () => ({ jobs: [], next_cursor: null })),
    createRenderJob: mock(async () => { throw new Error("unused"); }),
    getRenderJob: mock(async () => { throw new Error("unused"); }),
    cancelRenderJob: mock(async () => { throw new Error("unused"); }),
    retryRenderJob: mock(async () => { throw new Error("unused"); }),
    downloadRenderOutput: mock(async () => new Blob()),
    cleanupRenderArtifacts: mock(async () => { throw new Error("unused"); }),
  };
  resize(375);
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument: pendingSave, ...renderClient }}
      projectId="project_001"
      documentId={document.document_id}
      onBack={() => {}}
    />,
  );
  await screen.findByLabelText("Draft preview");
  const trigger = screen.getByRole("button", { name: "Render" });
  trigger.focus();
  job("Render");
  await screen.findByText("Starting, retrying, cancelling, and deleting renders need a wider screen.");
  expect(window.document.activeElement === trigger).toBe(true);
  expect(screen.queryByRole("button", { name: /^Render revision \d+$/ }) === null).toBe(true);
  // The empty workstation must not push render status off the first screen.
  expect(isHidden(screen.getByLabelText("Guided editing workstation"))).toBe(true);
  expect(screen.getAllByLabelText("Draft preview").length).toBe(1);

  resize(900);
  expect(screen.getByRole("button", { name: /^Render revision \d+$/ })).toBeDefined();
});

function reviewClient() {
  return {
    listStudioReviewComments: mock(async () => ({ comments: [] as ReviewComment[], next_cursor: null })),
    listStudioReviewDecisions: mock(async () => ({ decisions: [] as ReviewDecision[], next_cursor: null })),
    createStudioReviewComment: mock(async () => { throw new Error("unused"); }),
    createStudioReviewDecision: mock(async () => { throw new Error("unused"); }),
  };
}

test("reviews the saved preview on a phone and blocks review while a draft is unsaved", async () => {
  await renderStudio(375, document, pendingSave, reviewClient());
  pane("Controls");
  fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "Draft heading" } });

  job("Review");
  const panel = await screen.findByRole("region", { name: "Review" });
  expect(isHidden(panel)).toBe(false);
  expect(screen.getByLabelText("Draft preview").textContent).toBe("Original heading");
  expect(screen.getByText("Review applies to saved revision 1.")).toBeDefined();
  fireEvent.change(screen.getByLabelText("Review comment"), { target: { value: "Phone note" } });
  expect((screen.getByRole("button", { name: "Post comment" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Approve for render" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/Wait for your changes to save/)).toBeDefined();
});

test("keeps unsent review text across pane and viewport changes beside one preview", async () => {
  await renderStudio(375, document, pendingSave, reviewClient());
  job("Review");
  const panel = await screen.findByRole("region", { name: "Review" });
  fireEvent.change(screen.getByLabelText("Review comment"), { target: { value: "Phone note" } });

  job("Edit");
  expect(isHidden(panel)).toBe(true);
  job("Review");
  expect((screen.getByLabelText("Review comment") as HTMLTextAreaElement).value).toBe("Phone note");

  resize(1440);
  expect(isHidden(screen.getByRole("region", { name: "Review" }))).toBe(false);
  expect((screen.getByLabelText("Review comment") as HTMLTextAreaElement).value).toBe("Phone note");
  expect(screen.getAllByLabelText("Draft preview").length).toBe(1);
  expect(previewMounts).toBe(1);
});

test("keeps a stale review comment until the newer revision is loaded, then resubmits by hand", async () => {
  const review = reviewClient();
  review.listStudioReviewDecisions.mockImplementation(async () => ({
    decisions: [{
      decision_id: "decision_1",
      project_id: "project_001",
      document_id: "document_001",
      document_revision: 1,
      actor: { actor_id: "owner", actor_type: "user", display_name: null },
      decision: "approved" as const,
      reason: null,
      created_at: "2026-09-24T09:00:00Z",
    }],
    next_cursor: null,
  }));
  const posted = mock(async (_projectId: string, _documentId: string, request: CreateComment): Promise<ReviewComment> => {
    if (request.base_revision === 1) throw new StudioReviewRequestError("review_revision_conflict", 2);
    return {
      comment_id: "comment_1",
      project_id: "project_001",
      document_id: "document_001",
      document_revision: request.base_revision,
      actor: { actor_id: "owner", actor_type: "user", display_name: null },
      text: request.text,
      frame: request.frame ?? null,
      created_at: "2026-09-24T09:00:00Z",
    };
  });
  const revisions = [document, { ...document, revision: 2 }];
  const getEditDocument = mock(async () => revisions.shift() ?? document);
  await renderStudio(375, document, pendingSave, { ...review, createStudioReviewComment: posted, getEditDocument });
  job("Review");
  await screen.findByText("Current decision: Approved on revision 1");
  fireEvent.change(screen.getByLabelText("Review comment"), { target: { value: "Phone note" } });
  fireEvent.click(screen.getByRole("button", { name: "Post comment" }));

  fireEvent.click(await screen.findByRole("button", { name: "Load revision 2" }));
  fireEvent.click(await screen.findByRole("button", { name: "Reload Latest" }));
  expect(screen.getByText("Review applies to saved revision 2.")).toBeDefined();
  expect(screen.getByText("No decision on revision 2 yet.")).toBeDefined();
  expect(screen.getByText(/Approved on revision 1/)).toBeDefined();
  expect((screen.getByLabelText("Review comment") as HTMLTextAreaElement).value).toBe("Phone note");
  expect(posted).toHaveBeenCalledTimes(1);

  fireEvent.click(screen.getByRole("button", { name: "Post comment" }));
  await screen.findByText("Comment posted.");
  const [stale, resubmitted] = posted.mock.calls.map((call) => call[2]);
  expect(resubmitted!.base_revision).toBe(2);
  expect(resubmitted!.operation_id === stale!.operation_id).toBe(false);
});

test("Studio may shrink to the phone's width: a long title never widens the page", async () => {
  // A flex child's min-width defaults to its content; the truncated title's full text set it to
  // 985 px at 430 wide (browser walk, 2026-11-01).
  await renderStudio(375, timelineDocument() as EditDocument);
  expect(screen.getByRole("region", { name: "Guided Studio" }).className.split(" ").includes("min-w-0")).toBe(true);
});

test("leaving Timeline from its pane shows the preview, never an empty workspace", async () => {
  // Final review, Important 4: Story has no Timeline pane, so the chosen pane must fall back.
  await renderStudio(375, timelineDocument() as EditDocument);
  const modes = () => within(screen.getByRole("group", { name: "Editor mode" }));
  fireEvent.click(modes().getByRole("button", { name: "Timeline" }));
  pane("Timeline");
  fireEvent.click(modes().getByRole("button", { name: "Story" }));

  expect(screen.getByRole("button", { name: "Preview" }).getAttribute("aria-current")).toBe("page");
  expect(isHidden(screen.getByLabelText("Draft preview"))).toBe(false);
});

test("Story's side panel is named for what it holds, with no slider for its fixed width", async () => {
  // e2e audit 2026-11-02: the menu called the Materials column "Scene board panel".
  await renderStudio(1024, timelineDocument() as EditDocument);

  expect(screen.getByRole("button", { name: "Materials panel" })).toBeDefined();
  expect(screen.queryByRole("button", { name: "Scene board panel" }) === null).toBe(true);
  expect(screen.queryByLabelText("Assets width") === null).toBe(true);
  fireEvent.click(within(screen.getByRole("group", { name: "Editor mode" })).getByRole("button", { name: "Timeline" }));
  expect(screen.getByRole("button", { name: "Assets panel" })).toBeDefined();
});

test("a phone's Story pane fills the screen, with the beats pinned under it", async () => {
  // e2e audit 2026-11-02: the panes left the lower third empty and the chips floated.
  await renderStudio(430, timelineDocument() as EditDocument);

  expect((screen.getByLabelText("Guided editing workstation") as HTMLElement).style.gridTemplateRows).toContain("minmax");
});

// Spec 2026-11-08 §5.1: at 1024 an empty Timeline Inspector folds to a rail so the lanes get the width.
test("at 1024 an empty Timeline Inspector folds to a rail and opens on a selection", async () => {
  await renderStudio(1024, timelineDocument() as EditDocument);
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  const workstation = screen.getByLabelText("Guided editing workstation");
  expect(workstation.style.gridTemplateColumns).toContain("3rem");
  expect(workstation.style.gridTemplateColumns).not.toContain("var(--inspector-width)");
  fireEvent.click(screen.getByRole("button", { name: "Main video clip" }));
  expect(workstation.style.gridTemplateColumns).toContain("var(--inspector-width)");
});

// Final review 2026-11-08 #1: in Review the Timeline is hidden but mounted; its keys must not edit.
test("Delete in the Review job edits nothing", async () => {
  await renderStudio(1440, timelineDocument() as EditDocument);
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  fireEvent.click(screen.getByRole("button", { name: "Main video clip" }));
  job("Review");
  // `document` is this file's edit document; the page's body is window.document.body.
  fireEvent.keyDown(window.document.body, { key: "Delete" });
  job("Edit");
  expect(screen.getByRole("button", { name: "Main video clip" })).toBeDefined();
});
