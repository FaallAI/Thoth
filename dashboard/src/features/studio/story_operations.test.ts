/// <reference types="bun-types" />

import { expect, test } from "bun:test";

import type { EditDocumentOperation, EditDocumentV2, EditorAsset } from "@/api/control-plane";

import cases from "../../../../python/tests/fixtures/story_operation_cases.json";
import { createEditorState, editorReducer } from "./editor_state";
import { applyTimelineOperation } from "./timeline_domain";

// The same cases hold the server's `apply_edit_operations` (python/tests/domain/test_story_operations.py).
const base = cases.base as unknown as EditDocumentV2;
const assets: Record<string, EditorAsset> = Object.fromEntries(
  Object.entries(cases.assets).map(([id, ref]) => [id, { ...ref, media_type: "application/octet-stream" } as EditorAsset]),
);

for (const story of cases.cases) {
  test(`story operation case ${story.name}`, () => {
    const operations = story.operations as unknown as EditDocumentOperation[];
    const apply = () =>
      operations.reduce((document, operation) => applyTimelineOperation(document, operation, assets), base);

    if (story.refused) {
      expect(apply).toThrow();
      return;
    }
    const clips = new Map((apply().clips ?? []).map((clip) => [clip.clip_id, clip as Record<string, unknown>]));
    for (const [clipId, fields] of Object.entries(story.expect ?? {})) {
      const clip = clips.get(clipId);
      expect(clip).toBeDefined();
      for (const [key, value] of Object.entries(fields)) expect([key, clip?.[key] ?? null] as unknown[]).toEqual([key, value]);
    }
  });
}

const motion = (clipId: string, id: string): EditDocumentOperation => ({
  kind: "set_clip_motion",
  operation_id: id,
  clip_id: clipId,
  motion: "slow_zoom",
});

test("commit_operations is one undo step", () => {
  let state = createEditorState(base, assets);
  state = editorReducer(state, {
    type: "commit_operations",
    operations: [motion("clip_comment_card_000", "op_a"), motion("clip_comment_card_001", "op_b")],
  });
  expect(state.pendingOperations.map((operation) => operation.operation_id)).toEqual(["op_a", "op_b"]);
  expect(state.history).toHaveLength(1);

  state = editorReducer(state, { type: "undo" });
  expect(state.draft).toBe(base);
  expect(state.pendingOperations).toEqual([]);
});

test("commit_operations is atomic", () => {
  const initial = createEditorState(base, assets);
  const state = editorReducer(initial, {
    type: "commit_operations",
    operations: [motion("clip_comment_card_000", "op_a"), motion("clip_unknown", "op_b")],
  });
  expect(state.draft).toBe(base);
  expect(state.pendingOperations).toEqual([]);
  expect(state.history).toEqual([]);
});

test("commit_operations applies replace_text alongside timeline operations", () => {
  const state = editorReducer(createEditorState(base, assets), {
    type: "commit_operations",
    operations: [
      { kind: "replace_text", operation_id: "op_text", clip_id: "clip_001", field: "heading", value: "Shorter" },
      motion("clip_comment_card_000", "op_motion"),
    ],
  });
  const heading = (state.draft.clips ?? []).find((clip) => clip.clip_id === "clip_001");
  expect(heading).toMatchObject({ heading: "Shorter", ownership: "user_edited" });
  expect(state.pendingOperations).toHaveLength(2);
});
