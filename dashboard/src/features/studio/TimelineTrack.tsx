import {
  AudioLines,
  Captions,
  Clapperboard,
  Eye,
  EyeOff,
  Film,
  Layers,
  Lock,
  LockOpen,
  Music,
  Volume2,
  VolumeX,
  Zap,
  type LucideIcon,
} from "lucide-react";

import type { EditDocumentV2 } from "@/api/control-plane";
import type { MenuHandlers } from "@/components/ContextMenu";
import { useLocale } from "@/lib/locale";
import { TimelineClip, type GestureMode } from "./TimelineClip";
import { framesToPixels, type TimelineLane } from "./timeline_domain";

type Props = {
  lane: TimelineLane;
  zoom: number;
  widthInFrames: number;
  selectedClipId: string;
  onToggle: (field: "hidden" | "muted" | "locked", value: boolean) => void;
  onSelectClip: (clipId: string) => void;
  /** The track for the Inspector (spec 2026-11-08 §5.1). */
  onSelectTrack?: () => void;
  /** A press on the lane's empty well, in pixels from the lane's start. */
  onSeekAt?: (offsetPx: number) => void;
  /** Right-click menus (spec 2026-11-08 §5.1): a clip's, the lane's gaps', the track's name. */
  clipMenu?: (clip: NonNullable<EditDocumentV2["clips"]>[number]) => MenuHandlers;
  laneMenu?: MenuHandlers;
  nameMenu?: MenuHandlers;
  onGestureStart: (clipId: string, mode: GestureMode, clientX: number) => void;
  onNudge: (clipId: string, frames: number) => void;
  /** The clip's human name (spec 2026-11-01); absent, the Timeline's own words for it. */
  labelOf?: (clip: NonNullable<EditDocumentV2["clips"]>[number]) => string;
  readOnly?: boolean;
};

type TrackKind = TimelineLane["track"]["kind"];

const TRACK_ICON: Record<TrackKind, LucideIcon> = {
  main_video: Film,
  b_roll: Clapperboard,
  overlay: Layers,
  caption: Captions,
  narration: AudioLines,
  music: Music,
  sfx: Zap,
};

const toggleClass =
  "grid size-6 place-items-center rounded text-faint transition-colors hover:bg-raised hover:text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-30";

export function TimelineTrack({
  lane,
  zoom,
  widthInFrames,
  selectedClipId,
  onToggle,
  onSelectClip,
  onSelectTrack,
  onSeekAt,
  clipMenu,
  laneMenu,
  nameMenu,
  onGestureStart,
  onNudge,
  labelOf,
  readOnly = false,
}: Props) {
  const { t } = useLocale();
  const { track, clips } = lane;
  const Icon = TRACK_ICON[track.kind];
  const values = { track: track.label };
  // A locked track keeps its own lock button live; everything else waits for it.
  const toggles = [
    ["hidden", track.hidden === true, t(track.hidden ? "studio.timeline.showTrack" : "studio.timeline.hideTrack", values), track.hidden ? EyeOff : Eye],
    ["muted", track.muted === true, t(track.muted ? "studio.timeline.unmuteTrack" : "studio.timeline.muteTrack", values), track.muted ? VolumeX : Volume2],
    ["locked", track.locked === true, t(track.locked ? "studio.timeline.unlockTrack" : "studio.timeline.lockTrack", values), track.locked ? Lock : LockOpen],
  ] as const;

  return (
    <div
      role="group"
      aria-label={t("studio.timeline.track", values)}
      data-track-id={track.track_id}
      id={`timeline-track-${track.track_id}`}
      className="flex border-b border-hairline"
    >
      {/* The name stays in sight while the lanes scroll; a view-only phone gives it a quarter of the screen. */}
      {/* A click anywhere on the name column but its toggles selects the track. */}
      <div
        className={`group sticky left-0 z-[5] flex shrink-0 items-center gap-2 border-r border-hairline bg-surface ${readOnly ? "w-24 px-2" : "w-48 px-3"} ${onSelectTrack ? "cursor-pointer" : ""}`}
        {...nameMenu}
        onClick={(event) => {
          if ((event.target as HTMLElement).closest("button:not([data-track-name])")) return;
          onSelectTrack?.();
        }}
      >
        {readOnly ? null : <Icon aria-hidden="true" size={15} className="shrink-0 text-muted-ink" />}
        <button
          type="button"
          data-track-name
          aria-label={t("studio.timeline.selectTrack", values)}
          className="min-w-0 grow truncate text-left font-mono text-xs text-ink focus-visible:outline-2 focus-visible:outline-copper"
          title={track.label}
        >
          {track.kind}
        </button>
        {/* A state that is on stays in sight; the toggles themselves show on hover and focus. */}
        {toggles
          .filter(([, value]) => value)
          .map(([field, , , StateIcon]) => (
            <StateIcon key={field} aria-hidden="true" size={12} className="shrink-0 text-faint" />
          ))}
        <div className="absolute inset-y-0 right-1 flex items-center gap-0.5 bg-surface pl-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {/* A view-only Timeline (below 1024) changes nothing, lanes included. */}
          {(readOnly ? [] : toggles).map(([field, value, label, ToggleIcon]) => (
            <button
              key={field}
              type="button"
              className={toggleClass}
              disabled={field !== "locked" && track.locked === true}
              aria-label={label}
              title={label}
              onClick={() => onToggle(field, !value)}
            >
              <ToggleIcon aria-hidden="true" size={13} />
            </button>
          ))}
        </div>
      </div>
      <div
        data-lane-well
        className="relative h-11 grow bg-well"
        style={{ minWidth: `${framesToPixels(widthInFrames, zoom)}px` }}
        onContextMenu={(event) => event.target === event.currentTarget && laneMenu?.onContextMenu(event)}
        onPointerUp={laneMenu?.onPointerUp}
        onPointerCancel={laneMenu?.onPointerCancel}
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget) return;
          laneMenu?.onPointerDown(event);
          if (event.button !== 0) return;
          onSeekAt?.(event.clientX - event.currentTarget.getBoundingClientRect().left);
        }}
      >
        {clips.map((clip) => (
          <TimelineClip
            key={clip.clip_id}
            clip={clip}
            trackKind={track.kind}
            label={track.label}
            zoom={zoom}
            selected={clip.clip_id === selectedClipId}
            locked={clip.locked === true || track.locked === true}
            onSelect={() => onSelectClip(clip.clip_id)}
            onGestureStart={(mode, clientX) => onGestureStart(clip.clip_id, mode, clientX)}
            onNudge={(frames) => onNudge(clip.clip_id, frames)}
            name={labelOf?.(clip)}
            readOnly={readOnly}
            menu={clipMenu?.(clip)}
          />
        ))}
      </div>
    </div>
  );
}
