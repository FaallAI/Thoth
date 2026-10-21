/**
 * Where a clip's subtitle blur is drawn, and how strongly (spec 2026-10-21 5c-1, 3.4 and 5.2).
 *
 * Regions are fractions of the SOURCE frame and windows are SOURCE frames, so a box is
 * projected through the same fit, crop and position the media is drawn with. Strength is set
 * on the canvas: sigma = max(BLUR_FLOOR, BLUR_FACTOR x the region's canvas height), measured
 * against eye checks of real subtitle bands (two lines in 169 px were still readable at 16).
 */

import type { TimelineClip } from "./timeline";

type VideoClip = Extract<TimelineClip, { kind: "video" }>;

/** The weakest blur on the canvas, in pixels: a 109 px band needs about 24 to vanish. */
export const BLUR_FLOOR = 24;
/** Blur as a share of the region's canvas height: a 169 px band gets about 34. */
export const BLUR_FACTOR = 0.2;

export type BlurBox = {
  /** Clip-frame pixels, before the frame's own translate and scale. */
  left: number;
  top: number;
  width: number;
  height: number;
  /** Gaussian standard deviation in clip-frame pixels; CSS blur() takes the same value. */
  sigma: number;
  /** Clip-relative frames, or null for the whole clip. */
  from: number | null;
  to: number | null;
};

type Size = { width?: number | null; height?: number | null };

export function blurBoxes(
  clip: Pick<VideoClip, "fit" | "crop" | "position" | "source_from_frame" | "blur_regions">,
  asset: Size | undefined,
  canvas: { width: number; height: number },
): BlurBox[] {
  const crop = clip.crop ?? { left: 0, top: 0, width: 1, height: 1 };
  const scale = clip.position?.scale ?? 1;
  // The media element, enlarged and offset by the crop exactly as the composition draws it.
  const boxWidth = canvas.width / (crop.width || 1);
  const boxHeight = canvas.height / (crop.height || 1);
  const boxLeft = (-crop.left / (crop.width || 1)) * canvas.width;
  const boxTop = (-crop.top / (crop.height || 1)) * canvas.height;
  const picture = drawn(clip.fit ?? "cover", asset, boxWidth, boxHeight);
  const trim = clip.source_from_frame ?? 0;
  // A window that ends at or before the clip's trim (after a split or trim) shows nothing.
  const visible = (clip.blur_regions ?? []).filter(
    (region) => region.to_frame == null || region.to_frame > trim,
  );
  return visible.map((region) => {
    const height = region.h * picture.height;
    const sigma = Math.max(BLUR_FLOOR / scale, BLUR_FACTOR * height);
    const windowed = region.from_frame != null && region.to_frame != null;
    return {
      left: boxLeft + picture.left + region.x * picture.width - sigma,
      top: boxTop + picture.top + region.y * picture.height - sigma,
      width: region.w * picture.width + 2 * sigma,
      height: height + 2 * sigma,
      sigma,
      from: windowed ? Math.max(0, region.from_frame! - trim) : null,
      to: windowed ? Math.max(0, region.to_frame! - trim) : null,
    };
  });
}

/** The source picture inside its element box under object-fit; the box itself when unsized. */
function drawn(fit: string, asset: Size | undefined, width: number, height: number) {
  if (!asset?.width || !asset.height || fit === "fill") {
    return { left: 0, top: 0, width, height };
  }
  const ratio =
    fit === "contain"
      ? Math.min(width / asset.width, height / asset.height)
      : Math.max(width / asset.width, height / asset.height);
  const pictureWidth = asset.width * ratio;
  const pictureHeight = asset.height * ratio;
  return {
    left: (width - pictureWidth) / 2,
    top: (height - pictureHeight) / 2,
    width: pictureWidth,
    height: pictureHeight,
  };
}
