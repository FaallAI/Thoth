/**
 * The maths behind marks and kinetic captions (spec 2026-11-09, 3.4 and 3.5), kept apart from
 * drawing so the preview, the render and the tests share one definition.
 */

import { drawn, type Size } from "./blur";
import { speedPercent } from "./speed";
import { emphasisBox, type MotionState } from "./story_effects";

type Box = { width: number; height: number };
type Rect = { left: number; top: number; width: number; height: number };
type Crop = { left: number; top: number; width: number; height: number };
type Placement = { x: number; y: number; scale: number };

export type MarkShape = {
  kind: "box" | "arrow";
  x: number;
  y: number;
  w?: number;
  h?: number;
  from_frame: number;
  to_frame: number;
};
export type CaptionWord = { text: string; from_frame: number; duration_in_frames: number };

/** The source frame a clip shows at one of its own frames. */
export function sourceFrame(clip: { source_from_frame?: number }, frame: number): number {
  return (clip.source_from_frame ?? 0) + Math.floor((frame * speedPercent(clip)) / 100);
}

/** Marks use source frames, as blur regions do, so speed and slip keep them on their content. */
export function markWindowOpen(mark: MarkShape, clip: { source_from_frame?: number }, frame: number): boolean {
  const source = sourceFrame(clip, frame);
  return mark.from_frame <= source && source < mark.to_frame;
}

/** How a clip's media element shows its picture: the same inputs blur regions project through. */
export type MarkView = { fit?: string | null; crop: Crop; asset: Size | undefined; canvas: Box };

/**
 * Where a mark sits on the canvas, in canvas fractions, or null when it lies outside the visible
 * media. Marks are fractions of the picture, projected the way the media element draws it (crop,
 * then fit), as `blurBoxes` does; a box partly outside is cut at the frame's edge, and an arrow is a
 * point (no size).
 */
export function markBox(
  mark: MarkShape,
  view: MarkView,
  position: Placement | null | undefined,
  motion: MotionState,
): Rect | null {
  const { crop, canvas } = view;
  const elementWidth = canvas.width / (crop.width || 1);
  const elementHeight = canvas.height / (crop.height || 1);
  const elementLeft = (-crop.left / (crop.width || 1)) * canvas.width;
  const elementTop = (-crop.top / (crop.height || 1)) * canvas.height;
  const picture = drawn(view.fit ?? "cover", view.asset, elementWidth, elementHeight);
  // The clip's frame is the whole canvas before its placement and motion.
  const media = emphasisBox(position, { width: 1, height: 1 }, motion);
  const across = (value: number) => (elementLeft + picture.left + value * picture.width) / canvas.width;
  const down = (value: number) => (elementTop + picture.top + value * picture.height) / canvas.height;
  const u0 = across(mark.x);
  const v0 = down(mark.y);
  if (mark.kind === "arrow") {
    if (u0 < 0 || u0 > 1 || v0 < 0 || v0 > 1) return null;
    return { left: media.left + u0 * media.width, top: media.top + v0 * media.height, width: 0, height: 0 };
  }
  const left = Math.max(0, u0);
  const right = Math.min(1, across(mark.x + (mark.w ?? 0)));
  const top = Math.max(0, v0);
  const bottom = Math.min(1, down(mark.y + (mark.h ?? 0)));
  if (right <= left || bottom <= top) return null;
  return {
    left: media.left + left * media.width,
    top: media.top + top * media.height,
    width: (right - left) * media.width,
    height: (bottom - top) * media.height,
  };
}

/**
 * Style B's words, a few at a time: a group ends after `max` words or after a sentence mark, and a
 * lone last word joins the group before it.
 */
export function kineticGroups(words: readonly CaptionWord[], max = 4): { from: number; to: number; text: string }[] {
  const groups: CaptionWord[][] = [];
  let current: CaptionWord[] = [];
  for (const word of words) {
    current.push(word);
    if (current.length >= max || /[.,?!]$/.test(word.text)) {
      groups.push(current);
      current = [];
    }
  }
  if (current.length === 1 && groups.length > 0) groups.at(-1)!.push(current[0]!);
  else if (current.length > 0) groups.push(current);
  return groups.map((group) => ({
    from: group[0]!.from_frame,
    to: group.at(-1)!.from_frame + group.at(-1)!.duration_in_frames,
    text: group.map((word) => word.text).join(" "),
  }));
}
