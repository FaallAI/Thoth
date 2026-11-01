import { expect, test } from "bun:test";

import type { EditDocumentV2, StudioMaterials } from "@/api/control-plane";
import { translate, type MessageKey, type Values } from "@/lib/i18n";

import { assetLabel, clipLabel, type LabelContext } from "./studio_labels";
import { timelineDocument } from "./timeline-test-fixtures";

const t = (key: MessageKey, values?: Values) => translate("en", key, values);

function context(document: EditDocumentV2, materials: StudioMaterials | null = null): LabelContext {
  return { document, materials, t };
}

function materialsWith(items: Partial<StudioMaterials["items"][number]>[]): StudioMaterials {
  return {
    document_id: "document_002",
    provenance_available: true,
    items: items.map((item, index) => ({
      item_id: `item_${index}`,
      role: null,
      label: "",
      media_kind: "image",
      disposition: "attached",
      ...item,
    })),
  } as StudioMaterials;
}

function withClip(clip: Record<string, unknown>, asset?: Record<string, unknown>): EditDocumentV2 {
  const document = timelineDocument();
  return {
    ...document,
    asset_refs: [...(document.asset_refs ?? []), ...(asset ? [asset] : [])],
    clips: [...((document.clips ?? []) as unknown[]), clip],
  } as EditDocumentV2;
}

const voice = {
  kind: "audio",
  clip_id: "clip_narration_main",
  track_id: "track_music",
  asset_id: "asset_voice",
  from_frame: 0,
  duration_in_frames: 426,
  source_from_frame: 0,
  ownership: "ai_managed",
  hidden: false,
  locked: false,
  volume: 1,
  fade_in_frames: 0,
  fade_out_frames: 0,
};
const voiceAsset = { asset_id: "asset_voice", project_id: "project_001", kind: "audio", has_audio: true, validation_state: "ready", duration_in_frames: 426 };

test("a narration voice is named by its beat", () => {
  const ctx = context(withClip(voice, voiceAsset));

  expect(assetLabel("asset_voice", ctx)).toEqual({ label: "Narration · Main", kind: "voice", seconds: 14.2 });
  expect(clipLabel(ctx.document.clips!.at(-1)!, ctx)).toBe("Narration · Main");
});

test("a comment card is named by role and handle", () => {
  const ctx = context(timelineDocument(), materialsWith([{ asset_id: "asset_video", role: "comment_card", owner_handle: "@lailynisfa" }]));

  expect(assetLabel("asset_video", ctx).label).toBe("Comment card · @lailynisfa");
  expect(assetLabel("asset_video", ctx).kind).toBe("card");
});

test("an asset nothing names is an upload of its kind", () => {
  const document = withClip(voice, { ...voiceAsset, asset_id: "asset_still", kind: "image", duration_in_frames: null });
  const ctx = context(document);

  expect(assetLabel("asset_still", ctx)).toEqual({ label: "Upload · Image", kind: "upload", seconds: null });
  for (const clip of document.clips ?? []) expect(clipLabel(clip, ctx)).not.toMatch(/asset_|clip_/);
});

test("a placed sound effect is numbered, since its clip id carries no library id", () => {
  const ctx = context(withClip({ ...voice, clip_id: "clip_sfx_0", asset_id: "asset_sfx" }, { ...voiceAsset, asset_id: "asset_sfx" }));

  expect(clipLabel(ctx.document.clips!.at(-1)!, ctx)).toBe("Sound effect · 1");
  expect(assetLabel("asset_sfx", ctx).label).toBe("Sound effect · 1");
});
