/**
 * Story mode's motion and emphasis (spec 2026-10-27 §5.3), as plain maths so the
 * preview and the renderer draw them from one definition.
 *
 * Motion never touches a card's pixels: it moves and scales the clip frame. Every
 * value is a canvas fraction, as the stored position is.
 */

import type { TimelineClip } from "./timeline";

type VideoClip = Extract<TimelineClip, { kind: "video" }>;
export type Motion = NonNullable<VideoClip["motion"]>;
export type MotionState = { scale: number; translateX: number };
type Placement = { x: number; y: number; scale: number };
type Box = { width: number; height: number };

export const STILL: MotionState = { scale: 1, translateX: 0 };
const ZOOM_END = 1.08;
const PAN = 0.03;
export const HIGHLIGHT = { color: "#d49a79", width: 6 } as const;
export const ARROW_SIZE = 120;

/** Linear in the clip's own frame: the first frame is the stored placement. */
export function motionTransform(motion: Motion, frame: number, durationInFrames: number): MotionState {
  const t = durationInFrames > 1 ? Math.min(1, Math.max(0, frame / (durationInFrames - 1))) : 0;
  if (motion === "slow_zoom") return { scale: 1 + (ZOOM_END - 1) * t, translateX: 0 };
  if (motion === "pan") return { scale: 1, translateX: -PAN + 2 * PAN * t };
  return STILL;
}

/**
 * The share of the clip frame the media fills. A contained still is letterboxed,
 * so a highlight hugs the card rather than the frame.
 * ponytail: a cropped clip is treated as filling its frame; crop the box too if emphasis meets crops.
 */
export function contentBox(
  fit: VideoClip["fit"],
  asset: { width?: number | null; height?: number | null } | undefined,
  canvas: { width: number; height: number },
): Box {
  if (fit !== "contain" || !asset?.width || !asset.height) return { width: 1, height: 1 };
  const media = asset.width / asset.height;
  const frame = canvas.width / canvas.height;
  return media > frame ? { width: 1, height: frame / media } : { width: media / frame, height: 1 };
}

/** Where the visible media sits on the canvas, after its placement and motion. */
export function emphasisBox(
  position: Placement | null | undefined,
  content: Box,
  motion: MotionState,
): { left: number; top: number; width: number; height: number } {
  const { x, y, scale } = position ?? { x: 0, y: 0, scale: 1 };
  const width = content.width * scale * motion.scale;
  const height = content.height * scale * motion.scale;
  return { left: 0.5 + x + motion.translateX - width / 2, top: 0.5 + y - height / 2, width, height };
}
