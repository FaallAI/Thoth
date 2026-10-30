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
  onGestureStart: (clipId: string, mode: GestureMode, clientX: number) => void;
  onNudge: (clipId: string, frames: number) => void;
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
  onGestureStart,
  onNudge,
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
      <div className="group relative flex w-48 shrink-0 items-center gap-2 border-r border-hairline bg-surface px-3">
        <Icon aria-hidden="true" size={15} className="shrink-0 text-muted-ink" />
        <span className="min-w-0 grow truncate font-mono text-xs text-ink" title={track.label}>
          {track.kind}
        </span>
        {/* A state that is on stays in sight; the toggles themselves show on hover and focus. */}
        {toggles
          .filter(([, value]) => value)
          .map(([field, , , StateIcon]) => (
            <StateIcon key={field} aria-hidden="true" size={12} className="shrink-0 text-faint" />
          ))}
        <div className="absolute inset-y-0 right-1 flex items-center gap-0.5 bg-surface pl-1 opacity-0 transition-opacity group-hover:opacity-100 group-focus-within:opacity-100">
          {toggles.map(([field, value, label, ToggleIcon]) => (
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
        className="relative h-11 grow bg-well"
        style={{ minWidth: `${framesToPixels(widthInFrames, zoom)}px` }}
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
          />
        ))}
      </div>
    </div>
  );
}
