import type { PointerEvent } from "react";
import { Lock } from "lucide-react";

import type { AssetGlance, EditDocumentV2 } from "@/api/control-plane";
import type { MenuHandlers } from "@/components/ContextMenu";
import { useLocale, type LocaleState } from "@/lib/locale";
import { clipLabelSource, framesToPixels } from "./timeline_domain";
import { glanceWindow, peakSlice, stripTiles } from "./clip_glance";

/** Alt turns a body drag into a slip and a handle drag into a roll (Tier 3a). */
export type GestureMode = "move" | "trim_start" | "trim_end" | "slip" | "roll_start" | "roll_end";

const ALT_MODE: Record<"move" | "trim_start" | "trim_end", GestureMode> = { move: "slip", trim_start: "roll_start", trim_end: "roll_end" };

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
type TrackKind = EditDocumentV2["tracks"][number]["kind"];

type Props = {
  clip: Clip;
  trackKind: TrackKind;
  /** The track label, so every control reads as "<track> clip". */
  label: string;
  zoom: number;
  selected: boolean;
  locked: boolean;
  /** `add` when Shift, Ctrl or Cmd was held: the clip joins or leaves the selection. */
  onSelect: (add: boolean) => void;
  onGestureStart: (mode: GestureMode, clientX: number) => void;
  onNudge: (frames: number) => void;
  /** The clip's human name (spec 2026-11-01); absent, the Timeline's own words for it. */
  name?: string;
  /** The asset's filmstrip or peaks (Tier 3b); a clip without one draws plain. */
  glance?: AssetGlance;
  /** The draft's frame rate, to place the glance in seconds. */
  fps?: number;
  /** A view-only timeline: no trim handles, no drag. */
  readOnly?: boolean;
  /** The clip's right-click menu (spec 2026-11-08 §5.1). */
  menu?: MenuHandlers;
};

/** Video lanes read as footage, cards and words as panels, sound as the darkest well. */
const FILL: Record<TrackKind, string> = {
  main_video: "bg-raised",
  b_roll: "bg-raised",
  overlay: "bg-surface",
  caption: "bg-surface",
  narration: "bg-bg",
  music: "bg-bg",
  sfx: "bg-bg",
};

/** A clip in words: its own text, its role in the story, or its kind (`clipLabelSource`). */
export function clipLabel(t: LocaleState["t"], clip: Clip): string {
  const source = clipLabelSource(clip);
  if ("text" in source) return source.text;
  if ("kind" in source) return t(`studio.timeline.kind.${source.kind}`);
  return source.role === "hook" || source.role === "outro"
    ? t(`studio.story.beat.${source.role}`)
    : t(`studio.inventory.role.${source.role}`);
}

/** A clip's inner height in pixels (h-9 less its border), the filmstrip's height. */
const GLANCE_HEIGHT = 34;

/** Behind the label: the frames or the sound of the stretch of source the clip plays. */
function GlanceLayer({ clip, glance, widthPx, fps }: { clip: Clip; glance: AssetGlance; widthPx: number; fps: number }) {
  if (!("source_from_frame" in clip) || widthPx <= 0) return null;
  const window = glanceWindow(clip, fps);
  if ((clip.kind === "video") && glance.strip) {
    const strip = glance.strip;
    return (
      <div data-testid="clip-filmstrip" aria-hidden="true" className="pointer-events-none absolute inset-0 overflow-hidden opacity-70">
        {stripTiles(strip, window, widthPx, GLANCE_HEIGHT).map((tile) => (
          <div
            key={tile.left}
            className="absolute top-0 h-full bg-no-repeat"
            style={{
              left: `${tile.left}px`,
              width: `${tile.width}px`,
              backgroundImage: `url("${strip.image}")`,
              backgroundSize: `${strip.frames * Math.round((strip.frame_width * GLANCE_HEIGHT) / strip.frame_height)}px ${GLANCE_HEIGHT}px`,
              backgroundPosition: `-${tile.frame * Math.round((strip.frame_width * GLANCE_HEIGHT) / strip.frame_height)}px 0`,
            }}
          />
        ))}
      </div>
    );
  }
  if (clip.kind === "audio" && glance.peaks) {
    const values = peakSlice(glance.peaks, window);
    if (!values.length) return null;
    const path = values.map((value, index) => `M${index + 0.5} ${50 - value / 2}V${50 + value / 2}`).join("");
    return (
      <svg
        data-testid="clip-waveform"
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 h-full w-full text-copper/50"
        viewBox={`0 0 ${values.length} 100`}
        preserveAspectRatio="none"
      >
        <path d={path} stroke="currentColor" strokeWidth={0.8} vectorEffect="non-scaling-stroke" />
      </svg>
    );
  }
  return null;
}

