/// <reference types="bun-types" />

import { afterEach, expect, jest, mock, setSystemTime, test } from "bun:test";
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { render } from "@/test-render";
import { useEffect } from "react";
import userEvent from "@testing-library/user-event";
import type { EditDocument, EditDocumentPatch } from "@/api/control-plane";
import { createC2ClientFixtureBase } from "./prompt-proposal-test-fixtures";
import { FakePlayer } from "./timeline-test-fixtures";
import type { PlayerTimelineRef } from "./usePlayerTimeline";

/** Installed by the player tests; the mocked preview hands it to Studio's ref. */
let previewPlayer: FakePlayer | null = null;

mock.module("./StudioPreview", () => ({
  StudioPreview: ({
    document,
    onPlayer,
    playbackRate,
  }: {
    document: EditDocument;
    onPlayer?: (player: PlayerTimelineRef | null) => void;
    playbackRate?: number;
  }) => {
    // Published after commit, the way the real Player hands over its instance.
    useEffect(() => {
      onPlayer?.(previewPlayer);
      return () => onPlayer?.(null);
    }, [onPlayer]);
    return (
      <div aria-label="Draft preview" data-rate={playbackRate ?? 1}>
        {document.clips?.[0]?.kind}
      </div>
    );
  },
}));

const promptClientBase = createC2ClientFixtureBase();
const jobButton = (name: string) =>
  within(screen.getByRole("navigation", { name: "Studio jobs" })).getByRole("button", { name });
const job = (name: string) => fireEvent.click(jobButton(name));

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

afterEach(() => {
  cleanup();
  previewPlayer = null;
  jest.useRealTimers();
});

test("renders labelled Inspector fields and keyboard-visible editing controls", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const client = {
    ...promptClientBase,
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
  };

  render(<GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />);

  expect(await screen.findByLabelText("Heading")).toBeDefined();
  expect(screen.getByLabelText("Body")).toBeDefined();
  expect(screen.getByLabelText("Edited by")).toBeDefined();
  expect(screen.getByLabelText("Duration (seconds)")).toBeDefined();
  expect(screen.getByRole("button", { name: "Undo" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Redo" })).toBeDefined();
  expect(screen.getByText("Saved")).toBeDefined();
});

test("autosaves after 500ms and reports Saving then Saved", async () => {
  let resolveSave: (value: { kind: "saved"; document: EditDocument }) => void = () => {};
  const patchEditDocument = mock(
    () => new Promise<{ kind: "saved"; document: EditDocument }>((resolve) => { resolveSave = resolve; }),
  );
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  jest.useFakeTimers();
  try {
    fireEvent.change(heading, { target: { value: "Edited heading" } });
    act(() => jest.advanceTimersByTime(499));
    expect(patchEditDocument).toHaveBeenCalledTimes(0);
    act(() => jest.advanceTimersByTime(1));
    expect(patchEditDocument).toHaveBeenCalledTimes(1);
    expect(screen.getByText("Saving")).toBeDefined();
    const savedDocument = {
      ...document,
      revision: 2,
      clips: [{ ...document.clips[0], heading: "Edited heading", ownership: "user_edited" as const }],
    };
    await act(async () => { resolveSave({ kind: "saved", document: savedDocument }); });
    expect(screen.getByText("Saved")).toBeDefined();
  } finally {
    jest.useRealTimers();
  }
});

test("shows safe Retry guidance after a failed save without rendering the raw error", async () => {
  const rawError = "database password=do-not-render";
  const patchEditDocument = mock(async () => { throw new Error(rawError); });
  const { GuidedStudio } = await import("./GuidedStudio");
  const user = userEvent.setup();
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  await user.type(heading, " updated");

  expect((await screen.findByRole("alert", {}, { timeout: 1_000 })).textContent).toContain("Your edits are still here");
  expect(screen.getByRole("button", { name: "Retry" })).toBeDefined();
  expect(screen.queryByText(rawError)).toBeNull();
});

test("keeps the local draft on conflict and offers both explicit recovery actions", async () => {
  const latest = {
    ...document,
    revision: 2,
    clips: [{ ...document.clips[0], heading: "Remote heading" }],
  };
  const { GuidedStudio } = await import("./GuidedStudio");
  const user = userEvent.setup();
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "conflict" as const, latest })),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  await user.clear(heading);
  await user.type(heading, "Local heading");

  expect(await screen.findByText("Conflict", {}, { timeout: 1_000 })).toBeDefined();
  expect((screen.getByLabelText("Heading") as HTMLInputElement).value).toBe("Local heading");
  expect(screen.getByRole("button", { name: "Reload Latest" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Keep Editing Locally" })).toBeDefined();

  await user.click(screen.getByRole("button", { name: "Reload Latest" }));
  expect((screen.getByLabelText("Heading") as HTMLInputElement).value).toBe("Remote heading");
});

test("associates a safe inline validation message with a blank heading", async () => {
  const patchEditDocument = mock(async () => ({ kind: "saved" as const, document }));
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  jest.useFakeTimers();
  try {
    fireEvent.change(heading, { target: { value: "   " } });
    const message = screen.getByText("Heading is required before saving.");
    expect(heading.getAttribute("aria-invalid")).toBe("true");
    expect(heading.getAttribute("aria-describedby")).toBe(message.id);
    act(() => jest.advanceTimersByTime(500));
    expect(patchEditDocument).toHaveBeenCalledTimes(0);
  } finally {
    jest.useRealTimers();
  }
});

test("offers an explicit upgrade for a version 1 document and writes nothing on open", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const upgradeEditDocument = mock(async () => ({ kind: "saved" as const, document }));
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
        upgradeEditDocument,
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );

  expect(await screen.findByRole("button", { name: "Enable advanced timeline" })).toBeDefined();
  expect(screen.getByText(/scenes, text, and history/i)).toBeDefined();
  expect(upgradeEditDocument).toHaveBeenCalledTimes(0);
  expect(screen.queryByLabelText("Timeline")).toBeNull();
});

