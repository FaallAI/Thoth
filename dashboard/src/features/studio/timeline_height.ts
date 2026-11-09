/** Limits of the Timeline row under the Studio divider (spec 2026-11-09). */
export const DEFAULT_TIMELINE_HEIGHT = 392;
export const MIN_TIMELINE_HEIGHT = 150;
export const MIN_TOP_ROW = 240;
export const DIVIDER_HEIGHT = 8;

const KEY = "thoth.studio.timelineHeight";

/** The tallest timeline a workstation of this height can give. */
export function maxTimelineHeight(workstation: number): number {
  return Math.max(MIN_TIMELINE_HEIGHT, workstation - DIVIDER_HEIGHT - MIN_TOP_ROW);
}

export function clampTimelineHeight(height: number, workstation: number): number {
  return Math.min(maxTimelineHeight(workstation), Math.max(MIN_TIMELINE_HEIGHT, Math.round(height)));
}

/** This browser's chosen height; blocked storage or a bad value means the default. */
export function readTimelineHeight(): number {
  try {
    const stored = Number(localStorage.getItem(KEY));
    return Number.isFinite(stored) && stored > 0 ? stored : DEFAULT_TIMELINE_HEIGHT;
  } catch {
    return DEFAULT_TIMELINE_HEIGHT;
  }
}

export function saveTimelineHeight(height: number): void {
  try {
    localStorage.setItem(KEY, String(height));
  } catch {
    // Only a convenience: the height still applies until the page is reloaded.
  }
}

/** Grid rows that need no measuring: the timeline gets its height only while the top row keeps its minimum. */
export function timelineRows(height: number): string {
  return `minmax(${MIN_TOP_ROW}px,1fr) ${DIVIDER_HEIGHT}px minmax(${MIN_TIMELINE_HEIGHT}px,${height}px)`;
}
