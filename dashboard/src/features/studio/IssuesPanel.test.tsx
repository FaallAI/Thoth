/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { render } from "@/test-render";

import type { EditorAction, EditorMode } from "./editor_state";
import { IssuesBar } from "./IssuesPanel";
import { timelineDocument } from "./timeline-test-fixtures";

afterEach(cleanup);

/** A document whose main track starts late and whose music runs past the canvas. */
function brokenDocument() {
  const document = timelineDocument();
  document.clips![0]!.from_frame = 30;
  document.clips![2]!.duration_in_frames = 200;
  return document;
}

/**
 * Render the panel next to the elements it focuses, so the stable DOM IDs the
 * timeline publishes are the ones under test.
 */
function mount(mode: EditorMode = "advanced", selectedIssueId = "") {
  const actions: EditorAction[] = [];
  render(
    <>
      <IssuesBar
        document={brokenDocument()}
        selectedIssueId={selectedIssueId}
        mode={mode}
        dispatch={(action) => actions.push(action)}
      />
      <button type="button" id="timeline-clip-clip_main">
        target one
      </button>
      <button type="button" id="timeline-clip-clip_music">
        target two
      </button>
    </>,
  );
  return { actions };
}

/** Open the list behind the bar, the way a person reviews the issues. */
const review = () => fireEvent.click(screen.getByRole("button", { name: "Review issues" }));

test("the bar counts the warnings and says the first one", () => {
  mount();
  const bar = screen.getByRole("region", { name: "Timeline issues" });
  expect(bar.textContent).toContain("2 warnings");
  expect(bar.textContent).toContain("Main video: a clip starts after a gap");
  expect(screen.queryByRole("listitem")).toBeNull();
});

test("Review issues opens and closes the list of every issue in readable language", () => {
  mount();
  const button = screen.getByRole("button", { name: "Review issues" });
  expect(button.getAttribute("aria-expanded")).toBe("false");
  review();
  expect(button.getAttribute("aria-expanded")).toBe("true");
  const items = screen.getAllByRole("listitem");
  expect(items).toHaveLength(2);
  expect(items[0]!.textContent).toContain("Main video: a clip starts after a gap");
  expect(items[1]!.textContent).toContain("Music: a clip runs past the end of the video");
  review();
  expect(screen.queryByRole("listitem")).toBeNull();
});

test("says so when nothing is wrong", () => {
  render(
    <IssuesBar
      document={timelineDocument()}
      selectedIssueId=""
      mode="advanced"
      dispatch={() => {}}
    />,
  );
  expect(screen.getByText("No issues")).toBeDefined();
  expect(screen.queryByRole("button", { name: "Review issues" })).toBeNull();
});

test("selecting an issue selects its target and focuses the clip", () => {
  const { actions } = mount();
  review();
  fireEvent.click(screen.getByRole("button", { name: /Main video/ }));

  expect(actions).toEqual([
    { type: "select_issue", issueId: "main_track_gap:clip_main" },
    { type: "select_track", trackId: "track_main" },
    { type: "select_clip", clipId: "clip_main" },
    { type: "set_playhead", frame: 30 },
  ]);
  expect(document.activeElement?.id).toBe("timeline-clip-clip_main");
});

test("opens Advanced mode only when the editor is still simple", () => {
  const advanced = mount("advanced");
  review();
  fireEvent.click(screen.getByRole("button", { name: /Music/ }));
  expect(advanced.actions.some((action) => action.type === "set_editor_mode")).toBe(false);

  cleanup();
  const simple = mount("simple");
  review();
  fireEvent.click(screen.getByRole("button", { name: /Music/ }));
  expect(simple.actions[0]).toEqual({ type: "set_editor_mode", mode: "advanced" });
});

test("marks the selected issue without stealing focus in the background", () => {
  mount("advanced", "main_track_gap:clip_main");
  review();
  (document.activeElement as HTMLElement | null)?.blur();
  const selected = screen.getByRole("button", { name: /Main video/ });
  expect(selected.getAttribute("aria-current")).toBe("true");
  expect(document.activeElement).toBe(document.body);
});

test("choosing an issue closes the list so the clip it focused is in sight", () => {
  mount();
  review();
  fireEvent.click(screen.getByRole("button", { name: /Main video/ }));
  expect(screen.queryByRole("listitem")).toBeNull();
});

test("the list never reopens by itself after the issues clear", () => {
  const props = { selectedIssueId: "", mode: "advanced" as EditorMode, dispatch: () => {} };
  const view = render(<IssuesBar document={brokenDocument()} {...props} />);
  review();
  view.rerender(<IssuesBar document={timelineDocument()} {...props} />);
  view.rerender(<IssuesBar document={brokenDocument()} {...props} />);
  expect(screen.queryByRole("listitem")).toBeNull();
});

test("issues are grouped by lane in track order", () => {
  // Studio shell v2 (spec 2026-11-01, goal 7).
  mount();
  review();

  const groups = screen.getAllByRole("group");
  expect(groups.map((group) => group.getAttribute("aria-label"))).toEqual(["Main video", "Music"]);
  expect(within(groups[1]!).getAllByRole("listitem")).toHaveLength(1);
});

test("an issue row names its clip and its time", () => {
  const actions: EditorAction[] = [];
  render(
    <IssuesBar
      document={brokenDocument()}
      selectedIssueId=""
      mode="advanced"
      dispatch={(action) => actions.push(action)}
      labelOf={(clip) => (clip.clip_id === "clip_main" ? "Footage · @OfficialiNews" : "Music")}
    />,
  );
  review();

  const row = screen.getByRole("button", { name: /Footage · @OfficialiNews/ });
  expect(row.textContent).toContain("0:01.0");
  fireEvent.click(row);
  expect(actions.at(-1)).toEqual({ type: "set_playhead", frame: 30 });
});

test("a lane without a label is named by its kind, never its id", () => {
  // Final review, minor 6.
  const document = brokenDocument();
  for (const track of document.tracks) delete (track as { label?: string }).label;
  render(<IssuesBar document={document} selectedIssueId="" mode="advanced" dispatch={() => {}} />);
  review();

  expect(screen.getAllByRole("group").map((group) => group.getAttribute("aria-label"))).toEqual(["Main video", "Music"]);
  expect(screen.queryByText(/track_/)).toBeNull();
});

test("inline, the bar shows the count without the sentence and opens its list above", () => {
  render(<IssuesBar document={brokenDocument()} selectedIssueId="" mode="advanced" dispatch={() => {}} inline />);
  const bar = screen.getByRole("region", { name: "Timeline issues" });
  expect(bar.textContent).toContain("2 warnings");
  expect(bar.textContent).not.toContain("Main video: a clip starts after a gap");
  review();
  expect(screen.getAllByRole("listitem")).toHaveLength(2);
  const list = screen.getAllByRole("listitem")[0]!.closest(".absolute")!;
  expect(list.className).toContain("bottom-full");
  expect(list.className).toContain("right-0");
  expect(list.className).toContain("max-h-56");
});

test("inline with no issues still says so", () => {
  render(<IssuesBar document={timelineDocument()} selectedIssueId="" mode="advanced" dispatch={() => {}} inline />);
  expect(screen.getByText("No issues")).toBeDefined();
});