test("upgrades once for a double click and then opens the advanced timeline", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const upgraded = timelineDocument();
  let release: (value: { kind: "saved"; document: EditDocument }) => void = () => {};
  const upgradeEditDocument = mock(
    () =>
      new Promise<{ kind: "saved"; document: EditDocument }>((resolve) => {
        release = resolve;
      }),
  );
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
        upgradeEditDocument,
        listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
        createEditorPreviewCapability: mock(async () => ({
          preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
          expires_at: "2026-09-20T00:00:00Z",
        })),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );

  const upgrade = await screen.findByRole("button", { name: "Enable advanced timeline" });
  fireEvent.click(upgrade);
  fireEvent.click(upgrade);
  expect(upgradeEditDocument).toHaveBeenCalledTimes(1);

  await act(async () => {
    release({ kind: "saved", document: upgraded });
  });
  expect(await screen.findByLabelText("Timeline")).toBeDefined();
  expect(screen.getByLabelText("Asset library")).toBeDefined();
  expect(screen.getByLabelText("Timeline inspector")).toBeDefined();
  expect(screen.queryByLabelText("Scene board")).toBeNull();
});

test("shows the conflict choice instead of upgrading over a newer revision", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const latest = { ...document, revision: 7 };
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
        upgradeEditDocument: mock(async () => ({ kind: "conflict" as const, latest })),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Enable advanced timeline" }));
  expect(await screen.findByText(/A newer revision \d+ was saved/)).toBeDefined();
  expect(screen.getByRole("button", { name: "Reload Latest" })).toBeDefined();
});

test("keeps the version 1 document editable when the upgrade fails", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
        upgradeEditDocument: mock(async () => {
          throw new Error("offline");
        }),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );

  fireEvent.click(await screen.findByRole("button", { name: "Enable advanced timeline" }));
  expect((await screen.findByRole("alert")).textContent).toContain("Could not enable");

  const heading = screen.getByLabelText("Heading");
  fireEvent.change(heading, { target: { value: "Still editable" } });
  expect((heading as HTMLInputElement).value).toBe("Still editable");
  expect(screen.getByRole("button", { name: "Enable advanced timeline" })).toBeDefined();
});

/** Mount an advanced document with a client that always answers. */
async function mountAdvanced(overrides: Record<string, unknown> = {}) {
  const { GuidedStudio } = await import("./GuidedStudio");
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: timelineDocument() as EditDocument,
    }),
  );
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => timelineDocument() as EditDocument),
        patchEditDocument,
        listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
        createEditorPreviewCapability: mock(async () => ({
          preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
          expires_at: "2026-09-20T00:00:00Z",
        })),
        ...overrides,
      }}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  // A draft opens in Story; Timeline is one click away.
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  return { patchEditDocument };
}

test("autosaves a timeline edit through the same patch path", async () => {
  const { patchEditDocument } = await mountAdvanced();
  jest.useFakeTimers();
  try {
    fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
    expect(screen.getByText("Unsaved changes")).toBeDefined();
    act(() => jest.advanceTimersByTime(500));
    expect(patchEditDocument).toHaveBeenCalledTimes(1);
    const patch = patchEditDocument.mock.calls[0]![2];
    expect(patch.operations.map((operation) => operation.kind)).toEqual(["set_track_muted"]);
  } finally {
    jest.useRealTimers();
  }
});

test("keeps an unsaved timeline edit across a Review round trip", async () => {
  await mountAdvanced();
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  job("Review");
  job("Edit");

  expect(screen.getByRole("button", { name: "Unmute Music" })).toBeDefined();
  expect(screen.getByText("Unsaved changes")).toBeDefined();
});

test("an unavailable asset library leaves the timeline editable", async () => {
  await mountAdvanced({
    listEditorAssets: mock(async () => {
      throw new Error("offline");
    }),
  });

  expect((await screen.findByRole("alert")).textContent).toContain("Assets are unavailable");
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  expect(screen.getByRole("button", { name: "Unmute Music" })).toBeDefined();
});

const advancedClientBase = {
  listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
  createEditorPreviewCapability: mock(async () => ({
    preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
    expires_at: "2026-09-20T00:00:00Z",
  })),
};

async function renderTimelineStudio(
  document: EditDocument,
  patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document,
    }),
  ),
) {
  const { GuidedStudio } = await import("./GuidedStudio");
  const view = render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument,
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  await screen.findByLabelText("Timeline");
  // The preview publishes its player after commit, so let that render settle.
  await act(async () => {});
  return { view, patchEditDocument };
}

test("Timeline keeps the sound effects in the asset column, never a workstation cell of their own", async () => {
  // A fragment in the `contents` region made the SFX list a grid cell: it took the centre column,
  // and pushed the preview, timeline and inspector one cell along (audit, 2026-11-01).
  const { upgradedTextDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const document = upgradedTextDocument() as EditDocument;
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        listSfx: mock(async () => []),
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  const sfx = await screen.findByRole("region", { name: "Sound effects" });
  const column = screen.getByLabelText("Asset library").parentElement!;

  expect(column.contains(sfx)).toBe(true);
  expect(column.id).not.toBe("studio-region-scenes");
});

test("offers Story and Timeline for a version 2 document", async () => {
  const { upgradedTextDocument } = await import("./timeline-test-fixtures");
  await renderTimelineStudio(upgradedTextDocument() as EditDocument);

  const simple = screen.getByRole("button", { name: "Story" });
  const advanced = screen.getByRole("button", { name: "Timeline" });
  expect(screen.getByLabelText("Editor mode")).toBeDefined();
  expect(advanced.getAttribute("aria-pressed")).toBe("true");
  expect(simple.getAttribute("aria-pressed")).toBe("false");

  fireEvent.click(simple);

  expect(simple.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("toolbar", { name: "Story beats" })).toBeDefined();
  expect(screen.getByLabelText("Heading")).toBeDefined();
  expect(screen.queryByLabelText("Timeline")).toBeNull();
  expect(screen.queryByLabelText("Asset library")).toBeNull();
});

test("retains the design mode control with an unavailable Advanced choice for a version 1 document", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
      }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );

  await screen.findByLabelText("Heading");
  expect(screen.getByLabelText("Editor mode")).toBeDefined();
  expect(screen.getByRole("button", { name: /^Timeline$/ }).hasAttribute("disabled")).toBe(true);
});

