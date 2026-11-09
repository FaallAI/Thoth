/**
 * What a clip shows of its asset's glance (Tier 3b): the stretch of source it plays, at its speed.
 * Pure maths, so a slipped, split, trimmed or sped-up clip draws the right frames and peaks.
 */

import type { AssetGlance } from "@/api/control-plane";
import { sourceSpan } from "./timeline_domain";

type Strip = NonNullable<AssetGlance["strip"]>;
type Peaks = NonNullable<AssetGlance["peaks"]>;
export type GlanceWindow = { fromSeconds: number; seconds: number };

/** Rounding noise from seconds-as-floats must not push a boundary into the next frame or peak. */
const EPSILON = 1e-9;
/** A very wide clip never draws more tiles than this. */
const MAX_TILES = 200;

/** The stretch of source the clip plays: from its source start, for its length times its speed. */
export function glanceWindow(
  clip: { source_from_frame?: number; duration_in_frames: number; speed?: number },
  fps: number,
): GlanceWindow {
  return { fromSeconds: (clip.source_from_frame ?? 0) / fps, seconds: sourceSpan(clip) / fps };
}

/**
 * Frames at their own shape across the clip; each shows the source frame at its left edge.
 * `frame` indexes the strip, whose frames sit `seconds_per_frame` apart from the source's start.
 */
export function stripTiles(
  strip: Strip,
  window: GlanceWindow,
  clipWidthPx: number,
  heightPx: number,
): { left: number; width: number; frame: number }[] {
  const tile = Math.max(1, Math.round((strip.frame_width * heightPx) / strip.frame_height));
  const count = Math.min(MAX_TILES, Math.ceil(clipWidthPx / tile));
  return Array.from({ length: Math.max(0, count) }, (_, index) => {
    const left = index * tile;
    const seconds = window.fromSeconds + (left / clipWidthPx) * window.seconds;
    const frame = Math.min(strip.frames - 1, Math.max(0, Math.floor(seconds / strip.seconds_per_frame + EPSILON)));
    return { left, width: Math.min(tile, clipWidthPx - left), frame };
  });
}

/** The peaks inside the window, stopping where the track ends. */
export function peakSlice(peaks: Peaks, window: GlanceWindow): number[] {
  const start = Math.max(0, Math.floor(window.fromSeconds / peaks.seconds_per_peak + EPSILON));
  const end = Math.ceil((window.fromSeconds + window.seconds) / peaks.seconds_per_peak - EPSILON);
  return peaks.values.slice(start, Math.max(start, end));
}
