import { useState, type DragEvent } from "react";
import { Plus } from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { MATERIAL_DRAG_TYPE } from "./MaterialsPanel";

import type { Beat, BeatId } from "./story_beats";

type Props = {
  beats: Beat[];
  fps: number;
  totalFrames: number;
  selected: BeatId | null;
  onSelect: (id: BeatId) => void;
  /** With the preview URLs, a tile shows its first clips' stills and videos. */
  document?: EditDocumentV2;
  previews?: Record<string, string>;
  /** A material dropped on a media beat: its item id, or `upload:<asset_id>`. */
  onDropMaterial?: (beat: BeatId, data: string) => void;
  /** The text beats "Add beat" may make: Hook and Outro, each only while the draft lacks it. */
  addable?: ("hook" | "outro")[];
  onAddBeat?: (id: "hook" | "outro") => void;
};

const THUMBS = 3;

/** DESIGN §13.1: one tile per beat in time order; beats may overlap, so tiles show order and length. */
export function BeatStrip({
  beats,
  fps,
  totalFrames,
  selected,
  onSelect,
  document,
  previews = {},
  onDropMaterial,
  addable = [],
  onAddBeat,
}: Props) {
  const { t } = useLocale();
  const [over, setOver] = useState<BeatId | null>(null);
  const [adding, setAdding] = useState(false);
  // Hook and Outro are text; media goes to the other beats.
  const accepts = (id: BeatId, event: DragEvent) =>
    Boolean(onDropMaterial) && id !== "hook" && id !== "outro" && [...event.dataTransfer.types].includes(MATERIAL_DRAG_TYPE);
  const clips = new Map((document?.clips ?? []).map((clip) => [clip.clip_id, clip]));
  const kinds = new Map((document?.asset_refs ?? []).map((ref) => [ref.asset_id, ref.kind]));
  const thumbs = (beat: Beat) =>
    beat.clipIds
      .map((id) => clips.get(id))
      .flatMap((clip) => (clip && "asset_id" in clip && previews[clip.asset_id] ? [clip.asset_id] : []))
      .slice(0, THUMBS);
  const seconds = (frames: number) => t("studio.story.seconds", { seconds: (frames / fps).toFixed(1) });

  return (
    <div
      role="toolbar"
      aria-label={t("studio.story.beats")}
      className="flex shrink-0 items-stretch gap-2 overflow-x-auto rounded-[10px] border border-hairline bg-bg p-2"
    >
      <span className="shrink-0 self-center px-2 font-mono text-xs text-muted-ink">
        {t("studio.story.total", { length: seconds(totalFrames) })}
      </span>
      {beats.map((beat) => (
        <button
          key={beat.id}
          type="button"
          data-beat={beat.id}
          aria-pressed={selected === beat.id}
          onClick={() => onSelect(beat.id)}
          onDragOver={(event) => {
            if (!accepts(beat.id, event)) return;
            event.preventDefault();
            setOver(beat.id);
          }}
          onDragLeave={() => setOver(null)}
          onDrop={(event) => {
            if (!accepts(beat.id, event)) return;
            event.preventDefault();
            setOver(null);
            onDropMaterial?.(beat.id, event.dataTransfer.getData(MATERIAL_DRAG_TYPE));
          }}
          className={`flex min-w-28 shrink-0 flex-col items-start gap-1 rounded-md border-2 bg-surface px-3 py-2 text-left text-sm text-ink hover:bg-raised focus-visible:outline-2 focus-visible:outline-copper ${
            over === beat.id ? "border-dashed border-copper" : selected === beat.id ? "border-copper" : "border-transparent"
          }`}
        >
          <span className="font-medium">{t(`studio.story.beat.${beat.id}`)}</span>
          {thumbs(beat).length ? (
            <span aria-hidden="true" className="flex gap-1">
              {thumbs(beat).map((assetId) =>
                kinds.get(assetId) === "video" ? (
                  <video key={assetId} src={previews[assetId]} muted preload="metadata" className="h-10 w-6 rounded-sm object-cover" />
                ) : (
                  <img key={assetId} src={previews[assetId]} alt="" className="h-10 w-6 rounded-sm object-cover" />
                ),
              )}
            </span>
          ) : null}
          <span className="font-mono text-xs text-muted-ink">{seconds(beat.durationInFrames)}</span>
          {over === beat.id ? (
            <span className="text-xs text-copper">{t("studio.story.addTo", { beat: t(`studio.story.beat.${beat.id}`) })}</span>
          ) : null}
          {beat.missing.length ? (
            <span className="flex items-center gap-1 text-xs text-status-failed">
              <span aria-hidden="true" className="size-2 rounded-full bg-status-failed" />
              {t("studio.story.missing", { count: beat.missing.length })}
            </span>
          ) : null}
        </button>
      ))}
      {onAddBeat && addable.length ? (
        <div className="relative ml-auto shrink-0 self-center">
          <button
            type="button"
            aria-expanded={adding}
            onClick={() => setAdding((open) => !open)}
            className="inline-flex h-10 items-center gap-1.5 rounded-md border border-hairline px-3 text-[13px] text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper"
          >
            <Plus aria-hidden="true" size={14} /> {t("studio.story.addBeat")}
          </button>
          {adding ? (
            <div role="menu" aria-label={t("studio.story.addBeat")} className="absolute right-0 bottom-12 z-30 flex w-40 flex-col rounded-md border border-hairline bg-raised p-1 shadow-xl">
              {addable.map((id) => (
                <button
                  key={id}
                  type="button"
                  role="menuitem"
                  onClick={() => {
                    setAdding(false);
                    onAddBeat(id);
                  }}
                  className="rounded px-2 py-1.5 text-left text-sm text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper"
                >
                  {t(`studio.story.beat.${id}`)}
                </button>
              ))}
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