test("edits a version 2 text clip from Simple mode through the existing operations", async () => {
  const { upgradedTextDocument } = await import("./timeline-test-fixtures");
  const upgraded = upgradedTextDocument() as EditDocument;
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: upgraded,
    }),
  );
  await renderTimelineStudio(upgraded, patchEditDocument);

  fireEvent.click(screen.getByRole("button", { name: "Story" }));
  const heading = screen.getByLabelText("Heading") as HTMLInputElement;

  jest.useFakeTimers();
  fireEvent.change(heading, { target: { value: "Simple heading" } });
  expect(heading.value).toBe("Simple heading");
  act(() => jest.advanceTimersByTime(500));

  expect(patchEditDocument).toHaveBeenCalledTimes(1);
  const patch = patchEditDocument.mock.calls[0]![2];
  expect(patch.operations).toHaveLength(1);
  expect(patch.operations[0]).toMatchObject({
    kind: "replace_text",
    clip_id: "clip_001",
    field: "heading",
    value: "Simple heading",
  });
  expect(JSON.stringify(patch)).not.toContain("mode");
});

test("keeps unsaved version 2 edits across Simple, Advanced, and Review", async () => {
  const { upgradedTextDocument } = await import("./timeline-test-fixtures");
  const upgraded = upgradedTextDocument() as EditDocument;
  const patchEditDocument = mock(() => new Promise<{ kind: "saved"; document: EditDocument }>(() => {}));
  await renderTimelineStudio(upgraded, patchEditDocument);

  fireEvent.click(screen.getByRole("button", { name: "Hide Overlay" }));
  fireEvent.click(screen.getByRole("button", { name: "Story" }));
  fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "Round trip heading" } });

  fireEvent.click(screen.getByRole("button", { name: "Timeline" }));
  job("Review");
  job("Edit");
  fireEvent.click(screen.getByRole("button", { name: "Story" }));

  expect((screen.getByLabelText("Heading") as HTMLInputElement).value).toBe("Round trip heading");
  fireEvent.click(screen.getByRole("button", { name: "Timeline" }));
  expect(screen.getByRole("button", { name: "Show Overlay" })).toBeDefined();
});

test("drives and follows the preview player from the timeline", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  previewPlayer = new FakePlayer();
  await renderTimelineStudio(timelineDocument() as EditDocument);
  const player = previewPlayer;

  act(() => player.emit("frameupdate", { detail: { frame: 42 } }));
  const playhead = () => screen.getByRole("slider", { name: "Playhead" });
  expect(playhead().getAttribute("aria-valuenow")).toBe("42");

  fireEvent.keyDown(playhead(), { key: "ArrowRight", shiftKey: true });
  expect(player.seeks).toEqual([72]);
  expect(playhead().getAttribute("aria-valuenow")).toBe("72");

  fireEvent.click(screen.getByRole("button", { name: "Play" }));
  act(() => player.emit("play"));
  expect(player.calls).toEqual(["play"]);
  fireEvent.click(screen.getByRole("button", { name: "Pause" }));
  act(() => player.emit("pause"));
  expect(player.calls).toEqual(["play", "pause"]);
});

test("detaches every player listener when Studio unmounts", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  previewPlayer = new FakePlayer();
  const { view } = await renderTimelineStudio(timelineDocument() as EditDocument);
  const player = previewPlayer;
  expect(player.listenerCount).toBeGreaterThan(0);

  view.unmount();

  expect(player.listenerCount).toBe(0);
});

const assetPage = (assetId: string, cursor: string | null) => ({
  assets: [
    {
      asset_id: assetId,
      project_id: "project_001",
      kind: "video" as const,
      media_type: "video/mp4",
      has_audio: true,
      validation_state: "ready" as const,
      duration_in_frames: 60,
    },
  ],
  next_cursor: cursor,
});

/** Two ready assets, one per page, in a Studio whose saves always succeed. */
async function renderPagedAssetStudio() {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const upgraded = timelineDocument() as EditDocument;
  const listEditorAssets = mock(async (_projectId: string, cursor?: string) =>
    cursor ? assetPage("asset_second", null) : assetPage("asset_first", "cursor_2"),
  );
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: upgraded,
    }),
  );
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        listEditorAssets,
        getEditDocument: mock(async () => upgraded),
        patchEditDocument,
      }}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));
  return { listEditorAssets, patchEditDocument };
}

/** Let the debounced autosave fire and its response settle. */
async function completeAutosave(act_: () => void) {
  jest.useFakeTimers();
  try {
    act_();
    act(() => jest.advanceTimersByTime(500));
  } finally {
    jest.useRealTimers();
  }
  await act(async () => {});
}

test("keeps a first-page asset addable after a second page loads", async () => {
  const { patchEditDocument } = await renderPagedAssetStudio();

  fireEvent.click(await screen.findByRole("button", { name: "Load more assets" }));
  expect(await screen.findByLabelText("Add Upload · Video · 2 to timeline")).toBeDefined();
  expect(screen.getByLabelText("Add Upload · Video to timeline")).toBeDefined();

  jest.useFakeTimers();
  try {
    fireEvent.click(screen.getByLabelText("Add Upload · Video to timeline"));
    act(() => jest.advanceTimersByTime(500));
    const patch = patchEditDocument.mock.calls[0]![2];
    expect(patch.operations).toHaveLength(1);
    expect(patch.operations[0]).toMatchObject({
      kind: "add_clip_from_asset",
      asset_id: "asset_first",
      track_id: "track_main",
    });
  } finally {
    jest.useRealTimers();
  }
});

