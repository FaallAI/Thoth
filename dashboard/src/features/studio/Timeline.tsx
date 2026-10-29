import { useEffect, useRef, type KeyboardEvent as ReactKeyboardEvent } from "react";

import type { EditDocumentOperation } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { EditorAction, EditorState } from "./editor_state";
import type { GestureMode } from "./TimelineClip";
import { TimelineToolbar, type ClipAction } from "./TimelineToolbar";
import { TimelineTrack } from "./TimelineTrack";
import {
  formatTimecode,
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
};

/** One pointer gesture in flight. Committed on pointer up, dropped on Escape. */
type Gesture = {
  clipId: string;
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

export function Timeline({ state, dispatch, onSeek, onPlay, onPause }: Props) {
  const { t } = useLocale();
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

  // Keep the listeners' view of the editor current without re-attaching them.
  const latest = useRef({ state, dispatch, timeline, onSeek });
  latest.current = { state, dispatch, timeline, onSeek };

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
      latest.current.dispatch({
        type: "preview_timeline_operation",
        operation: operationFor(active, frameAt(active, event.clientX)),
      });
    };
    const onUp = (event: PointerEvent) => {
      const active = gesture.current;
      end();
      if (!active?.previewed) return;
      latest.current.dispatch({
        type: "commit_timeline_operation",
        operation: operationFor(active, frameAt(active, event.clientX)),
      });
    };
    const onKeyDown = (event: KeyboardEvent) => {
      const active = gesture.current;
      if (event.key !== "Escape" || !active) return;
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

  if (!timeline) return null;

  const duration = timeline.canvas.duration_in_frames;
  const lanes = visibleLanes(timeline);

  const startGesture = (clipId: string, mode: GestureMode, clientX: number) => {
    const clip = clips.find((candidate) => candidate.clip_id === clipId);
    if (!clip || clip.locked === true || trackOf(clip.track_id)?.locked === true) return;
    gesture.current = {
      clipId,
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
      />

      <div className="min-h-0 overflow-auto">
        <div
          className="relative"
          style={{ width: `${framesToPixels(duration, state.zoom) + HEADER_WIDTH}px` }}
        >
          <div className="sticky top-0 z-10 flex h-7 border-b border-hairline bg-surface">
            <div className="shrink-0 border-r border-hairline" style={{ width: HEADER_WIDTH }} />
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
            style={{ left: `${HEADER_WIDTH + framesToPixels(state.playheadFrame, state.zoom)}px` }}
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
              onToggle={(field, value) =>
                commit(
                  field === "hidden"
                    ? {
                        kind: "set_track_visibility",
                        operation_id: newId("op"),
                        track_id: lane.track.track_id,
                        hidden: value,
                      }
                    : field === "muted"
                      ? {
                          kind: "set_track_muted",
                          operation_id: newId("op"),
                          track_id: lane.track.track_id,
                          muted: value,
                        }
                      : {
                          kind: "set_track_locked",
                          operation_id: newId("op"),
                          track_id: lane.track.track_id,
                          locked: value,
                        },
                )
              }
              onSelectClip={(clipId) => dispatch({ type: "select_clip", clipId })}
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
    </section>
  );
}
