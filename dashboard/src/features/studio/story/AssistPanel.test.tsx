/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { StudioImportRequestError, type StoryAssistProposal } from "@/api/control-plane";
import { render } from "@/test-render";

import type { EditorAction } from "../editor_state";
import { AssistPanel } from "./AssistPanel";
import { computeBeats } from "./story_beats";
import { storyDocument, storyInventory } from "./story-test-fixtures";

afterEach(cleanup);

const hook = computeBeats(storyDocument(), storyInventory()).find((beat) => beat.id === "hook")!;
const proposal: StoryAssistProposal = {
  proposal_id: "assist_1",
  title: "Shorter hook",
  reason: "31 characters instead of 56, readable in the 4-second hook at 15 chars/s",
  operations: [{ kind: "replace_text", operation_id: "op_assist_1", clip_id: "clip_hook", field: "heading", value: "Asap Kalteng makin parah" }],
};

function mount(request: (...args: unknown[]) => Promise<StoryAssistProposal>, locale: "en" | "id" = "en") {
  const dispatch = mock((_action: EditorAction) => {});
  const ask = mock(request);
  render(<AssistPanel request={ask} baseRevision={3} beat={hook} dispatch={dispatch} />, { locale });
  return { dispatch, ask };
}

test("a suggestion for the beat, applied through the editor", async () => {
  const { dispatch, ask } = mount(async () => proposal);

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" })));

  expect(ask).toHaveBeenCalledWith({ base_revision: 3, beat: "hook", clip_ids: ["clip_hook"] });
  expect(screen.getByText("Shorter hook")).toBeDefined();
  expect(screen.getByText(/31 characters instead of 56/)).toBeDefined();
  expect(screen.getByText("Asap Kalteng makin parah")).toBeDefined();

  fireEvent.click(screen.getByRole("button", { name: "Apply" }));
  expect(dispatch).toHaveBeenCalledWith({ type: "commit_operations", operations: proposal.operations });
  expect(screen.queryByText("Shorter hook")).toBeNull();
});

test("dismiss forgets the proposal and changes nothing", async () => {
  const { dispatch } = mount(async () => proposal);

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" })));
  fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));

  expect(dispatch).not.toHaveBeenCalled();
  expect(screen.queryByText("Shorter hook")).toBeNull();
});

test("the panel shows it is thinking while the call runs", async () => {
  let finish: (value: StoryAssistProposal) => void = () => {};
  mount(() => new Promise<StoryAssistProposal>((resolve) => (finish = resolve)));

  fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" }));
  expect(screen.getByRole("status").textContent).toContain("Thinking");
  await act(async () => finish(proposal));
  expect(screen.queryByText(/Thinking/)).toBeNull();
});

test("an unconfigured project is sent to Presets & prompts", async () => {
  mount(async () => {
    throw new StudioImportRequestError(409, "assist_not_configured");
  });

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" })));

  expect(screen.getByRole("alert").textContent).toContain("Choose a model for Story Assist");
  expect(screen.getByRole("link", { name: "Presets & prompts" }).getAttribute("href")).toBe("/studio/presets");
});

test("a failure says so and leaves the draft alone", async () => {
  const { dispatch } = mount(async () => {
    throw new StudioImportRequestError(503, "assist_unavailable");
  });

  await act(async () => fireEvent.click(screen.getByRole("button", { name: "Suggest for Hook" })));

  expect(screen.getByRole("alert").textContent).toContain("Assist is unavailable");
  expect(dispatch).not.toHaveBeenCalled();
});

test("the panel speaks Indonesian", () => {
  mount(async () => proposal, "id");

  expect(screen.getByRole("button", { name: "Sarankan untuk Hook" })).toBeDefined();
});
