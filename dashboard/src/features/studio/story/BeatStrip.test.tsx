/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";

import { BeatStrip } from "./BeatStrip";
import { computeBeats } from "./story_beats";
import { storyDocument, storyInventory } from "./story-test-fixtures";

afterEach(cleanup);

const beats = computeBeats(storyDocument(), storyInventory());

test("one tile per beat with its name and length, and the total on the left", () => {
  render(<BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} />);

  const tiles = screen.getAllByRole("button", { name: /Hook|Main|Reactions|Footage/ });
  expect(tiles.map((tile) => tile.getAttribute("data-beat"))).toEqual(["hook", "main", "reactions", "footage"]);
  expect(screen.getByRole("button", { name: /^Hook/ }).textContent).toContain("4.0 s");
  expect(screen.getByText("Total 10.0 s")).toBeDefined();
});

test("choosing a tile selects its beat", () => {
  const onSelect = mock((_id: string) => {});
  const { rerender } = render(<BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={onSelect} />);

  fireEvent.click(screen.getByRole("button", { name: /^Reactions/ }));
  expect(onSelect).toHaveBeenCalledWith("reactions");

  rerender(<BeatStrip beats={beats} fps={30} totalFrames={300} selected="reactions" onSelect={onSelect} />);
  const selected = screen.getByRole("button", { name: /^Reactions/ });
  expect(selected.getAttribute("aria-pressed")).toBe("true");
  expect(selected.className).toContain("border-copper");
});

test("a beat with a missing material shows a red dot", () => {
  render(<BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} />);

  expect(screen.getByRole("button", { name: /^Reactions/ }).textContent).toContain("1 missing");
  expect(screen.getByRole("button", { name: /^Main/ }).textContent).not.toContain("missing");
});

test("the strip speaks Indonesian", () => {
  render(<BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} />, { locale: "id" });

  expect(screen.getByRole("button", { name: /^Reaksi/ }).textContent).toContain("1 hilang");
  expect(screen.getByText("Total 10.0 dtk")).toBeDefined();
});

test("a tile shows thumbnails of its first clips", () => {
  const previews = { asset_clip_comment_card_000: "/p/card0.png", asset_clip_comment_card_001: "/p/card1.png" };
  const { container } = render(
    <BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} document={storyDocument()} previews={previews} />,
  );

  const reactions = container.querySelector('[data-beat="reactions"]')!;
  expect([...reactions.querySelectorAll("img")].map((image) => image.getAttribute("src"))).toEqual(["/p/card0.png", "/p/card1.png"]);
});

const dragged = (data: Record<string, string>) => ({
  dataTransfer: { types: Object.keys(data), getData: (type: string) => data[type] ?? "", dropEffect: "" },
});

test("a material dragged over a tile shows where it will land, and drops there", () => {
  const onDrop = mock((_beat: string, _data: string) => {});
  const { container } = render(
    <BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} onDropMaterial={onDrop} />,
  );
  const reactions = container.querySelector('[data-beat="reactions"]')!;
  const material = { "application/x-thoth-material": "comment_card_003" };

  fireEvent.dragOver(reactions, dragged(material));
  expect(reactions.className).toContain("border-dashed");
  expect(reactions.textContent).toContain("+ Add to Reactions");

  fireEvent.drop(reactions, dragged(material));
  expect(onDrop).toHaveBeenCalledWith("reactions", "comment_card_003");
  expect(reactions.className).not.toContain("border-dashed");
});

test("text beats take no dropped media", () => {
  const { container } = render(
    <BeatStrip beats={beats} fps={30} totalFrames={300} selected={null} onSelect={() => {}} onDropMaterial={() => {}} />,
  );
  const hook = container.querySelector('[data-beat="hook"]')!;

  fireEvent.dragOver(hook, dragged({ "application/x-thoth-material": "comment_card_003" }));
  expect(hook.className).not.toContain("border-dashed");
});
