import { useEffect, useLayoutEffect, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";

import { useLocale } from "@/lib/locale";
import {
  DEFAULT_TIMELINE_HEIGHT,
  MIN_TIMELINE_HEIGHT,
  clampTimelineHeight,
  maxTimelineHeight,
} from "./timeline_height";

const STEP = 16;
const LARGE_STEP = 64;

type Props = {
  height: number;
  /** The grid the two rows share; its height sets how tall the timeline may be. */
  workstation: () => HTMLElement | null;
  /** The height while a drag is under way. */
  onResize: (height: number) => void;
  /** The height to keep: a drag's end, a key, or a double-click. */
  onCommit: (height: number) => void;
};

/** The separator between the top row and the Timeline (the WAI-ARIA window splitter pattern). */
export function TimelineDivider({ height, workstation, onResize, onCommit }: Props) {
  const { t } = useLocale();
  const measure = () => workstation()?.getBoundingClientRect().height ?? 0;
  const [room, setRoom] = useState(0);
  useLayoutEffect(() => {
    const update = () => setRoom(measure());
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  // A drag in flight ends with the divider: leaving Timeline mode unmounts it.
  const stop = useRef<(() => void) | null>(null);
  useEffect(() => () => stop.current?.(), []);

  // A remembered height can be taller than this window: everything starts from what is on screen.
  const shown = (space: number) => Math.min(height, maxTimelineHeight(space));

  const start = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    event.preventDefault();
    const space = measure();
    setRoom(space);
    const pressY = event.clientY;
    const from = shown(space);
    let moved = false;
    let last = from;
    const at = (clientY: number) => clampTimelineHeight(from + pressY - clientY, space);
    const end = () => {
      stop.current = null;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      window.removeEventListener("pointercancel", cancel);
    };
    const move = (pointer: globalThis.PointerEvent) => {
      moved = true;
      last = at(pointer.clientY);
      onResize(last);
    };
    const up = (released: globalThis.PointerEvent) => {
      end();
      if (moved) onCommit(at(released.clientY));
    };
    const cancel = () => {
      end();
      if (moved) onCommit(last);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    window.addEventListener("pointercancel", cancel);
    stop.current = end;
  };

  const keys = (event: KeyboardEvent<HTMLDivElement>) => {
    const space = measure();
    const step = event.shiftKey ? LARGE_STEP : STEP;
    const next =
      event.key === "ArrowUp" ? shown(space) + step
      : event.key === "ArrowDown" ? shown(space) - step
      : event.key === "Home" ? MIN_TIMELINE_HEIGHT
      : event.key === "End" ? maxTimelineHeight(space)
      : null;
    if (next === null) return;
    // The Timeline's own shortcuts listen on the window: Home must not also seek.
    event.preventDefault();
    event.stopPropagation();
    setRoom(space);
    onCommit(clampTimelineHeight(next, space));
  };

  return (
    <div
      role="separator"
      tabIndex={0}
      aria-orientation="horizontal"
      aria-label={t("studio.timeline.resize")}
      aria-controls="studio-timeline"
      aria-valuenow={Math.round(shown(room))}
      aria-valuemin={MIN_TIMELINE_HEIGHT}
      aria-valuemax={maxTimelineHeight(room)}
      className="studio-timeline-divider focus-visible:outline-2 focus-visible:outline-copper"
      onPointerDown={start}
      onKeyDown={keys}
      // Unclamped: the rows fit it to a short window, and it is whole again when the window grows.
      onDoubleClick={() => onCommit(DEFAULT_TIMELINE_HEIGHT)}
    />
  );
}