test("stays in Simple mode after a version 2 autosave completes", async () => {
  const { upgradedTextDocument } = await import("./timeline-test-fixtures");
  const upgraded = upgradedTextDocument() as EditDocument;
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: { ...upgraded, revision: upgraded.revision + 1 },
    }),
  );
  await renderTimelineStudio(upgraded, patchEditDocument);
  fireEvent.click(screen.getByRole("button", { name: "Story" }));

  await completeAutosave(() =>
    fireEvent.change(screen.getByLabelText("Heading"), { target: { value: "Saved heading" } }),
  );

  expect(patchEditDocument).toHaveBeenCalledTimes(1);
  await waitFor(() => expect(screen.getByText("Saved")).toBeDefined());
  expect(screen.getByRole("button", { name: "Story" }).getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByLabelText("Heading")).toBeDefined();
});

test("keeps a loaded asset addable after an earlier asset edit saves", async () => {
  const { patchEditDocument } = await renderPagedAssetStudio();
  fireEvent.click(await screen.findByRole("button", { name: "Load more assets" }));
  expect(await screen.findByLabelText("Add Upload · Video · 2 to timeline")).toBeDefined();

  await completeAutosave(() => fireEvent.click(screen.getByLabelText("Add Upload · Video to timeline")));
  expect(patchEditDocument).toHaveBeenCalledTimes(1);

  await completeAutosave(() => fireEvent.click(screen.getByLabelText("Add Upload · Video · 2 to timeline")));

  expect(patchEditDocument).toHaveBeenCalledTimes(2);
  expect(patchEditDocument.mock.calls[1]![2].operations[0]).toMatchObject({
    kind: "add_clip_from_asset",
    asset_id: "asset_second",
  });
});

/** The render half of the control plane, as Studio degrades without it. */
function renderClientFixture() {
  const capability = {
    available: true,
    preset_id: "standard_vertical_mp4_v1" as const,
    renderer_version: "remotion-4.0.538",
  };
  return {
    getRenderCapability: mock(async () => capability),
    createRenderJob: mock(async () => ({
      render_job_id: "rj_001",
      project_id: "project_001",
      document_id: "document_001",
      document_revision: 2,
      status: "preparing" as const,
      template_id: "vertical_text_story" as const,
      template_version: 1 as const,
      preset_id: "standard_vertical_mp4_v1" as const,
      renderer_version: "remotion-4.0.538",
      created_at: "2026-09-21T10:00:00Z",
    })),
    listRenderJobs: mock(async () => ({ jobs: [], next_cursor: null })),
    getRenderJob: mock(async () => { throw new Error("no job"); }),
    cancelRenderJob: mock(async () => { throw new Error("no job"); }),
    retryRenderJob: mock(async () => { throw new Error("no job"); }),
    downloadRenderOutput: mock(async () => new Blob([])),
    cleanupRenderArtifacts: mock(async () => { throw new Error("no job"); }),
  };
}

test("offers render controls only where the control plane supports rendering", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const base = {
    ...promptClientBase,
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
  };

  const { unmount } = render(
    <GuidedStudio client={base} projectId="project_001" documentId="document_001" onBack={() => {}} />,
  );
  expect(await screen.findByLabelText("Heading")).toBeDefined();
  expect(screen.queryByRole("button", { name: /^Render revision \d+$/ })).toBeNull();
  unmount();

  render(
    <GuidedStudio
      client={{ ...base, ...renderClientFixture() }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  expect(await screen.findByLabelText("Heading")).toBeDefined();
  job("Render");
  expect(await screen.findByRole("button", { name: /^Render revision \d+$/ })).toBeDefined();
  // The editor, the other destinations, and preview are untouched by the new surface.
  expect(screen.getByLabelText("Heading")).toBeDefined();
  expect(jobButton("Review")).toBeDefined();
  expect(screen.getByLabelText("Draft preview")).toBeDefined();
});

test("an unsaved draft cannot be rendered and says so", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const client = {
    ...promptClientBase,
    ...renderClientFixture(),
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(() => new Promise<never>(() => {})),
  };

  render(
    <GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />,
  );
  const heading = await screen.findByLabelText("Heading");
  job("Render");
  const button = await screen.findByRole("button", { name: /^Render revision \d+$/ });
  expect(button).toHaveProperty("disabled", false);

  fireEvent.change(heading, { target: { value: "Edited heading" } });

  await waitFor(() => expect(button).toHaveProperty("disabled", true));
  const reason = button.getAttribute("aria-describedby");
  expect(window.document.getElementById(reason as string)?.textContent).toBe(
    "Save your changes before rendering.",
  );
  expect(client.createRenderJob).toHaveBeenCalledTimes(0);
});

test("a saved revision is what gets rendered, and the draft never leaves the editor", async () => {
  let resolveSave: (value: { kind: "saved"; document: EditDocument }) => void = () => {};
  const patchEditDocument = mock(
    () => new Promise<{ kind: "saved"; document: EditDocument }>((resolve) => { resolveSave = resolve; }),
  );
  const { GuidedStudio } = await import("./GuidedStudio");
  const client = {
    ...promptClientBase,
    ...renderClientFixture(),
    getEditDocument: mock(async () => document),
    patchEditDocument,
  };
  const { container } = render(
    <GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />,
  );
  const heading = await screen.findByLabelText("Heading");
  expect(client.listRenderJobs).toHaveBeenCalledTimes(1);

  jest.useFakeTimers();
  try {
    fireEvent.change(heading, { target: { value: "Edited heading" } });
    act(() => jest.advanceTimersByTime(500));
    await act(async () => {
      resolveSave({
        kind: "saved",
        document: {
          ...document,
          revision: 2,
          clips: [{ ...document.clips[0], heading: "Edited heading", ownership: "user_edited" as const }],
        },
      });
    });
  } finally {
    jest.useRealTimers();
  }

  // A new saved revision is a new render generation: the panel re-reads.
  await waitFor(() => expect(client.listRenderJobs).toHaveBeenCalledTimes(2));

  job("Render");
  fireEvent.click(screen.getByRole("button", { name: /^Render revision \d+$/ }));
  const confirmation = screen.getByRole("group", { name: "Render this version?" });
  expect(confirmation.textContent).not.toContain("Edited heading");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Start render" }));
  });

  expect(client.createRenderJob).toHaveBeenCalledWith("project_001", expect.any(String), {
    document_id: "document_001",
    document_revision: 2,
  });
  // The draft still belongs to the editor alone.
  expect((screen.getByLabelText("Heading") as HTMLInputElement).value).toBe("Edited heading");
  expect(container.textContent).not.toContain("Original heading");
});