const withModifier = (event: { shiftKey: boolean; ctrlKey: boolean; metaKey: boolean }) =>
  event.shiftKey || event.ctrlKey || event.metaKey;

const handle =
  "absolute top-0 h-full w-2 cursor-ew-resize focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-0";

export function TimelineClip({
  clip,
  trackKind,
  label,
  zoom,
  selected,
  locked,
  onSelect,
  onGestureStart,
  onNudge,
  name: given,
  glance,
  fps = 30,
  readOnly = false,
  menu,
}: Props) {
  const { t } = useLocale();
  const name = t("studio.timeline.clip", { track: label });
  const text = given ?? clipLabel(t, clip);
  const start = (mode: "move" | "trim_start" | "trim_end") => (event: PointerEvent) => {
    if (event.button !== 0) return;
    const add = withModifier(event);
    onSelect(add);
    // A modifier press only changes the selection; it never starts a drag.
    if (!add) onGestureStart(event.altKey ? ALT_MODE[mode] : mode, event.clientX);
  };

  return (
    <div
      className="absolute top-1 h-9"
      style={{
        left: `${framesToPixels(clip.from_frame, zoom)}px`,
        width: `${Math.max(8, framesToPixels(clip.duration_in_frames, zoom))}px`,
      }}
    >
      <button
        type="button"
        id={`timeline-clip-${clip.clip_id}`}
        aria-label={name}
        aria-pressed={selected}
        className={`relative flex h-full w-full items-start gap-1 overflow-hidden rounded-md border px-2 py-1 text-left text-xs text-ink transition-colors focus-visible:outline-2 focus-visible:outline-copper ${FILL[trackKind]} ${
          selected ? "border-2 border-copper" : "border-hairline hover:border-faint"
        }`}
        // A pointer press already selected; a click from the keyboard (detail 0) selects here.
        onClick={(event) => {
          if (event.detail === 0) onSelect(withModifier(event));
        }}
        onContextMenu={(event) => {
          onSelect(false);
          menu?.onContextMenu(event);
        }}
        onPointerUp={menu?.onPointerUp}
        onPointerCancel={menu?.onPointerCancel}
        onPointerDown={(event) => {
          menu?.onPointerDown(event);
          if (readOnly) {
            if (event.button === 0) onSelect(false);
          } else start("move")(event);
        }}
        onKeyDown={(event) => {
          menu?.onKeyDown(event);
          if (event.defaultPrevented) return;
          const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
          if (!step) return;
          // Arrows on a focused clip belong to the clip, so they never move the playhead instead.
          event.preventDefault();
          if (locked || readOnly) return;
          onNudge(step);
        }}
      >
        {glance ? <GlanceLayer clip={clip} glance={glance} widthPx={framesToPixels(clip.duration_in_frames, zoom)} fps={fps} /> : null}
        {locked ? <Lock aria-hidden="true" size={11} className="relative mt-0.5 shrink-0 text-faint" /> : null}
        <span className="relative truncate rounded bg-well/70 px-1" title={text}>{text}</span>
      </button>
      {readOnly ? null : (
        <>
          <button
            type="button"
            aria-label={t("studio.timeline.trimStartOf", { clip: name })}
            disabled={locked}
            className={`${handle} left-0 rounded-l-md ${selected ? "bg-copper/40" : ""}`}
            onPointerDown={start("trim_start")}
          />
          <button
            type="button"
            aria-label={t("studio.timeline.trimEndOf", { clip: name })}
            disabled={locked}
            className={`${handle} right-0 rounded-r-md ${selected ? "bg-copper/40" : ""}`}
            onPointerDown={start("trim_end")}
          />
        </>
      )}
    </div>
  );
}
