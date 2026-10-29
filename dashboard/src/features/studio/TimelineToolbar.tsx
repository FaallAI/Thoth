import {
  ArrowRightToLine,
  BetweenHorizontalEnd,
  BetweenHorizontalStart,
  Minus,
  Pause,
  Play,
  Plus,
  Scissors,
} from "lucide-react";

import { useLocale } from "@/lib/locale";
import { Switch } from "./StudioSwitch";
import { MAX_ZOOM, MIN_ZOOM, formatTimecode } from "./timeline_domain";

export type ClipAction = "move" | "trim_start" | "trim_end" | "split";

type Props = {
  zoom: number;
  snapping: boolean;
  ripple: boolean;
  playheadFrame: number;
  durationInFrames: number;
  fps: number;
  playing: boolean;
  /** Undefined when nothing is selected, true when the selection cannot move. */
  selectionLocked?: boolean;
  onZoom: (zoom: number) => void;
  onSnapping: (snapping: boolean) => void;
  onRipple: (ripple: boolean) => void;
  onClipAction: (action: ClipAction) => void;
  onPlay?: () => void;
  onPause?: () => void;
};

const icon =
  "grid size-7 shrink-0 place-items-center rounded text-muted-ink transition-colors hover:bg-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-30";

const CLIP_ACTIONS = [
  ["move", "studio.timeline.moveToPlayhead", ArrowRightToLine],
  ["trim_start", "studio.timeline.trimStart", BetweenHorizontalStart],
  ["trim_end", "studio.timeline.trimEnd", BetweenHorizontalEnd],
  ["split", "studio.timeline.split", Scissors],
] as const;

// The slider moves zoom on a log scale, so each step left or right feels the same.
const ZOOM_RANGE = { min: Math.log2(MIN_ZOOM), max: Math.log2(MAX_ZOOM) };
const clampZoom = (zoom: number) => Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, zoom));

export function TimelineToolbar({
  zoom,
  snapping,
  ripple,
  playheadFrame,
  durationInFrames,
  fps,
  playing,
  selectionLocked,
  onZoom,
  onSnapping,
  onRipple,
  onClipAction,
  onPlay,
  onPause,
}: Props) {
  const { t } = useLocale();

  return (
    <div className="flex flex-wrap items-center gap-3 border-y border-hairline bg-surface px-3 py-1.5">
      <button
        type="button"
        className={`${icon} rounded-full bg-raised`}
        aria-label={t(playing ? "studio.timeline.pause" : "studio.timeline.play")}
        onClick={() => (playing ? onPause?.() : onPlay?.())}
      >
        {playing ? <Pause aria-hidden="true" size={14} /> : <Play aria-hidden="true" size={14} />}
      </button>
      <span className="font-mono text-sm tabular-nums text-ink">
        {formatTimecode(playheadFrame, fps)} / {formatTimecode(durationInFrames, fps)}
      </span>

      {/* The same operations the pointer gestures emit, for keyboard and screen readers. */}
      <div className="flex items-center gap-0.5" role="group" aria-label={t("studio.timeline.clipActions")}>
        {CLIP_ACTIONS.map(([action, label, Icon]) => (
          <button
            key={action}
            type="button"
            className={icon}
            aria-label={t(label)}
            title={t(label)}
            disabled={selectionLocked !== false}
            onClick={() => onClipAction(action)}
          >
            <Icon aria-hidden="true" size={15} />
          </button>
        ))}
      </div>
      {selectionLocked ? <p className="text-xs text-muted-ink">{t("studio.timeline.locked")}</p> : null}

      <div className="ml-auto flex items-center gap-3">
        <Switch label={t("studio.timeline.ripple")} checked={ripple} onChange={onRipple} />
        <Switch label={t("studio.timeline.snap")} checked={snapping} onChange={onSnapping} />
        <span aria-hidden="true" className="h-5 w-px bg-hairline" />
        <button
          type="button"
          className={icon}
          aria-label={t("studio.timeline.zoomOut")}
          disabled={zoom <= MIN_ZOOM}
          onClick={() => onZoom(clampZoom(zoom / 2))}
        >
          <Minus aria-hidden="true" size={15} />
        </button>
        <input
          type="range"
          aria-label={t("studio.timeline.zoom")}
          min={ZOOM_RANGE.min}
          max={ZOOM_RANGE.max}
          step="any"
          value={Math.log2(zoom)}
          onChange={(event) => onZoom(clampZoom(2 ** Number(event.target.value)))}
          className="w-32 accent-copper"
        />
        <button
          type="button"
          className={icon}
          aria-label={t("studio.timeline.zoomIn")}
          disabled={zoom >= MAX_ZOOM}
          onClick={() => onZoom(clampZoom(zoom * 2))}
        >
          <Plus aria-hidden="true" size={15} />
        </button>
      </div>
    </div>
  );
}