test("the render confirmation names the template the saved document carries", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  // A template identity neither Studio nor the panel is allowed to assume.
  const future = {
    ...document,
    template: { template_id: "future_template", version: 3 },
  } as unknown as EditDocument;
  const client = {
    ...promptClientBase,
    ...renderClientFixture(),
    getEditDocument: mock(async () => future),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document: future })),
  };

  render(
    <GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />,
  );
  await screen.findByLabelText("Draft preview");
  job("Render");
  const button = await screen.findByRole("button", { name: /^Render revision \d+$/ });
  await waitFor(() => expect(button).toHaveProperty("disabled", false));
  fireEvent.click(button);

  const confirmation = screen.getByRole("group", { name: "Render this version?" });
  expect(confirmation.textContent).toContain("future_template");
  expect(confirmation.textContent).toContain("3");
  expect(confirmation.textContent).not.toContain("vertical_text_story");
});

test("a blocking timeline issue stops a render whose text is valid", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const gapped = timelineDocument();
  // The main track no longer starts at zero: one structural issue, text untouched.
  gapped.clips![0]!.from_frame = 10;
  const client = {
    ...promptClientBase,
    ...renderClientFixture(),
    getEditDocument: mock(async () => gapped as EditDocument),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document: gapped as EditDocument })),
    listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
    createEditorPreviewCapability: mock(async () => ({
      preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
      expires_at: "2026-09-20T00:00:00Z",
    })),
  };

  render(
    <GuidedStudio client={client} projectId="project_001" documentId="document_002" onBack={() => {}} />,
  );
  await screen.findByLabelText("Draft preview");
  job("Render");
  const button = await screen.findByRole("button", { name: /^Render revision \d+$/ });

  expect(button).toHaveProperty("disabled", true);
  const reason = button.getAttribute("aria-describedby");
  expect(window.document.getElementById(reason as string)?.textContent).toBe(
    "Fix 1 timeline issue before rendering.",
  );
  expect(client.createRenderJob).toHaveBeenCalledTimes(0);
});

test("names the document's own project and its saved revision in every job", async () => {
  let resolveSave: (value: { kind: "saved"; document: EditDocument }) => void = () => {};
  const patchEditDocument = mock(
    () => new Promise<{ kind: "saved"; document: EditDocument }>((resolve) => { resolveSave = resolve; }),
  );
  // The document belongs to another project than the one Studio was opened with.
  const foreign = { ...document, project_id: "project_other" };
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => foreign), patchEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  const header = globalThis.document.querySelector<HTMLElement>('section[aria-label="Guided Studio"] > header')!;
  const shows = (text: string) => within(header).getByText(text).closest("[hidden]") === null;

  for (const name of ["Edit", "Review", "Render"]) {
    job(name);
    expect(shows("Project project_other")).toBe(true);
    expect(shows("Saved revision 1")).toBe(true);
  }
  expect(within(header).queryByText("Project project_001") === null).toBe(true);

  job("Edit");
  jest.useFakeTimers();
  try {
    fireEvent.change(heading, { target: { value: "Edited heading" } });
    act(() => jest.advanceTimersByTime(500));
    // An unsaved edit does not change the saved revision the header names.
    expect(shows("Saved revision 1")).toBe(true);
    await act(async () => {
      resolveSave({ kind: "saved", document: { ...foreign, revision: 2, clips: [{ ...document.clips[0], heading: "Edited heading" }] } });
    });
    expect(shows("Saved revision 2")).toBe(true);
    expect(within(header).queryByText("Saved revision 1") === null).toBe(true);
  } finally {
    jest.useRealTimers();
  }
});

test("edits the first text clip of a scene whose first clip is media", async () => {
  const { sceneStripDocument } = await import("./timeline-test-fixtures");
  const mediaFirst = sceneStripDocument();
  mediaFirst.scenes[0]!.clip_ids = ["clip_still"];
  mediaFirst.clips!.find((clip) => clip.clip_id === "clip_still")!.scene_id = "scene_001";
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: mediaFirst as EditDocument,
    }),
  );
  await renderTimelineStudio(mediaFirst as EditDocument, patchEditDocument);

  fireEvent.click(screen.getByRole("button", { name: "Story" }));
  const heading = screen.getByLabelText("Heading") as HTMLInputElement;
  expect(heading.value).toBe("Heading 1");

  jest.useFakeTimers();
  fireEvent.change(heading, { target: { value: "Media-first heading" } });
  act(() => jest.advanceTimersByTime(500));

  expect(patchEditDocument.mock.calls[0]![2].operations).toEqual([
    expect.objectContaining({ kind: "replace_text", clip_id: "clip_001", value: "Media-first heading" }),
  ]);
});

