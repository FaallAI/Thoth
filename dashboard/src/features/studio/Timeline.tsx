import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import type { EditDocumentOperation, EditDocumentV2, EditorAsset } from "@/api/control-plane";
import { useContextMenu } from "@/components/ContextMenu";
import { useLocale } from "@/lib/locale";
import type { EditorAction, EditorState } from "./editor_state";
import { clipLabel, type GestureMode } from "./TimelineClip";
import { TimelineToolbar, type ClipAction } from "./TimelineToolbar";
import { TimelineTrack } from "./TimelineTrack";
import { ReplaceMediaDialog } from "./ReplaceMediaDialog";
import { clipMenu, gapMenu, trackMenu, type MenuContext } from "./timeline_menus";
import { isTypingTarget, timelineKey } from "./studio_keys";
import { deleteClip, rippleDelete, splitAt } from "./timeline_edits";
import {
  clampZoom,
  compatibleTrackIds,
  formatTimecode,
  trackName,
  framesToPixels,
  rulerTicks,
  isTimelineDocument,
  snapCandidates,
  snapFrame,
  visibleLanes,
} from "./timeline_domain";

type Props = {
  state: EditorState;
  dispatch: (action: EditorAction) => void;
  /** Preview transport, absent wherever the timeline renders without a player. */
  onSeek?: (frame: number) => void;
  onPlay?: () => void;
  onPause?: () => void;
  /** The clip's human name (spec 2026-11-01); absent, the Timeline's own words for it. */
  labelOf?: (clip: NonNullable<EditDocumentV2["clips"]>[number]) => string;
  /** Below 1024 the lanes are a view (spec 2026-11-01); a tapped clip offers Inspect. */
  readOnly?: boolean;
  onInspect?: () => void;
  /** The beat a clip belongs to in Story, or null; with `onShowInStory`, the menu's "Show in Story". */
  beatOf?: (clipId: string) => string | null;
  onShowInStory?: (clipId: string) => void;
  /** An asset's human name, for Replace media; absent, its kind. */
  assetName?: (asset: EditorAsset) => string;
};

/** One pointer gesture in flight. Committed on pointer up, dropped on Escape. */
type Gesture = {
  clipId: string;
  clipKind: NonNullable<EditDocumentV2["clips"]>[number]["kind"];
  /** The clip's own track: the lane a drag falls back to over an incompatible one. */
  homeTrackId: string;
  trackId: string;
  mode: GestureMode;
  originX: number;
  anchor: number;
  operationId: string;
  previewed: boolean;
};

const newId = (prefix: string) => `${prefix}_${crypto.randomUUID()}`;

/** Snap within a fixed screen distance, so zooming out does not widen the pull. */
const snapThreshold = (zoom: number) => Math.max(1, Math.round(8 / zoom));

/** The header column beside every lane; the ruler and the playhead start after it. */
const HEADER_WIDTH = 192;
const READ_ONLY_HEADER_WIDTH = 96;

