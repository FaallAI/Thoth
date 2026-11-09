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

import type { AssetGlance, EditDocumentV2 } from "@/api/control-plane";
import type { MenuHandlers } from "@/components/ContextMenu";
import { useLocale } from "@/lib/locale";
import { TimelineClip, type GestureMode } from "./TimelineClip";
import { ASSET_DRAG_TYPE, framesToPixels, type TimelineLane } from "./timeline_domain";

type Props = {
  lane: TimelineLane;
  zoom: number;
  widthInFrames: number;
  /** Every selected clip (spec 2026-11-08 §6). */
  selectedClipIds: readonly string[];
  onToggle: (field: "hidden" | "muted" | "locked", value: boolean) => void;
  onSelectClip: (clipId: string, add: boolean) => void;
  /** An asset dropped on the lane, at that many pixels from the lane's start (spec 2026-11-08 §6). */
  onDropAsset?: (assetId: string, offsetPx: number) => void;
  /** A press on the empty well that may grow into a marquee (spec 2026-11-08 §6). */
  onMarqueeStart?: (clientX: number, clientY: number) => void;
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
  /** An asset's filmstrip or peaks (Tier 3b). */
  glanceOf?: (assetId: string) => AssetGlance | undefined;
  readOnly?: boolean;
  /** The track's plain name (spec 2026-11-08 §5.1); absent, its stored label. */
  name?: string;
  /** The label controls are named by, numbered from the second track of a kind; absent, the stored label. */
  accessibleLabel?: string;
  /** A dragged clip is over this lane and the lane cannot take it. */
  refusesDrop?: boolean;
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
  selectedClipIds,
  onToggle,
  onSelectClip,
  onMarqueeStart,
  onSelectTrack,
  onSeekAt,
  clipMenu,
  laneMenu,
  nameMenu,
  onGestureStart,
  onNudge,
  labelOf,
  glanceOf,
  readOnly = false,
  name,
  onDropAsset,
  accessibleLabel,
  refusesDrop = false,
}: Props) {
  const { t } = useLocale();
  const { track, clips } = lane;
  const Icon = TRACK_ICON[track.kind];
  const values = { track: accessibleLabel ?? track.label };
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
          className="min-w-0 grow truncate text-left text-xs text-ink focus-visible:outline-2 focus-visible:outline-copper"
          title={name ?? track.label}
        >
          {name ?? track.label}
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
        data-drop={refusesDrop ? "refused" : undefined}
        className={`relative h-11 grow bg-well ${refusesDrop ? "cursor-not-allowed ring-1 ring-inset ring-destructive/60" : ""}`}
        style={{ minWidth: `${framesToPixels(widthInFrames, zoom)}px` }}
        onContextMenu={(event) => event.target === event.currentTarget && laneMenu?.onContextMenu(event)}
        onPointerUp={laneMenu?.onPointerUp}
        onPointerCancel={laneMenu?.onPointerCancel}
        onDragOver={(event) => {
          if (!onDropAsset || !Array.from(event.dataTransfer.types ?? []).includes(ASSET_DRAG_TYPE)) return;
          event.preventDefault();
          event.dataTransfer.dropEffect = "copy";
        }}
        onDrop={(event) => {
          const assetId = event.dataTransfer.getData(ASSET_DRAG_TYPE);
          if (!onDropAsset || !assetId) return;
          event.preventDefault();
          onDropAsset(assetId, event.clientX - event.currentTarget.getBoundingClientRect().left);
        }}
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget) return;
          laneMenu?.onPointerDown(event);
          if (event.button !== 0) return;
          onSeekAt?.(event.clientX - event.currentTarget.getBoundingClientRect().left);
          onMarqueeStart?.(event.clientX, event.clientY);
        }}
      >
        {clips.map((clip) => (
          <TimelineClip
            key={clip.clip_id}
            clip={clip}
            trackKind={track.kind}
            label={track.label}
            zoom={zoom}
            selected={selectedClipIds.includes(clip.clip_id)}
            locked={clip.locked === true || track.locked === true}
            onSelect={(add) => onSelectClip(clip.clip_id, add)}
            onGestureStart={(mode, clientX) => onGestureStart(clip.clip_id, mode, clientX)}
            onNudge={(frames) => onNudge(clip.clip_id, frames)}
            name={labelOf?.(clip)}
            glance={"asset_id" in clip ? glanceOf?.(clip.asset_id) : undefined}
            readOnly={readOnly}
            menu={clipMenu?.(clip)}
          />
        ))}
      </div>
    </div>
  );
}