test("captions and scene audio added in Simple mode persist in one autosave", async () => {
  const { sceneStripDocument } = await import("./timeline-test-fixtures");
  const strip = sceneStripDocument();
  strip.tracks.push({ ...strip.tracks[0]!, track_id: "track_caption", kind: "caption", label: "Captions", order: 4, clip_ids: [] });
  const voice = { ...assetPage("asset_voice", null).assets[0]!, kind: "audio" as const, media_type: "audio/mpeg", duration_in_frames: 20 };
  const listEditorAssets = mock(async () => ({ assets: [voice], next_cursor: null }));
  const createEditorPreviewCapability = mock(async () => ({
    preview_url: "/api/v1/projects/project_001/editor-assets/asset_voice/preview",
    expires_at: "2026-09-20T00:00:00Z",
  }));
  const patchEditDocument = mock(
    async (_projectId: string, _documentId: string, _patch: EditDocumentPatch) => ({
      kind: "saved" as const,
      document: strip as EditDocument,
    }),
  );
  const { GuidedStudio } = await import("./GuidedStudio");
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        listEditorAssets,
        createEditorPreviewCapability,
        getEditDocument: mock(async () => strip as EditDocument),
        patchEditDocument,
      }}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Story" }));
  fireEvent.click(screen.getByText("Scene audio", { selector: "summary" }));
  fireEvent.click(screen.getByText("Edit captions and timing", { selector: "summary" }));
  const addAudio = await screen.findByRole("button", { name: "Add audio to scene" });

  fireEvent.change(screen.getByLabelText("New caption"), { target: { value: "Hello" } });
  fireEvent.click(screen.getByRole("button", { name: "Add caption" }));
  fireEvent.click(addAudio);
  await act(async () => {});
  await completeAutosave(() => fireEvent.click(screen.getByLabelText("Mute Music lane")));

  expect(listEditorAssets).toHaveBeenCalledWith("project_001", undefined, 50);
  expect(createEditorPreviewCapability).toHaveBeenCalledWith("project_001", "asset_voice");
  expect(patchEditDocument.mock.calls[0]![2].operations).toEqual([
    expect.objectContaining({ kind: "add_caption_clip", scene_id: "scene_001", track_id: "track_caption", text: "Hello" }),
    expect.objectContaining({
      kind: "add_clip_from_asset",
      asset_id: "asset_voice",
      track_id: "track_music",
      scene_id: "scene_001",
      from_frame: 0,
      duration_in_frames: 20,
    }),
    expect.objectContaining({ kind: "set_track_muted", track_id: "track_music", muted: true }),
  ]);
});

test("Studio offers no rename control it cannot honour", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const client = {
    ...promptClientBase,
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
  };
  render(<GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />);
  expect(await screen.findByLabelText("Heading")).toBeDefined();
  // Boolean(): a failing toBeNull() makes Bun print the whole element and crash (exit 127).
  expect(Boolean(screen.queryByRole("button", { name: "Rename document unavailable" }))).toBe(false);
});

test("the top bar reads in Indonesian", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const client = {
    ...promptClientBase,
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
  };

  render(<GuidedStudio client={client} projectId="project_001" documentId="document_001" onBack={() => {}} />, { locale: "id" });

  expect(await screen.findByRole("button", { name: "Kembali ke Studio" })).toBeDefined();
  expect(screen.getByText("Tersimpan")).toBeDefined();
  expect(screen.getByRole("button", { name: "Urungkan" })).toBeDefined();
  expect(within(screen.getByRole("navigation", { name: "Bagian Studio" })).getByRole("button", { name: "Tinjau" })).toBeDefined();
});

test("Timeline names assets from the run's materials, as Story does", async () => {
  // Materials loaded only in Story, so Timeline called every card "Upload · Image" (walk, 2026-11-01).
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const document = timelineDocument() as EditDocument;
  render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        listEditorAssets: mock(async () => ({
          assets: [{ asset_id: "asset_video", project_id: "project_001", kind: "video" as const, media_type: "video/mp4", has_audio: true, validation_state: "ready" as const, duration_in_frames: 60 }],
          next_cursor: null,
        })),
        getStudioMaterials: mock(async () => ({
          document_id: "document_002",
          provenance_available: true,
          items: [{ item_id: "comment_card_000", role: "comment_card" as const, label: "card", owner_handle: "@lailynisfa", media_kind: "video" as const, disposition: "attached" as const, asset_id: "asset_video" }],
          figures: [],
        })),
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
      }}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  fireEvent.click(await screen.findByRole("button", { name: "Timeline" }));

  expect(await screen.findByRole("button", { name: "Add Comment card · @lailynisfa to timeline" })).toBeDefined();
});

const narrationCalls = {
  startNarration: mock(async () => { throw new Error("unused"); }),
  decideNarration: mock(async () => { throw new Error("unused"); }),
  editNarrationBeat: mock(async () => { throw new Error("unused"); }),
  revoiceNarrationBeat: mock(async () => { throw new Error("unused"); }),
  cancelNarration: mock(async () => { throw new Error("unused"); }),
  restartNarration: mock(async () => { throw new Error("unused"); }),
};