export function Timeline({
  state,
  dispatch,
  onSeek,
  onPlay,
  onPause,
  labelOf,
  readOnly = false,
  onInspect,
  beatOf,
  onShowInStory,
  assetName,
}: Props) {
  const { t } = useLocale();
  const headerWidth = readOnly ? READ_ONLY_HEADER_WIDTH : HEADER_WIDTH;
  const gesture = useRef<Gesture | null>(null);
  // The ruler under a press: pointer moves seek until the pointer is released.
  const scrubbing = useRef<HTMLElement | null>(null);
  const timeline = isTimelineDocument(state.draft) ? state.draft : undefined;
  const clips = timeline?.clips ?? [];
  const selectedClip = clips.find((clip) => clip.clip_id === state.selectedClipId);
  const trackOf = (trackId: string) => timeline?.tracks.find((t) => t.track_id === trackId);
  const selectionLocked = selectedClip
    ? selectedClip.locked === true || trackOf(selectedClip.track_id)?.locked === true
    : undefined;

  // The lanes' scroll box: Ctrl+0 fits the canvas into its width.
  const lanesBox = useRef<HTMLDivElement>(null);
  // One right-click menu for clips, gaps and tracks (spec 2026-11-08 §5.1), and the clip being replaced.
  const menu = useContextMenu();
  const [replacing, setReplacing] = useState<string | null>(null);

  // Keep the listeners' view of the editor current without re-attaching them.
  const latest = useRef({ state, dispatch, timeline, onSeek, onPlay, onPause, readOnly });
  latest.current = { state, dispatch, timeline, onSeek, onPlay, onPause, readOnly };

  /** Move the playhead and the preview to one frame, kept inside the document. */
  const seek = (frame: number) => {
    const { dispatch: send, timeline: doc, onSeek: follow } = latest.current;
    const last = Math.max(0, (doc?.canvas.duration_in_frames ?? 1) - 1);
    const clamped = Math.min(last, Math.max(0, Math.round(frame)));
    send({ type: "set_playhead", frame: clamped });
    follow?.(clamped);
  };
  const seekToPointer = (ruler: HTMLElement, clientX: number) =>
    seek((clientX - ruler.getBoundingClientRect().left) / latest.current.state.zoom);

  /** Where a gesture lands, after snapping, for a pointer at `clientX`. */
  const frameAt = (active: Gesture, clientX: number) => {
    const { state: current, timeline: doc } = latest.current;
    if (!doc) return active.anchor;
    const raw = Math.max(0, active.anchor + Math.round((clientX - active.originX) / current.zoom));
    if (!current.snapping) return raw;
    const candidates = snapCandidates(doc, {
      excludeClipId: active.clipId,
      playhead: current.playheadFrame,
    });
    return snapFrame(raw, candidates, snapThreshold(current.zoom));
  };

  /** A move follows the pointer onto another lane that can hold the clip (spec 2026-11-08 §5.1). */
  const followLane = (active: Gesture, clientX: number, clientY: number) => {
    const doc = latest.current.timeline;
    if (active.mode !== "move" || !doc || !document.elementsFromPoint) return;
    const lane = document
      .elementsFromPoint(clientX, clientY)
      .map((element) => element.closest<HTMLElement>("[data-track-id]"))
      .find(Boolean);
    const trackId = lane?.dataset.trackId;
    active.trackId =
      trackId && (trackId === active.homeTrackId || compatibleTrackIds(doc, active.clipKind).includes(trackId))
        ? trackId
        : active.homeTrackId;
  };

  const operationFor = (active: Gesture, frame: number): EditDocumentOperation => {
    switch (active.mode) {
      case "trim_start":
        return {
          kind: "trim_clip_start",
          operation_id: active.operationId,
          clip_id: active.clipId,
          from_frame: frame,
        };
      case "trim_end":
        return {
          kind: "trim_clip_end",
          operation_id: active.operationId,
          clip_id: active.clipId,
          end_frame: frame,
        };
      default:
        return {
          kind: "move_clip",
          operation_id: active.operationId,
          clip_id: active.clipId,
          target_track_id: active.trackId,
          from_frame: frame,
          ripple: latest.current.state.ripple,
        };
    }
  };

  // Pointer and Escape handling lives on the window so a gesture survives the
  // pointer leaving the clip it started on.
  useEffect(() => {
    const end = () => {
      gesture.current = null;
      scrubbing.current = null;
    };
    const onMove = (event: PointerEvent) => {
      if (scrubbing.current) {
        seekToPointer(scrubbing.current, event.clientX);
        return;
      }
      const active = gesture.current;
      if (!active) return;
      active.previewed = true;
      followLane(active, event.clientX, event.clientY);
      latest.current.dispatch({
        type: "preview_timeline_operation",
        operation: operationFor(active, frameAt(active, event.clientX)),
      });
    };
    const onUp = (event: PointerEvent) => {
      const active = gesture.current;
      end();
      if (!active?.previewed) return;
      followLane(active, event.clientX, event.clientY);
      latest.current.dispatch({
        type: "commit_timeline_operation",
        operation: operationFor(active, frameAt(active, event.clientX)),
      });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const active = gesture.current;
      if (event.key !== "Escape" || !active) return;
      // Escape drops the drag first; the editing keys below then leave the selection alone.
      event.preventDefault();
      end();
      if (active.previewed) latest.current.dispatch({ type: "cancel_timeline_preview" });
    };

    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", end);
    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", end);
      window.removeEventListener("keydown", onKeyDown);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps -- listeners read `latest`.
  }, []);

  // Spec 2026-11-08 §5.1: the editing keys, never while a person types in a field.
  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const { state: current, dispatch: send, timeline: doc, onPlay: play, onPause: pause, readOnly: viewOnly } = latest.current;
      if (!doc || viewOnly || event.defaultPrevented || isTypingTarget(event.target)) return;
      const action = timelineKey(event);
      if (!action) return;
      const target = event.target as HTMLElement | null;
      // Space keeps its own meaning on a button, a checkbox or a list.
      if (action === "play" && target?.closest?.("button, input, select, [role='slider']")) return;
      const fpsNow = doc.canvas.fps;
      const commitEdit = (operations: EditDocumentOperation[]) => {
        if (operations.length) send({ type: "commit_operations", operations });
      };
      const clipId = current.selectedClipId;
      switch (action) {
        case "delete":
          if (!clipId) return;
          commitEdit(deleteClip(doc, clipId).operations);
          break;
        case "ripple_delete":
          if (!clipId) return;
          commitEdit(rippleDelete(doc, clipId).operations);
          break;
        case "split":
          if (!clipId) return;
          commitEdit(splitAt(doc, clipId, current.playheadFrame).operations);
          break;
        case "play":
          (current.playing ? pause : play)?.();
          break;
        case "start":
          seek(0);
          break;
        case "end":
          seek(doc.canvas.duration_in_frames - 1);
          break;
        case "frame_back":
        case "frame_forward":
        case "second_back":
        case "second_forward": {
          const step = action.startsWith("second") ? Math.max(1, fpsNow) : 1;
          seek(current.playheadFrame + (action.endsWith("back") ? -step : step));
          break;
        }
        case "zoom_in":
          send({ type: "set_zoom", zoom: clampZoom(current.zoom * 2) });
          break;
        case "zoom_out":
          send({ type: "set_zoom", zoom: clampZoom(current.zoom / 2) });
          break;
        case "zoom_fit": {
          const width = (lanesBox.current?.clientWidth ?? 0) - (viewOnly ? READ_ONLY_HEADER_WIDTH : HEADER_WIDTH);
          if (width <= 0) return;
          send({ type: "set_zoom", zoom: clampZoom(width / doc.canvas.duration_in_frames) });
          break;
        }
        case "clear":
          if (!clipId) return;
          send({ type: "select_clip", clipId: "" });
          break;
      }
      event.preventDefault();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the listener reads `latest`.
  }, []);

  // Ctrl+wheel zooms around the pointer; a plain wheel scrolls as always. Native, so it may cancel the page zoom.
  const hasTimeline = Boolean(timeline);
  useEffect(() => {
    const box = lanesBox.current;
    if (!box) return;
    const onWheel = (event: WheelEvent) => {
      if (!(event.ctrlKey || event.metaKey) || !event.deltaY) return;
      event.preventDefault();
      const { state: current, dispatch: send, readOnly: viewOnly } = latest.current;
      const header = viewOnly ? READ_ONLY_HEADER_WIDTH : HEADER_WIDTH;
      const zoom = clampZoom(event.deltaY > 0 ? current.zoom / 1.25 : current.zoom * 1.25);
      const pointer = event.clientX - box.getBoundingClientRect().left - header;
      const frame = (box.scrollLeft + pointer) / current.zoom;
      send({ type: "set_zoom", zoom });
      requestAnimationFrame(() => {
        box.scrollLeft = Math.max(0, frame * zoom - pointer);
      });
    };
    box.addEventListener("wheel", onWheel, { passive: false });
    return () => box.removeEventListener("wheel", onWheel);
  }, [hasTimeline]);

  if (!timeline) return null;

  const duration = timeline.canvas.duration_in_frames;
  const lanes = visibleLanes(timeline);

  const startGesture = (clipId: string, mode: GestureMode, clientX: number) => {
    const clip = clips.find((candidate) => candidate.clip_id === clipId);
    if (!clip || clip.locked === true || trackOf(clip.track_id)?.locked === true) return;
    gesture.current = {
      clipId,
      clipKind: clip.kind,
      homeTrackId: clip.track_id,
      trackId: clip.track_id,
      mode,
      originX: clientX,
      anchor: mode === "trim_end" ? clip.from_frame + clip.duration_in_frames : clip.from_frame,
      operationId: newId("op"),
      previewed: false,
    };
  };

  const fps = timeline.canvas.fps;
  const onRulerKey = (event: ReactKeyboardEvent) => {
    const step = event.shiftKey ? Math.max(1, fps) : 1;
    const target = {
      ArrowRight: state.playheadFrame + step,
      ArrowLeft: state.playheadFrame - step,
      Home: 0,
      End: duration - 1,
    }[event.key];
    if (target === undefined) return;
    event.preventDefault();
    seek(target);
  };

  const commit = (operation: EditDocumentOperation) =>
    dispatch({ type: "commit_timeline_operation", operation });

  const toggleTrack = (trackId: string, field: "hidden" | "muted" | "locked", value: boolean) =>
    commit(
      field === "hidden"
        ? { kind: "set_track_visibility", operation_id: newId("op"), track_id: trackId, hidden: value }
        : field === "muted"
          ? { kind: "set_track_muted", operation_id: newId("op"), track_id: trackId, muted: value }
          : { kind: "set_track_locked", operation_id: newId("op"), track_id: trackId, locked: value },
    );

  const menuContext: MenuContext = {
    t,
    doc: timeline,
    playheadFrame: state.playheadFrame,
    commit: (operations) => {
      if (operations.length) dispatch({ type: "commit_operations", operations });
    },
    trackName: (track) => trackName(t, timeline, track),
  };
  const replaced = clips.find((clip) => clip.clip_id === replacing);
  const replacedAsset = replaced && "asset_id" in replaced ? replaced.asset_id : undefined;

  const clipAction = (action: ClipAction) => {
    if (!selectedClip || selectionLocked) return;
    const frame = state.playheadFrame;
    if (action === "split") {
      commit({
        kind: "split_clip",
        operation_id: newId("op"),
        clip_id: selectedClip.clip_id,
        split_frame: frame,
        left_clip_id: newId("clip"),
        right_clip_id: newId("clip"),
      });
      return;
    }
    commit(
      operationFor(
        {
          clipId: selectedClip.clip_id,
          clipKind: selectedClip.kind,
          homeTrackId: selectedClip.track_id,
          trackId: selectedClip.track_id,
          mode: action,
          originX: 0,
          anchor: frame,
          operationId: newId("op"),
          previewed: false,
        },
        frame,
      ),
    );
  };

  return (
    <section className="flex min-h-0 flex-col" aria-label="Timeline">
      <TimelineToolbar
        zoom={state.zoom}
        snapping={state.snapping}
        ripple={state.ripple}
        playheadFrame={state.playheadFrame}
        durationInFrames={duration}
        fps={timeline.canvas.fps}
        playing={state.playing}
        selectionLocked={selectionLocked}
        onPlay={onPlay}
        onPause={onPause}
        onZoom={(zoom) => dispatch({ type: "set_zoom", zoom })}
        onSnapping={(snapping) => dispatch({ type: "set_snapping", snapping })}
        onRipple={(ripple) => dispatch({ type: "set_ripple", ripple })}
        onClipAction={clipAction}
        readOnly={readOnly}
      />
      {readOnly ? (
        <p className="flex items-center gap-2 border-b border-hairline bg-surface px-3 py-2 text-xs text-muted-ink">{t("studio.timeline.viewOnly")}</p>
      ) : null}

      <div ref={lanesBox} data-testid="timeline-lanes" className="min-h-0 overflow-auto">
        <div
          className="relative"
          style={{ width: `${framesToPixels(duration, state.zoom) + headerWidth}px` }}
        >
          <div className="sticky top-0 z-10 flex h-7 border-b border-hairline bg-surface">
            <div className="sticky left-0 z-10 shrink-0 border-r border-hairline bg-surface" style={{ width: headerWidth }} />
            <div
              role="slider"
              tabIndex={0}
              aria-label={t("studio.timeline.playhead")}
              aria-valuemin={0}
              aria-valuemax={Math.max(0, duration - 1)}
              aria-valuenow={state.playheadFrame}
              aria-valuetext={formatTimecode(state.playheadFrame, fps)}
              className="relative grow cursor-pointer focus-visible:outline-2 focus-visible:outline-copper"
              onPointerDown={(event) => {
                if (event.button !== 0) return;
                scrubbing.current = event.currentTarget;
                seekToPointer(event.currentTarget, event.clientX);
              }}
              onKeyDown={onRulerKey}
            >
              {rulerTicks(duration, fps, state.zoom).map((tick) => (
                <span
                  key={tick.frame}
                  aria-hidden="true"
                  className="absolute bottom-0 top-0 border-l border-hairline pl-1 pt-1 font-mono text-[0.7rem] text-faint"
                  style={{ left: `${framesToPixels(tick.frame, state.zoom)}px` }}
                >
                  {tick.label}
                </span>
              ))}
            </div>
          </div>
          <div
            aria-hidden="true"
            className="pointer-events-none absolute bottom-0 top-0 z-20 w-px bg-playhead"
            style={{ left: `${headerWidth + framesToPixels(state.playheadFrame, state.zoom)}px` }}
          >
            <span className="absolute -left-1.5 top-0.5 size-3 rounded-full bg-playhead" />
          </div>
          {lanes.map((lane) => (
            <TimelineTrack
              key={lane.track.track_id}
              lane={lane}
              zoom={state.zoom}
              widthInFrames={duration}
              selectedClipId={state.selectedClipId}
              labelOf={labelOf}
              readOnly={readOnly}
              name={trackName(t, timeline, lane.track)}
              onToggle={(field, value) => toggleTrack(lane.track.track_id, field, value)}
              clipMenu={
                readOnly
                  ? undefined
                  : (clip) =>
                      menu.bind(() =>
                        clipMenu(menuContext, clip, {
                          onReplace: () => setReplacing(clip.clip_id),
                          storyBeat: beatOf?.(clip.clip_id) ?? null,
                          onShowInStory: onShowInStory ? () => onShowInStory(clip.clip_id) : undefined,
                        }),
                      )
              }
              laneMenu={
                readOnly
                  ? undefined
                  : menu.bind((at) =>
                      gapMenu(menuContext, lane.track.track_id, Math.floor((at.x - at.owner.getBoundingClientRect().left) / state.zoom)),
                    )
              }
              nameMenu={
                readOnly
                  ? undefined
                  : menu.bind(() =>
                      trackMenu(menuContext, lane.track, {
                        onSelect: () => dispatch({ type: "select_track", trackId: lane.track.track_id }),
                        onToggle: (field, value) => toggleTrack(lane.track.track_id, field, value),
                      }),
                    )
              }
              onSelectClip={(clipId) => dispatch({ type: "select_clip", clipId })}
              onSelectTrack={() => dispatch({ type: "select_track", trackId: lane.track.track_id })}
              onSeekAt={(offset) => {
                seek(offset / state.zoom);
                if (state.selectedClipId) dispatch({ type: "select_clip", clipId: "" });
              }}
              onGestureStart={startGesture}
              onNudge={(clipId, frames) => {
                const clip = clips.find((candidate) => candidate.clip_id === clipId);
                if (!clip) return;
                commit({
                  kind: "move_clip",
                  operation_id: newId("op"),
                  clip_id: clipId,
                  target_track_id: clip.track_id,
                  from_frame: Math.max(0, clip.from_frame + frames),
                  ripple: state.ripple,
                });
              }}
            />
          ))}
        </div>
      </div>
      {menu.element}
      {replaced && replacedAsset ? (
        <ReplaceMediaDialog
          currentAssetId={replacedAsset}
          kind={timeline.asset_refs?.find((ref) => ref.asset_id === replacedAsset)?.kind === "image" ? "image" : "video"}
          assets={Object.values(state.assets)}
          nameOf={(asset) => assetName?.(asset) ?? t(`studio.label.kind.${asset.kind}`)}
          onClose={() => setReplacing(null)}
          onReplace={(assetId) => {
            setReplacing(null);
            dispatch({
              type: "commit_operations",
              operations: [{ kind: "replace_clip_asset", operation_id: newId("op"), clip_id: replaced.clip_id, asset_id: assetId }],
            });
          }}
        />
      ) : null}
      {readOnly && selectedClip ? (
        <div className="flex items-center gap-3 border-t border-hairline bg-surface px-3 py-2">
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm text-ink">{labelOf?.(selectedClip) ?? clipLabel(t, selectedClip)}</span>
            <span className="block font-mono text-xs text-muted-ink">
              {formatTimecode(selectedClip.from_frame, fps)}–{formatTimecode(selectedClip.from_frame + selectedClip.duration_in_frames, fps)}
            </span>
          </span>
          <button type="button" onClick={onInspect} className="rounded-md border border-hairline px-3 py-1.5 text-[13px] text-copper focus-visible:outline-2 focus-visible:outline-copper">
            {t("studio.timeline.inspect")}
          </button>
        </div>
      ) : null}
    </section>
  );
}
