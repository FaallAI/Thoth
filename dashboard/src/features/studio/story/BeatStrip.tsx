import { useContextMenu } from "@/components/ContextMenu";
import { useState, type DragEvent } from "react";
import { Mic, Plus } from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { MATERIAL_DRAG_TYPE } from "./MaterialsPanel";

import { beatOwnFrames, type Beat, type BeatId } from "./story_beats";

type Props = {
  beats: Beat[];
  fps: number;
  totalFrames: number;
  selected: BeatId | null;
  onSelect: (id: BeatId) => void;
  /** Right-click menu (spec 2026-11-08 §5.2). */
  onAddFromMaterials?: (id: BeatId) => void;
  onShowInTimeline?: (id: BeatId) => void;
  /** With the preview URLs, a tile shows its first clips' stills and videos. */
  document?: EditDocumentV2;
  previews?: Record<string, string>;
  /** A material dropped on a media beat: its item id, or `upload:<asset_id>`. */
  onDropMaterial?: (beat: BeatId, data: string) => void;
  /** The text beats "Add beat" may make: Hook and Outro, each only while the draft lacks it. */
  addable?: ("hook" | "outro")[];
  onAddBeat?: (id: "hook" | "outro") => void;
  /** Beats with a narration voice, and those whose text changed after recording. */
  voiced?: ReadonlySet<BeatId>;
  stale?: ReadonlySet<BeatId>;
  /** "chips" below 1024: one scrolling row, the total pinned on the left. */
  variant?: "tiles" | "chips";
};

const THUMBS = 3;

/** DESIGN §13.1: one tile per beat in time order; beats may overlap, so tiles show order and length. */
export function BeatStrip({
  beats,
  fps,
  totalFrames,
  selected,
  onSelect,
  onAddFromMaterials,
  onShowInTimeline,
  document,
  previews = {},
  onDropMaterial,
  addable = [],
  onAddBeat,
  voiced,
  stale,
  variant = "tiles",
}: Props) {
  const chips = variant === "chips";
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
      // A voice has no picture to show on its tile.
      .flatMap((clip) => (clip && "asset_id" in clip && previews[clip.asset_id] && kinds.get(clip.asset_id) !== "audio" ? [clip.asset_id] : []))
      .slice(0, THUMBS);
  const seconds = (frames: number) => t("studio.story.seconds", { seconds: (frames / fps).toFixed(1) });
  // Each tile's own time, so the tiles sum to the canvas (spec 2026-11-01, goal 6).
  const own = beatOwnFrames(beats, totalFrames);
  const menu = useContextMenu();

  return (
    <div
      role="toolbar"
      aria-label={t("studio.story.beats")}
      data-variant={variant}
      className={`flex shrink-0 items-stretch gap-2 rounded-[10px] border border-hairline bg-bg p-2 ${chips ? "overflow-x-auto [scrollbar-width:none]" : "overflow-x-auto"}`}
    >
      <span className={`flex shrink-0 flex-col self-center px-2 font-mono text-xs text-muted-ink ${chips ? "sticky left-0 z-10 bg-bg" : ""}`}>
        <span>{t("studio.story.total", { length: seconds(totalFrames) })}</span>
        <span className="font-sans text-[11px] text-faint">{t("studio.story.matchesCanvas")}</span>
      </span>
      {menu.element}
      {beats.map((beat) => (
        <button
          key={beat.id}
          type="button"
          data-beat={beat.id}
          aria-pressed={selected === beat.id}
          onClick={() => onSelect(beat.id)}
          {...menu.bind(() => {
            const unavailable = t("studio.menu.reason.unavailable");
            return [
              { kind: "item", id: "open", label: t("studio.menu.openBeat"), onSelect: () => onSelect(beat.id) },
              { kind: "item", id: "add", label: t("studio.menu.addFromMaterials"), disabled: !onAddFromMaterials, reason: unavailable, onSelect: () => onAddFromMaterials?.(beat.id) },
              { kind: "item", id: "timeline", label: t("studio.menu.showInTimeline"), disabled: !onShowInTimeline, reason: unavailable, onSelect: () => onShowInTimeline?.(beat.id) },
            ];
          })}
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
          className={`flex shrink-0 rounded-md border-2 bg-surface text-left text-sm text-ink hover:bg-raised focus-visible:outline-2 focus-visible:outline-copper ${
            chips ? "items-center gap-2 px-3 py-1.5" : "min-w-28 flex-col items-start gap-1 px-3 py-2"
          } ${
            over === beat.id ? "border-dashed border-copper" : selected === beat.id ? "border-copper" : "border-transparent"
          }`}
        >
          <span className="font-medium">{t(`studio.story.beat.${beat.id}`)}</span>
          {!chips && thumbs(beat).length ? (
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
          <span className="flex items-center gap-1.5 font-mono text-xs text-muted-ink">
            {seconds(own.get(beat.id) ?? 0)}
            {stale?.has(beat.id) ? (
              <Mic role="img" aria-label={t("studio.story.needsRevoice")} size={12} className="text-status-waiting" />
            ) : voiced?.has(beat.id) ? (
              <Mic role="img" aria-label={t("studio.story.narrated")} size={12} className="text-status-done" />
            ) : null}
          </span>
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