test("Create narration waits until the draft's narration has been read", async () => {
  // e2e audit 2026-11-02: a narrated draft offered Create narration until its state arrived.
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const { StudioImportRequestError } = await import("@/api/control-plane");
  const document = timelineDocument() as EditDocument;
  let refuse!: (error: unknown) => void;
  const getNarration = mock(() => new Promise<never>((_, reject) => (refuse = reject)));
  render(
    <GuidedStudio
      client={{ ...promptClientBase, ...advancedClientBase, ...narrationCalls, getNarration, getEditDocument: mock(async () => document), patchEditDocument: mock(async () => ({ kind: "saved" as const, document })) } as never}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  await screen.findByRole("button", { name: "Timeline" });
  await waitFor(() => expect(getNarration).toHaveBeenCalled());

  expect(screen.queryByRole("button", { name: "Create narration" })).toBeNull();
  // Its place is held meanwhile, so the header does not jump when the answer arrives.
  expect(screen.getByRole("status", { name: "Checking narration…" })).toBeDefined();
  refuse(new StudioImportRequestError(404));
  expect(await screen.findByRole("button", { name: "Create narration" })).toBeDefined();
  expect(screen.queryByRole("status", { name: "Checking narration…" })).toBeNull();
});

test("Scene media does not call the main video an upload while materials load", async () => {
  // e2e audit 2026-11-02: it read "Upload · Video" until the materials arrived.
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const document = timelineDocument() as EditDocument;
  render(
    <GuidedStudio
      client={{ ...promptClientBase, ...advancedClientBase, getStudioMaterials: mock(() => new Promise<never>(() => {})), getEditDocument: mock(async () => document), patchEditDocument: mock(async () => ({ kind: "saved" as const, document })) } as never}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  const media = await screen.findByRole("region", { name: "Scene media" });

  expect(media.textContent).not.toContain("Upload");
});

test("previews stay readable while the draft stays open", async () => {
  // Each piece of a video is read on the asset's cookie, which lasted five minutes: after ten
  // minutes on a narration every read of the main video was refused (stage1, 2026-11-03).
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const document_ = timelineDocument() as EditDocument;
  const createEditorPreviewCapability = mock(async () => ({
    preview_url: "/api/v1/projects/project_001/editor-assets/asset_video/preview",
    expires_at: "2099-01-01T00:00:00Z",
  }));
  const intervals = jest.spyOn(globalThis, "setInterval");
  const stopped = jest.spyOn(globalThis, "clearInterval");
  const { unmount } = render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        ...advancedClientBase,
        listEditorAssets: mock(async () => ({ assets: [], next_cursor: null })),
        createEditorPreviewCapability,
        getEditDocument: mock(async () => document_),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document: document_ })),
      }}
      projectId="project_001"
      documentId="document_002"
      onBack={() => {}}
    />,
  );
  await waitFor(() => expect(createEditorPreviewCapability).toHaveBeenCalledWith("project_001", "asset_video"));
  await act(async () => {});
  const asked = () => createEditorPreviewCapability.mock.calls.length;
  const first = asked();

  const call = intervals.mock.calls.find(([, ms]) => (ms ?? 0) > 60_000 && (ms ?? 0) < 300_000);
  const index = intervals.mock.calls.indexOf(call!);
  (call![0] as () => void)();
  expect(asked()).toBeGreaterThan(first);

  // Coming back soon after a renewal asks for nothing; coming back past the cookie renews at once.
  const renewed = asked();
  const visibility = Object.getOwnPropertyDescriptor(window.document, "visibilityState");
  Object.defineProperty(window.document, "visibilityState", { configurable: true, get: () => "visible" });
  window.document.dispatchEvent(new Event("visibilitychange"));
  expect(asked()).toBe(renewed);
  setSystemTime(new Date(Date.now() + 301_000));
  window.document.dispatchEvent(new Event("visibilitychange"));
  expect(asked()).toBeGreaterThan(renewed);
  setSystemTime();
  if (visibility) Object.defineProperty(window.document, "visibilityState", visibility);
  else delete (window.document as { visibilityState?: unknown }).visibilityState;

  unmount();
  // By identity: two timers compare equal, so toHaveBeenCalledWith passes on any other one.
  const timer = intervals.mock.results[index]!.value;
  expect(stopped.mock.calls.some(([id]) => id === timer)).toBe(true);
  intervals.mockRestore();
  stopped.mockRestore();
});

// Found by the write audit.
test("write-audit: a save the document refuses says so and offers Undo, not a connection retry", async () => {
  const patchEditDocument = mock(async () => {
    throw new Error("edit_refused");
  });
  const { GuidedStudio } = await import("./GuidedStudio");
  const user = userEvent.setup();
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  await user.type(await screen.findByLabelText("Heading"), " updated");

  const alert = await screen.findByRole("alert", {}, { timeout: 1_000 });
  expect(alert.textContent).toContain("could not be saved");
  expect(alert.textContent).not.toContain("connection");
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
});

test("write-audit: Undo after an autosave restores the revision it replaced", async () => {
  const restored = { ...document, revision: document.revision + 2 };
  const restoreEditDocument = mock(async () => ({ kind: "saved" as const, document: restored }));
  const patchEditDocument = mock(async (_p: string, _d: string, patch: EditDocumentPatch) => ({
    kind: "saved" as const,
    document: { ...document, revision: patch.base_revision + 1 },
  }));
  const { GuidedStudio } = await import("./GuidedStudio");
  const user = userEvent.setup();
  render(
    <GuidedStudio
      client={{ ...promptClientBase, getEditDocument: mock(async () => document), patchEditDocument, restoreEditDocument }}
      projectId="project_001"
      documentId="document_001"
      onBack={() => {}}
    />,
  );
  await user.type(await screen.findByLabelText("Heading"), " updated");
  await waitFor(() => expect(patchEditDocument).toHaveBeenCalled(), { timeout: 2_000 });
  const undo = screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement;
  await waitFor(() => expect(undo.disabled).toBe(false));
  await act(async () => {
    fireEvent.click(undo);
  });

  expect(restoreEditDocument).toHaveBeenCalledWith("project_001", "document_001", {
    base_revision: document.revision + 1,
    revision: document.revision,
  });
});

test("write-audit: adding an asset loads its preview without a trip to Preview", async () => {
  const { createEditorPreviewCapability } = advancedClientBase as unknown as {
    createEditorPreviewCapability: ReturnType<typeof mock>;
  };
  createEditorPreviewCapability.mockClear();
  await renderPagedAssetStudio();
  fireEvent.click(await screen.findByLabelText("Add Upload · Video to timeline"));
  await waitFor(() => expect(createEditorPreviewCapability).toHaveBeenCalledWith("project_001", "asset_first"));
});

test("write-audit: Add says so when it cuts a clip to fit", async () => {
  const long = { ...assetPage("asset_long", null).assets[0]!, duration_in_frames: 100_000 };
  await mountAdvanced({ listEditorAssets: mock(async () => ({ assets: [long], next_cursor: null })) });
  fireEvent.click(await screen.findByLabelText("Add Upload · Video to timeline"));

  const notice = await screen.findByRole("status", { name: "Clip placed" });
  expect(notice.textContent).toContain("3333.3 s");
});

test("write-audit: the top bar's title follows the heading as it is typed", async () => {
  const { GuidedStudio } = await import("./GuidedStudio");
  const user = userEvent.setup();
  const { container } = render(
    <GuidedStudio
      client={{
        ...promptClientBase,
        getEditDocument: mock(async () => document),
        patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
      }}
      projectId="project_001"
      documentId="document_001"
      documentTitle="Old title"
      onBack={() => {}}
    />,
  );
  const heading = await screen.findByLabelText("Heading");
  await user.clear(heading);
  await user.type(heading, "New title");
  expect(container.querySelector(".studio-topbar span[title]")?.getAttribute("title")).toBe("New title");
});

