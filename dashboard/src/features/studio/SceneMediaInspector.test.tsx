import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { render } from "@/test-render";
import { SceneMediaInspector } from "./SceneMediaInspector";
import { timelineDocument } from "./timeline-test-fixtures";

afterEach(cleanup);

test("design media surfaces remain honest and never emit unsupported operations", () => {
  const document = timelineDocument();
  render(<SceneMediaInspector document={document} sceneId={document.scenes[0]!.scene_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Replace" }));
  expect(screen.getByRole("dialog", { name: "Replace media" })).toBeDefined();
  expect(screen.getByText(/Replacing media is not available/)).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Close Replace media" }));
  fireEvent.click(screen.getByRole("button", { name: "Adjust" }));
  expect(screen.getByRole("dialog", { name: "Adjust media" })).toBeDefined();
  expect(screen.getByLabelText("Fit").hasAttribute("disabled")).toBe(true);
  expect(screen.getByRole("button", { name: "Apply changes" }).hasAttribute("disabled")).toBe(true);
});

test("media details only display document metadata, without sample filenames or locators", () => {
  const source = { ...timelineDocument(), clips: [], asset_refs: [] };
  render(<SceneMediaInspector document={source} sceneId={source.scenes[0]!.scene_id} />);
  fireEvent.click(screen.getByRole("button", { name: "Media details" }));
  expect(screen.getByRole("dialog", { name: "Media details" })).toBeDefined();
  expect(screen.getAllByText("No media attached").length).toBeGreaterThan(0);
  expect(screen.queryByText("gion-pagoda-street.mp4")).toBeNull();
});

test("a scene that lists only its text still finds the main video under it, by name", () => {
  // e2e audit 2026-11-02, finding 3: a narrated draft read "No media attached" over its main video.
  const source = timelineDocument();
  const document = { ...source, scenes: [{ ...source.scenes[0]!, clip_ids: [] }] };
  render(<SceneMediaInspector document={document} sceneId="scene_001" labelOf={(assetId) => (assetId === "asset_video" ? "Main video · @creator" : "?")} />);

  expect(screen.queryByText("No media attached")).toBeNull();
  expect(screen.getByText("Main video · @creator")).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Media details" }));
  expect(screen.queryByText("asset_video")).toBeNull();
});

test("without a name the media reads as its kind, never as an id", () => {
  const document = timelineDocument();
  render(<SceneMediaInspector document={document} sceneId="scene_001" />);

  fireEvent.click(screen.getByRole("button", { name: "Media details" }));
  expect(screen.queryByText("asset_video")).toBeNull();
});

test("the media panel and its dialogs speak Indonesian", () => {
  const document = timelineDocument();
  render(<SceneMediaInspector document={document} sceneId={document.scenes[0]!.scene_id} />, { locale: "id" });

  expect(screen.getByRole("region", { name: "Media scene" })).toBeDefined();
  fireEvent.click(screen.getByRole("button", { name: "Ganti" }));
  expect(screen.getByRole("dialog", { name: "Ganti media" })).toBeDefined();
  expect(screen.getByText("Aset siap")).toBeDefined();
  expect(screen.queryByText(/Replacing media/)).toBeNull();
});

// Spec 2026-11-08 §5.1: Replace media works where the Story offers it.
test("with assets and a handler, Replace offers the ready videos and hands back the choice", () => {
  const document = timelineDocument();
  const replaced: [string, string][] = [];
  render(
    <SceneMediaInspector
      document={document}
      sceneId={document.scenes[0]!.scene_id}
      labelOf={(assetId) => (assetId === "asset_other" ? "Footage · @someone" : "Main video")}
      assets={[{ asset_id: "asset_other", project_id: "project_001", kind: "video", has_audio: true, media_type: "video/mp4", validation_state: "ready" }]}
      onReplace={(clipId, assetId) => replaced.push([clipId, assetId])}
    />,
  );
  fireEvent.click(screen.getByRole("button", { name: "Replace" }));
  fireEvent.click(screen.getByRole("button", { name: "Use Footage · @someone" }));
  expect(replaced).toEqual([["clip_main", "asset_other"]]);
});
