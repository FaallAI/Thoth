import { useState, type Dispatch, type ReactNode } from "react";
import { ChevronRight, MessagesSquare, Monitor, Type } from "lucide-react";

import type { EditDocumentV2, EditorAsset, StudioMaterial, StudioMaterials } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import type { EditorAction } from "../editor_state";
import type { Beat } from "./story_beats";
import { SwapCardSheet } from "./SwapCardSheet";

type Props = {
  document: EditDocumentV2;
  beats: Beat[];
  materials: StudioMaterials | null;
  revision: number;
  playheadFrame: number;
  dispatch: Dispatch<EditorAction>;
  attachMaterial?: (itemId: string) => Promise<EditorAsset>;
  /** The existing caption editor, as the Captions row. */
  captions: ReactNode;
};

const row = "flex items-center gap-3 border-b border-hairline px-4 py-3 last:border-b-0";

/** DESIGN §13.5: the phone's quick edit — hook text, captions, a comment card swap. Nothing else. */
export function QuickEdit({ document, beats, materials, revision, playheadFrame, dispatch, attachMaterial, captions }: Props) {
  const { t, plural } = useLocale();
  const [swapping, setSwapping] = useState(false);
  const clips = document.clips ?? [];
  const hook = clips.find(
    (clip) => clip.kind === "text" && beats.find((beat) => beat.id === "hook")?.clipIds.includes(clip.clip_id),
  );
  const reactions = beats.find((beat) => beat.id === "reactions");
  const reactionClips = (reactions?.clipIds ?? [])
    .map((id) => clips.find((clip) => clip.clip_id === id))
    .filter((clip): clip is NonNullable<typeof clip> => clip?.kind === "video");
  // The card on screen at the playhead, else the first.
  const atPlayhead = reactionClips.findIndex(
    (clip) => clip.from_frame <= playheadFrame && playheadFrame < clip.from_frame + clip.duration_in_frames,
  );
  const targetIndex = Math.max(0, atPlayhead);
  const target = reactionClips[targetIndex];
  const cards = (materials?.items ?? []).filter((item) => item.role === "comment_card" && item.media_kind === "image");
  const inUse = target && "asset_id" in target ? cards.find((item) => item.asset_id === target.asset_id)?.item_id ?? null : null;

  const swap = async (card: StudioMaterial) => {
    if (!target || !attachMaterial) return;
    const asset = await attachMaterial(card.item_id);
    dispatch({ type: "assets_loaded", assets: [asset], replace: false });
    dispatch({
      type: "commit_operations",
      operations: [{ kind: "replace_clip_asset", operation_id: `op_${crypto.randomUUID()}`, clip_id: target.clip_id, asset_id: asset.asset_id }],
    });
    setSwapping(false);
  };

  return (
    <section aria-label={t("studio.quick.region")} className="flex flex-col gap-3 p-4">
      <h2 className="text-[15px] font-semibold text-ink">{t("studio.quick.title", { revision })}</h2>
      <div className="flex flex-col rounded-[10px] border border-hairline bg-surface">
        {hook?.kind === "text" ? (
          <label className={row}>
            <Type aria-hidden="true" size={18} className="shrink-0 text-muted-ink" />
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="text-sm font-medium text-ink">{t("studio.quick.hook")}</span>
              <input
                key={hook.heading}
                type="text"
                aria-label={t("studio.quick.hook")}
                defaultValue={hook.heading}
                onKeyDown={(event) => event.key === "Enter" && event.currentTarget.blur()}
                onBlur={(event) => {
                  const value = event.currentTarget.value.trim();
                  if (value && value !== hook.heading) {
                    dispatch({
                      type: "commit_operations",
                      operations: [{ kind: "replace_text", operation_id: `op_${crypto.randomUUID()}`, clip_id: hook.clip_id, field: "heading", value }],
                    });
                  }
                }}
                className="h-9 rounded-md border border-hairline bg-well px-2 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper"
              />
            </span>
          </label>
        ) : null}
        <div className={`${row} flex-col items-stretch`}>{captions}</div>
        {cards.length && target && attachMaterial ? (
          <button type="button" className={`${row} text-left`} onClick={() => setSwapping(true)}>
            <MessagesSquare aria-hidden="true" size={18} className="shrink-0 text-muted-ink" />
            <span className="flex min-w-0 flex-1 flex-col">
              <span className="text-sm font-medium text-ink">{t("studio.quick.swapRow")}</span>
              <span className="text-xs text-muted-ink">{plural("studio.quick.swapCount", reactionClips.length)}</span>
            </span>
            <ChevronRight aria-hidden="true" size={16} className="text-muted-ink" />
          </button>
        ) : null}
      </div>
      <p className="flex items-center gap-2 text-xs text-muted-ink">
        <Monitor aria-hidden="true" size={14} /> {t("studio.quick.larger")}
      </p>
      {swapping ? (
        <SwapCardSheet index={targetIndex + 1} cards={cards} inUse={inUse} onCancel={() => setSwapping(false)} onSwap={(card) => void swap(card)} />
      ) : null}
    </section>
  );
}
