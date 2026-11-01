// Human names for assets and clips (spec 2026-11-01, Studio shell v2): "kind · source", never an id.
import type { EditDocumentV2, StudioImportItem, StudioMaterials } from "@/api/control-plane";
import type { MessageKey, Values } from "@/lib/i18n";

import { clipLabel as roleLabel } from "./TimelineClip";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
export type AssetKind = "voice" | "card" | "video" | "image" | "music" | "sfx" | "upload";
export type LabelContext = {
  document: EditDocumentV2;
  materials: StudioMaterials | null;
  t: (key: MessageKey, values?: Values) => string;
  /** The import inventory: names a clip saved before Story mode by its `clip_<item_id>`. */
  inventory?: StudioImportItem[];
};

const NARRATION = "clip_narration_";
const SFX = "clip_sfx_";
const CARD_ROLES = new Set(["post_card", "profile_card", "comment_card", "slide"]);

function seconds(document: EditDocumentV2, frames: number | null | undefined): number | null {
  return frames == null ? null : Math.round((frames / document.canvas.fps) * 10) / 10;
}

function clipName(clip: Clip, ctx: LabelContext): { label: string; kind: AssetKind } | null {
  const { t, document } = ctx;
  if (clip.clip_id.startsWith(NARRATION)) {
    const beat = t(`studio.story.beat.${clip.clip_id.slice(NARRATION.length)}` as MessageKey);
    return { label: t("studio.label.narration", { beat }), kind: "voice" };
  }
  if (clip.clip_id.startsWith(SFX)) {
    return { label: t("studio.label.sfx", { number: Number(clip.clip_id.slice(SFX.length)) + 1 }), kind: "sfx" };
  }
  const track = document.tracks.find((item) => item.track_id === clip.track_id);
  if (clip.kind === "audio" && track?.kind === "music") return { label: t("studio.label.music"), kind: "music" };
  return null;
}

type Named = { role?: string | null; owner_handle?: string | null; author?: string | null; label?: string | null; title?: string | null; media_kind?: string };

function described(item: Named | undefined, ctx: LabelContext): { label: string; kind: AssetKind } | null {
  if (!item?.role) return null;
  const role = ctx.t(`studio.label.role.${item.role}` as MessageKey);
  const source = item.owner_handle || item.author || item.label || item.title;
  const kind: AssetKind = CARD_ROLES.has(item.role) ? "card" : item.media_kind === "image" ? "image" : "video";
  return { label: source ? ctx.t("studio.label.material", { role, source }) : role, kind };
}

function materialName(assetId: string, ctx: LabelContext): { label: string; kind: AssetKind } | null {
  return described(ctx.materials?.items.find((material) => material.asset_id === assetId), ctx);
}

/** A clip saved before Story mode names its inventory item: `clip_<item_id>`. */
function itemName(clipId: string, ctx: LabelContext): { label: string; kind: AssetKind } | null {
  const itemId = clipId.replace(/^clip_/, "");
  return (
    described(ctx.materials?.items.find((material) => material.item_id === itemId), ctx) ??
    described(ctx.inventory?.find((entry) => entry.item_id === itemId), ctx)
  );
}

/** An asset's label, kind and length in seconds; an asset nothing names is an upload of its kind. */
export function assetLabel(
  assetId: string,
  ctx: LabelContext,
  /** The asset itself, for one the document does not reference yet (a library row). */
  known?: { kind: "image" | "video" | "audio"; duration_in_frames?: number | null },
): { label: string; kind: AssetKind; seconds: number | null } {
  const { document, t } = ctx;
  const ref = document.asset_refs?.find((asset) => asset.asset_id === assetId) ?? known;
  const length = seconds(document, ref?.duration_in_frames);
  const material = materialName(assetId, ctx);
  if (material) return { ...material, seconds: length };
  for (const clip of document.clips ?? []) {
    if ("asset_id" in clip && clip.asset_id === assetId) {
      const named = clipName(clip, ctx);
      if (named) return { ...named, seconds: length };
    }
  }
  const kind = ref?.kind ?? "video";
  return { label: t("studio.label.upload", { kind: t(`studio.label.kind.${kind}` as MessageKey) }), kind: "upload", seconds: length };
}

/** A clip's label: its own name, its material's, else the Timeline's words for its text, role or kind. */
export function clipLabel(clip: Clip, ctx: LabelContext): string {
  const named = clipName(clip, ctx);
  if (named) return named.label;
  const material = ("asset_id" in clip ? materialName(clip.asset_id, ctx) : null) ?? itemName(clip.clip_id, ctx);
  return material?.label ?? roleLabel(ctx.t, clip);
}

/** Repeated labels in one list get " · 2", " · 3" in list order, so rows stay distinguishable. */
export function numberRepeats(labels: string[]): string[] {
  const seen = new Map<string, number>();
  return labels.map((label) => {
    const count = (seen.get(label) ?? 0) + 1;
    seen.set(label, count);
    return count === 1 ? label : `${label} · ${count}`;
  });
}