// Final review 2026-11-08: L's speed lasts only while playing; a pause from anywhere brings it back to 1.
test("L speeds the preview up, and any pause brings it back to normal speed", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  previewPlayer = new FakePlayer();
  await renderTimelineStudio(timelineDocument() as EditDocument);
  const player = previewPlayer;
  const rate = () => screen.getByLabelText("Draft preview").getAttribute("data-rate");

  fireEvent.keyDown(window, { key: "l" });
  act(() => player.emit("play"));
  fireEvent.keyDown(window, { key: "l" });
  expect(rate()).toBe("2");
  act(() => player.emit("pause"));
  expect(rate()).toBe("1");
});

// Tier 3b: each asset's filmstrip or peaks, asked for once in Timeline mode.
const GLANCE = { asset_id: "asset_music", strip: null, peaks: { seconds_per_peak: 0.1, values: [10, 40] } };

test("Timeline asks for each asset's glance once", async () => {
  const getEditorAssetGlance = mock(async (_projectId: string, assetId: string) => ({ ...GLANCE, asset_id: assetId }));
  await mountAdvanced({ getEditorAssetGlance });
  await waitFor(() => expect(getEditorAssetGlance).toHaveBeenCalledTimes(2));
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  await act(async () => {});
  expect(getEditorAssetGlance.mock.calls.map(([, assetId]) => assetId).sort()).toEqual(["asset_music", "asset_video"]);
});

test("a refused glance leaves the timeline as it was", async () => {
  await mountAdvanced({ getEditorAssetGlance: mock(async () => Promise.reject(new Error("503"))) });
  await act(async () => {});
  expect(screen.queryByTestId("clip-filmstrip")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Mute Music" }));
  expect(screen.getByRole("button", { name: "Unmute Music" })).toBeDefined();
});

test("at most two glances are asked for at a time", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const doc = timelineDocument();
  doc.asset_refs = [...doc.asset_refs!, { ...doc.asset_refs![0]!, asset_id: "asset_third" }];
  const getEditorAssetGlance = mock(() => new Promise<never>(() => {}));
  await mountAdvanced({ getEditorAssetGlance, getEditDocument: mock(async () => doc as EditDocument) });
  await act(async () => {});
  expect(getEditorAssetGlance).toHaveBeenCalledTimes(2);
});

// Style templates (spec 2026-11-10): applying a style, undoing it, and its cut preview.
test("a style is applied from the header, one Undo undoes it and Redo applies it again", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const { StudioImportRequestError } = await import("@/api/control-plane");
  const document = timelineDocument() as EditDocument;
  const styled = { ...document, revision: document.revision + 1, style: { template_id: "style_a", revision: 1 } } as EditDocument;
  const undoStyle = mock(async () => ({ kind: "saved" as const, document: { ...document, revision: document.revision + 2 } }));
  const restoreEditDocument = mock(async () => ({ kind: "saved" as const, document }));
  const client = {
    ...promptClientBase,
    ...advancedClientBase,
    ...narrationCalls,
    getNarration: mock(async () => {
      throw new StudioImportRequestError(404);
    }),
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
    restoreEditDocument,
    listStyles: mock(async () => [
      { template_id: "style_a", name: "Style A", revision: 1 },
      { template_id: "style_b", name: "Style B", revision: 1 },
    ]),
    applyStyle: mock(async () => ({ document: styled, previous_revision: document.revision, narration: null, narration_refused: "prompt_not_configured" })),
    undoStyle,
  };
  render(<GuidedStudio client={client as never} projectId="project_001" documentId="document_002" onBack={() => {}} />);
  await screen.findByRole("option", { name: "Style A" });
  fireEvent.change(screen.getByLabelText("Style"), { target: { value: "style_a" } });
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Apply style" }));
  });
  await waitFor(() => expect((screen.getByLabelText("Style") as HTMLSelectElement).value).toBe("style_a"));
  const undo = screen.getByRole("button", { name: "Undo" }) as HTMLButtonElement;
  await waitFor(() => expect(undo.disabled).toBe(false));
  await act(async () => {
    fireEvent.click(undo);
  });
  expect(undoStyle).toHaveBeenCalledWith("project_001", "document_002", {
    base_revision: document.revision + 1,
    revision: document.revision,
  });
  // Deferred minor (2026-11-10): Redo goes through the style again, so its narration starts.
  const redo = screen.getByRole("button", { name: "Redo" }) as HTMLButtonElement;
  await waitFor(() => expect(redo.disabled).toBe(false));
  await act(async () => {
    fireEvent.click(redo);
  });
  expect(client.applyStyle).toHaveBeenLastCalledWith("project_001", "document_002", {
    template_id: "style_a",
    base_revision: document.revision + 2,
  });
  expect(restoreEditDocument).not.toHaveBeenCalled();
});

test("while a styled draft's script waits, the preview plays its cut preview", async () => {
  const { timelineDocument } = await import("./timeline-test-fixtures");
  const { GuidedStudio } = await import("./GuidedStudio");
  const document = { ...(timelineDocument() as EditDocument), style: { template_id: "style_b", revision: 1 } } as EditDocument;
  const getNarrationPreview = mock(async () => document);
  const client = {
    ...promptClientBase,
    ...advancedClientBase,
    ...narrationCalls,
    getNarration: mock(async () => ({
      document_id: "document_002",
      workflow_id: "narration/document_002/1",
      status: "awaiting_approval",
      script: { beats: [{ beat: "main", text: "Satu dua tiga." }], sfx_cues: [] },
      unsupported: {},
      stale_beats: [],
    })),
    getEditDocument: mock(async () => document),
    patchEditDocument: mock(async () => ({ kind: "saved" as const, document })),
    getNarrationPreview,
  };
  render(<GuidedStudio client={client as never} projectId="project_001" documentId="document_002" onBack={() => {}} />);
  await waitFor(() => expect(getNarrationPreview).toHaveBeenCalledWith("project_001", "document_002"));
});
