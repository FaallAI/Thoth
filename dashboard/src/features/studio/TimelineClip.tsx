import type { KeyboardEvent, PointerEvent } from "react";
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
  /** An audio clip's volume line (Tier 3b): a drag previews, a release or a key commits. */
  onVolume?: (volume: number, phase: "preview" | "commit" | "cancel") => void;
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
      <div
        data-testid="clip-filmstrip"
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 overflow-hidden opacity-70"
        // The picture is set once here; every tile points at it (final review 2026-11-09).
        style={{ ["--strip" as string]: `url("${strip.image}")` }}
      >
        {stripTiles(strip, window, widthPx, GLANCE_HEIGHT).map((tile) => (
          <div
            key={tile.left}
            className="absolute top-0 h-full bg-no-repeat"
            style={{
              left: `${tile.left}px`,
              width: `${tile.width}px`,
              backgroundImage: "var(--strip)",
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

/** Volume steps of 0.05, from 0 at the line's bottom to 1 at its top, as the Inspector's slider. */
const volumeStep = (value: number) => Math.min(1, Math.max(0, Math.round(value * 20) / 20));

function VolumeLine({ volume, label, onVolume }: { volume: number; label: string; onVolume: NonNullable<Props["onVolume"]> }) {
  const shown = Math.min(1, Math.max(0, volume));
  const start = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    event.stopPropagation();
    // The level moves with the pointer from where it was pressed, so a press alone changes
    // nothing; only a drag previews, and only a changed level commits (final review 2026-11-09).
    const height = Math.max(1, event.currentTarget.parentElement!.getBoundingClientRect().height);
    const pressY = event.clientY;
    const at = (clientY: number) => volumeStep(shown + (pressY - clientY) / height);
    let moved = false;
    let last = shown;
    const end = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
      window.removeEventListener("keydown", escape, true);
    };
    const cancel = () => {
      end();
      if (moved) onVolume(last, "cancel");
    };
    const move = (pointer: globalThis.PointerEvent) => {
      moved = true;
      last = at(pointer.clientY);
      onVolume(last, "preview");
    };
    const up = (released: globalThis.PointerEvent) => {
      end();
      const level = at(released.clientY);
      if (!moved) return;
      onVolume(level, level === volume ? "cancel" : "commit");
    };
    const escape = (key: globalThis.KeyboardEvent) => {
      if (key.key !== "Escape") return;
      key.stopPropagation();
      cancel();
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    window.addEventListener("keydown", escape, true);
  };
  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const next =
      event.key === "ArrowUp" || event.key === "ArrowRight" ? volumeStep(shown + 0.05)
      : event.key === "ArrowDown" || event.key === "ArrowLeft" ? volumeStep(shown - 0.05)
      : event.key === "Home" ? 0
      : event.key === "End" ? 1
      : null;
    if (next === null) return;
    event.preventDefault();
    // A boosted clip (above 1, set through the API) is never made quieter by a "louder" key.
    if (volume >= 1 && next >= shown) return;
    event.stopPropagation();
    onVolume(next, "commit");
  };
  return (
    <div
      role="slider"
      tabIndex={0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(shown * 100)}
      aria-valuetext={`${Math.round(shown * 100)}%`}
      className="group/volume absolute inset-x-1 z-10 h-3 -translate-y-1/2 cursor-ns-resize focus-visible:outline-2 focus-visible:outline-copper"
      style={{ top: `${(1 - shown) * 100}%` }}
      onPointerDown={start}
      onKeyDown={keys}
    >
      <span aria-hidden="true" className="absolute inset-x-0 top-1/2 h-px bg-copper/80 group-hover/volume:h-0.5" />
    </div>
  );
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
  onVolume,
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
      {!readOnly && !locked && onVolume && clip.kind === "audio" ? (
        <VolumeLine volume={clip.volume ?? 1} label={t("studio.timeline.volumeOf", { clip: name })} onVolume={onVolume} />
      ) : null}
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
