import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
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
