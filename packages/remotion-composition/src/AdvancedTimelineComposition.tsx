import { Video } from "@remotion/media";
import { AbsoluteFill, Audio, Freeze, Img, Sequence, useCurrentFrame } from "remotion";
import { Fragment, type CSSProperties, type ReactNode } from "react";

import type { EditDocumentV2, TimelineClip } from "./timeline";
import { blurBoxes } from "./blur";
import { kineticGroups, markBox, markWindowOpen, sourceFrame, type MarkShape, type MarkView } from "./effects";
import { moveAt } from "./moves";
import { speedPercent } from "./speed";
import { visibleLanes } from "./timeline";
import { safePreviewSource } from "./media";
import { COMPOSITION_FONT_FAMILY, useCompositionFonts } from "./fonts";
import {
  ARROW_SIZE,
  HIGHLIGHT,
  STILL,
  contentBox,
  emphasisBox,
  motionTransform,
  type MotionState,
} from "./story_effects";

type OverlayClip = Extract<TimelineClip, { kind: "overlay" }>;
type AssetRef = NonNullable<EditDocumentV2["asset_refs"]>[number];
type VideoClip = Extract<TimelineClip, { kind: "video" }>;

/** A style the document may select by name, resolved to a local style object. */
type TrustedStyle = { name: string; style: CSSProperties };

/** Preview media, keyed by asset ID. Never persisted into a document revision. */
export type PreviewSources = Record<string, string>;

type Props = {
  document: EditDocumentV2;
  previewSources?: PreviewSources;
  onPreviewUnavailable?: (assetId: string) => void;
};

/**
 * Styling is inline on purpose: the server bundle has no CSS pipeline, so a
 * class name would render in the browser and vanish in the rendered file.
 */
const CANVAS: CSSProperties = {
  backgroundColor: "#09090b",
  color: "#ffffff",
  // Set once at the root: every glyph below inherits the family this package
  // ships, so nothing drawn depends on what the host has installed.
  fontFamily: COMPOSITION_FONT_FAMILY,
};
const TEXT_CLIP: CSSProperties = {
  alignItems: "center",
  justifyContent: "center",
  gap: 24,
  padding: 64,
  textAlign: "center",
};
const HEADING: CSSProperties = { maxWidth: "80%", fontSize: 60, fontWeight: 700, lineHeight: 1.25 };
const BODY: CSSProperties = { maxWidth: "72%", fontSize: 30, color: "#d4d4d8" };
/** A placed heading: two lines on a scrim, the draft keeping whatever the ellipsis cuts. */
const PLACED_TEXT: CSSProperties = {
  alignItems: "center",
  textAlign: "center",
};
const HEADING_SCRIM: CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: 16,
  maxWidth: "88%",
  padding: "28px 36px",
  borderRadius: 22,
  backgroundColor: "rgba(0, 0, 0, 0.65)",
};
const PLACED_HEADING: CSSProperties = {
  margin: 0,
  fontSize: 60,
  fontWeight: 700,
  lineHeight: 1.25,
  display: "-webkit-box",
  WebkitBoxOrient: "vertical",
  WebkitLineClamp: 2,
  lineClamp: 2,
  overflow: "hidden",
};
const HEADING_CHAR_WIDTH = 30;
/** Above TikTok's top interface; lower keeps clear of its bottom 18% and of the caption lane. */
const HEADING_TOP_SAFE = 0.08;
const HEADING_LOWER_SAFE = 0.3;
/** The two slots that place a heading; any other draws mid-frame as every older draft does. */
const HEADING_PLACES = new Set(["title_top", "title_lower"]);
const TEXT_CARD: CSSProperties = {
  backgroundColor: "#ffffff",
  alignItems: "center",
  justifyContent: "center",
  padding: "0 80px",
};
const TEXT_CARD_HEADING: CSSProperties = {
  margin: 0,
  color: "#111111",
  fontSize: 84,
  fontWeight: 800,
  lineHeight: 1.1,
  textAlign: "center",
};
/**
 * Blur-fill blurs an eighth-size copy and scales it up 8.8 times (cover plus a 10% bleed), which looks
 * like blur(48px) at full size. A still takes a CSS blur, drawn once; a movie is blurred inside its
 * canvas, since a CSS blur over a layer that changes every frame made a 60 s render five times slower
 * (plan 2026-11-09, Task 8).
 */
const BLUR_FILL_RADIUS = "blur(6px)";
const BLUR_FILL_LAYER: CSSProperties = {
  position: "absolute",
  left: "50%",
  top: "50%",
  width: "12.5%",
  height: "12.5%",
  transform: "translate(-50%, -50%) scale(8.8)",
};
const BLUR_FILL_MEDIA: CSSProperties = { width: "100%", height: "100%", objectFit: "cover" };

/**
 * About how many characters two lines of a placed heading hold on this canvas.
 * ponytail: an average glyph width, not a measurement; measure the font if wide scripts cut early.
 */
export function headingFitChars(canvas: { width: number }): number {
  const inner = canvas.width * 0.88 - 72;
  return 2 * Math.floor(inner / HEADING_CHAR_WIDTH);
}
const CAPTION_LANE: CSSProperties = {
  alignItems: "center",
  justifyContent: "flex-end",
  padding: 64,
};
/** Keeps a caption above TikTok's interface, which covers the bottom 18% of the canvas. */
const CAPTION_SAFE_BOTTOM = 0.18;
const UNAVAILABLE: CSSProperties = {
  alignItems: "center",
  justifyContent: "center",
  backgroundColor: "#18181b",
  fontSize: 24,
  color: "#a1a1aa",
};

/**
 * The only overlay presets the composition will draw. A document naming
 * anything else renders nothing, so a stored preset ID can never select
 * arbitrary markup.
 */
const OVERLAY_PRESETS: Record<string, (clip: OverlayClip, accent: TrustedStyle) => ReactNode> = {
  lower_third: (clip, accent) => (
    <div
      data-testid="overlay-lower_third"
      data-accent={accent.name}
      style={{
        position: "absolute",
        left: 64,
        right: 64,
        bottom: 128,
        borderRadius: 4,
        backgroundColor: "rgba(0, 0, 0, 0.7)",
        padding: "24px 32px",
        fontSize: 36,
        ...accent.style,
      }}
    >
      {clip.parameters?.text}
    </div>
  ),
  badge: (clip, accent) => (
    <div
      data-testid="overlay-badge"
      data-accent={accent.name}
      style={{
        position: "absolute",
        left: 64,
        top: 64,
        borderRadius: 9999,
        backgroundColor: "rgba(255, 255, 255, 0.9)",
        padding: "12px 24px",
        fontSize: 30,
        fontWeight: 600,
        ...accent.style,
      }}
    >
      {clip.parameters?.text}
    </div>
  ),
  progress_bar: (_clip, accent) => (
    <div
      data-testid="overlay-progress_bar"
      data-accent={accent.name}
      style={{
        position: "absolute",
        left: 0,
        right: 0,
        bottom: 0,
        height: 12,
        backgroundColor: "rgba(255, 255, 255, 0.8)",
      }}
    />
  ),
};

/**
 * Every style name the composition will honour. A document naming anything
 * else falls back, so a stored slot can never become arbitrary CSS or markup.
 */
const OVERLAY_ACCENTS: Record<string, CSSProperties> = {
  accent_primary: { color: "#fcd34d" },
  accent_secondary: { color: "#7dd3fc" },
  title: { color: "#ffffff" },
  source: { color: "#e4e4e7" },
};

const CAPTION_BASE: CSSProperties = {
  borderRadius: 4,
  backgroundColor: "rgba(0, 0, 0, 0.7)",
  padding: "12px 24px",
  textAlign: "center",
};

const CAPTION_STYLES: Record<string, CSSProperties> = {
  caption_default: { ...CAPTION_BASE, fontSize: 36 },
  source: { ...CAPTION_BASE, fontSize: 30, color: "#e4e4e7" },
  // Narration's word-timed captions (spec 2026-10-31).
  word_highlight: { ...CAPTION_BASE, fontSize: 40, fontWeight: 700 },
  // Style A's small subtitles on a solid box, and Style B's big centred words (spec 2026-11-09).
  boxed: { borderRadius: 4, backgroundColor: "#000000", padding: "6px 14px", textAlign: "center", fontSize: 30 },
  kinetic: {
    textAlign: "center",
    fontSize: 96,
    fontWeight: 800,
    textTransform: "uppercase",
    textShadow: "0 4px 12px rgba(0, 0, 0, 0.85)",
  },
};

/** The caption styles a document may name; Studio offers exactly these. */
export const CAPTION_STYLE_IDS = Object.keys(CAPTION_STYLES);

/** Identity crop and placement, used when a clip stores neither. */
const FULL_CROP = { left: 0, top: 0, width: 1, height: 1 };
const NO_POSITION = { x: 0, y: 0, scale: 1 };

function trustedStyle(
  slot: string | null | undefined,
  registry: Record<string, CSSProperties>,
  fallback: CSSProperties,
): TrustedStyle {
  const style = slot ? registry[slot] : undefined;
  return style ? { name: slot as string, style } : { name: "default", style: fallback };
}

export function AdvancedTimelineComposition({
  document,
  previewSources = {},
  onPreviewUnavailable,
}: Props) {
  useCompositionFonts();
  // Whether a clip is a still or a movie comes only from the document's own
  // validated asset reference, never from a preview URL or its suffix.
  const refs = new Map((document.asset_refs ?? []).map((ref) => [ref.asset_id, ref]));
  return (
    <AbsoluteFill style={CANVAS}>
      {/* Lanes are editor rows, so a hidden track still has one; the composition drops it. */}
      {visibleLanes(document)
        .filter(({ track }) => !track.hidden)
        .flatMap(({ track, clips }) =>
          clips
            .filter((clip) => !clip.hidden)
            .map((clip) => (
              <Sequence
                key={clip.clip_id}
                name={clip.clip_id}
                from={clip.from_frame}
                durationInFrames={clip.duration_in_frames}
              >
                {renderClip(
                  clip,
                  track.muted === true,
                  refs,
                  document.canvas,
                  previewSources,
                  onPreviewUnavailable,
                )}
              </Sequence>
            )),
        )}
    </AbsoluteFill>
  );
}

function renderClip(
  clip: TimelineClip,
  muted: boolean,
  refs: Map<string, AssetRef>,
  canvas: EditDocumentV2["canvas"],
  sources: PreviewSources,
  onPreviewUnavailable?: (assetId: string) => void,
): ReactNode {
  switch (clip.kind) {
    case "text":
      if (clip.style_slot === "card") {
        // Style B's narrator card: the heading alone, black on white (spec 2026-11-09, 3.6).
        return (
          <AbsoluteFill data-testid="text-card" style={TEXT_CARD}>
            <h1 style={TEXT_CARD_HEADING}>{clip.heading}</h1>
          </AbsoluteFill>
        );
      }
      if (HEADING_PLACES.has(clip.style_slot)) {
        const top = clip.style_slot === "title_top";
        return (
          <AbsoluteFill
            data-testid={`heading-${clip.style_slot}`}
            style={{
              ...PLACED_TEXT,
              justifyContent: top ? "flex-start" : "flex-end",
              ...(top
                ? { paddingTop: canvas.height * HEADING_TOP_SAFE }
                : { paddingBottom: canvas.height * HEADING_LOWER_SAFE }),
            }}
          >
            <div style={HEADING_SCRIM}>
              <h1 style={PLACED_HEADING}>{clip.heading}</h1>
              {clip.body && <p style={{ ...BODY, maxWidth: "100%", margin: 0 }}>{clip.body}</p>}
            </div>
          </AbsoluteFill>
        );
      }
      return (
        <AbsoluteFill style={TEXT_CLIP}>
          <h1 style={HEADING}>{clip.heading}</h1>
          {clip.body && <p style={BODY}>{clip.body}</p>}
        </AbsoluteFill>
      );
    case "overlay": {
      const accent = trustedStyle(clip.parameters?.accent_slot, OVERLAY_ACCENTS, {
        color: "#ffffff",
      });
      return <AbsoluteFill>{OVERLAY_PRESETS[clip.preset_id]?.(clip, accent)}</AbsoluteFill>;
    }
    case "caption": {
      const style = trustedStyle(clip.style_slot, CAPTION_STYLES, CAPTION_STYLES.caption_default!);
      // Kinetic words sit in the middle, a little above it; every other style stays in the low lane.
      const lane =
        style.name === "kinetic"
          ? { ...CAPTION_LANE, justifyContent: "center", paddingBottom: canvas.height * 0.1 }
          : { ...CAPTION_LANE, paddingBottom: canvas.height * CAPTION_SAFE_BOTTOM };
      return (
        <AbsoluteFill style={lane}>
          {/* Cue frames are relative to the caption clip, so they nest inside it. */}
          {clip.cues.map((cue, index) => (
            <Sequence
              key={`${clip.clip_id}_cue_${index}`}
              name={`${clip.clip_id}_cue_${index}`}
              from={cue.from_frame}
              durationInFrames={cue.duration_in_frames}
              // Its default wrapper is a row of its own: the lane's centring would never reach the
              // cue, and the cue's box would run the canvas's height from the top left.
              layout="none"
            >
              {style.name === "kinetic" && cue.words && cue.words.length > 0 ? (
                <KineticCue words={cue.words} style={style.style} />
              ) : style.name === "word_highlight" && cue.words && cue.words.length > 0 ? (
                <WordHighlightCue words={cue.words} style={style.style} />
              ) : (
                <p data-testid="caption-cue" data-caption-style={style.name} style={style.style}>
                  {cue.text}
                </p>
              )}
            </Sequence>
          ))}
        </AbsoluteFill>
      );
    }
    case "video": {
      const draw = (motion: MotionState) =>
        videoClip(clip, muted, refs, canvas, sources, motion, onPreviewUnavailable);
      // Only a moving clip reads the frame, so a still clip draws exactly as before Story mode.
      const moving = (clip.moves?.length ?? 0) > 0 || (clip.motion && clip.motion !== "none");
      const drawn = moving ? <MovingClip clip={clip} draw={draw} /> : draw(STILL);
      const asset = refs.get(clip.asset_id);
      // Narration's retiming may run a clip past its source: hold that last frame (2026-10-31).
      // At a speed (Tier 3a) the source runs out after fewer or more timeline frames.
      const remaining =
        clip.hold_after_source && asset?.kind === "video" && asset.duration_in_frames
          ? Math.floor(((asset.duration_in_frames - clip.source_from_frame) * 100) / speedPercent(clip))
          : null;
      const held =
        remaining !== null && remaining > 0 ? <HeldClip lastFrame={remaining - 1}>{drawn}</HeldClip> : drawn;
      // Outside the hold, so a held last frame still fades out on time; no fade draws as before.
      return hasFades(clip) ? <FadingClip clip={clip}>{held}</FadingClip> : held;
    }
    case "audio": {
      const source = resolve(clip.asset_id, sources, onPreviewUnavailable);
      // Audio has no picture: a missing source is reported but never covers the frame.
      if (!source) return null;
      return (
        <Audio
          src={source}
          startFrom={clip.source_from_frame}
          {...(speedPercent(clip) !== 100 ? { playbackRate: clip.speed } : {})}
          volume={(frame) =>
            // Ducking scales the clip's own volume, so an operator's level survives it.
            muted ? 0 : clip.volume * volumeAt(frame, clip.volume_keyframes ?? [], 1) * fadeMultiplier(frame, clip)
          }
        />
      );
    }
    default:
      return null;
  }
}

/** Style B's words, one group at a time: each group stays until the next one starts. */
function KineticCue({
  words,
  style,
}: {
  words: NonNullable<Extract<TimelineClip, { kind: "caption" }>["cues"][number]["words"]>;
  style: CSSProperties;
}) {
  const frame = useCurrentFrame();
  const groups = kineticGroups(words);
  const shown = groups.filter((group) => group.from <= frame).at(-1) ?? groups[0]!;
  return (
    <p data-testid="caption-cue" data-caption-style="kinetic" style={style}>
      {shown.text}
    </p>
  );
}

/** The spoken word in amber, the rest of the page in white (narration captions, 2026-10-31). */
function WordHighlightCue({
  words,
  style,
}: {
  words: NonNullable<Extract<TimelineClip, { kind: "caption" }>["cues"][number]["words"]>;
  style: CSSProperties;
}) {
  const frame = useCurrentFrame();
  return (
    <p data-testid="caption-cue" data-caption-style="word_highlight" style={style}>
      {words.map((word, index) => {
        const active = frame >= word.from_frame && frame < word.from_frame + word.duration_in_frames;
        return (
          <Fragment key={index}>
            {index > 0 ? " " : null}
            <span
              data-testid="caption-word"
              data-active={String(active)}
              style={{ color: active ? "#d49a79" : "#ffffff" }}
            >
              {word.text}
            </span>
          </Fragment>
        );
      })}
    </p>
  );
}

/**
 * Past the asset's last frame the clip shows that frame, paused. Freeze stays mounted and
 * switches on through `active` (Remotion v4.0.127+), so the decoder is never remounted.
 */
function HeldClip({ lastFrame, children }: { lastFrame: number; children: ReactNode }) {
  return (
    <Freeze frame={lastFrame} active={(frame) => frame > lastFrame}>
      {children}
    </Freeze>
  );
}

/**
 * A keyframed volume at one clip-relative frame: the first value before the first
 * keyframe, linear between keyframes, the last value after; `fallback` without any.
 */
export function volumeAt(
  frame: number,
  keyframes: ReadonlyArray<{ frame: number; volume: number }>,
  fallback: number,
): number {
  if (keyframes.length === 0) return fallback;
  if (frame <= keyframes[0]!.frame) return keyframes[0]!.volume;
  for (let index = 1; index < keyframes.length; index += 1) {
    const next = keyframes[index]!;
    if (frame <= next.frame) {
      const previous = keyframes[index - 1]!;
      const ratio = (frame - previous.frame) / (next.frame - previous.frame);
      return previous.volume + (next.volume - previous.volume) * ratio;
    }
  }
  return keyframes[keyframes.length - 1]!.volume;
}

function MovingClip({ clip, draw }: { clip: VideoClip; draw: (motion: MotionState) => ReactNode }) {
  // Inside the clip's sequence, so the motion runs across the clip's own duration.
  const frame = useCurrentFrame();
  if (clip.moves?.length) {
    // Keyframed moves replace the preset; they stack on the stored placement (spec 2026-11-09).
    const value = moveAt(clip.moves, frame);
    return <>{draw({ scale: value.scale, translateX: value.x, translateY: value.y })}</>;
  }
  return <>{draw(motionTransform(clip.motion ?? "none", frame, clip.duration_in_frames))}</>;
}

function videoClip(
  clip: VideoClip,
  muted: boolean,
  refs: Map<string, AssetRef>,
  canvas: EditDocumentV2["canvas"],
  sources: PreviewSources,
  motion: MotionState,
  onPreviewUnavailable?: (assetId: string) => void,
): ReactNode {
  const kind = refs.get(clip.asset_id)?.kind;
  if (kind !== "video" && kind !== "image") {
    return <PreviewUnavailable label="Video preview unavailable" />;
  }
  const source = resolve(clip.asset_id, sources, onPreviewUnavailable);
  if (!source) return <PreviewUnavailable label="Video preview unavailable" />;
  const crop = clip.crop ?? FULL_CROP;
  const position = clip.position ?? NO_POSITION;
  // A movie's blur-fill is drawn from the clip's own decoded frames: a second decoder of the same
  // source made a 60 s render five times slower (plan 2026-11-09, Task 8).
  const blurTarget: { canvas: HTMLCanvasElement | null } = { canvas: null };
  const onVideoFrame =
    clip.background === "blur_fill" ? (image: CanvasImageSource) => drawCover(blurTarget.canvas, image) : undefined;
  const media: CSSProperties = {
    position: "absolute",
    width: percent(1 / span(crop.width)),
    height: percent(1 / span(crop.height)),
    left: percent(-crop.left / span(crop.width)),
    top: percent(-crop.top / span(crop.height)),
  };
  const frame = (
    // The frame clips the crop and carries the placement; the media itself
    // is enlarged and offset so the kept region fills that frame.
    <AbsoluteFill
      data-testid="clip-frame"
      style={{
        overflow: "hidden",
        // Offsets are canvas fractions, not pixels, so they project as percentages.
        transform: `translate(${percent(position.x + motion.translateX)}, ${percent(position.y + motion.translateY)}) scale(${position.scale * motion.scale})`,
      }}
    >
      {/* A still has no source timeline, so only a movie carries a trim. */}
      {kind === "image" ? (
        <Img src={source} style={{ ...media, objectFit: clip.fit }} />
      ) : (
        // One WebCodecs decoder for the preview and the render: the HTML5 element mis-seeks
        // under load (parity frame 90, 2026-10-21). A source headless Chrome cannot decode
        // (HEVC) falls back to the FFmpeg frame extractor, which renders a few levels off
        // the preview's colours rather than cancelling the whole render.
        <Video
          src={source}
          trimBefore={clip.source_from_frame}
          muted={muted}
          // A clip at a speed (Tier 3a) keeps its pitch, so speech stays natural; normal speed passes nothing.
          {...(speedPercent(clip) !== 100 ? { playbackRate: clip.speed, preservePitch: true } : {})}
          // Only ducking or a fade passes a volume, so every other render stays as it was.
          {...(clip.volume_keyframes?.length || hasFades(clip)
            ? {
                volume: (frame: number) =>
                  volumeAt(frame, clip.volume_keyframes ?? [], 1) * fadeMultiplier(frame, clip),
              }
            : {})}
          objectFit={clip.fit}
          // A paused player draws no new frame for a new callback, so a change of background remounts it.
          key={clip.background ?? "none"}
          {...(onVideoFrame ? { onVideoFrame } : {})}
          style={media}
        />
      )}
      {kind === "video" && clip.blur_enabled
        ? blurBoxes(clip, refs.get(clip.asset_id), canvas).map((box, index) => {
            const region = (
              <div
                key={`${clip.clip_id}_blur_${index}`}
                data-testid="blur-region"
                style={{
                  position: "absolute",
                  left: box.left,
                  top: box.top,
                  width: box.width,
                  height: box.height,
                  backdropFilter: `blur(${box.sigma}px)`,
                }}
              />
            );
            // A windowed region shows only between its source frames, clip-relative here.
            return box.from === null || box.to === null ? (
              region
            ) : (
              <Sequence
                key={`${clip.clip_id}_blur_${index}`}
                name={`${clip.clip_id}_blur_${index}`}
                from={box.from}
                durationInFrames={Math.max(1, box.to - box.from)}
              >
                {region}
              </Sequence>
            );
          })
        : null}
    </AbsoluteFill>
  );
  const content = contentBox(clip.fit, refs.get(clip.asset_id), canvas);
  // Behind the clip: a blurred copy of the same media covering the canvas, still while the clip moves.
  const blurFill =
    clip.background === "blur_fill" ? (
      <AbsoluteFill data-testid="clip-blur-fill" style={{ overflow: "hidden" }}>
        <div data-testid="clip-blur-fill-layer" style={BLUR_FILL_LAYER}>
          {kind === "image" ? (
            <Img src={source} style={{ ...BLUR_FILL_MEDIA, filter: BLUR_FILL_RADIUS }} />
          ) : (
            <canvas
              ref={(element) => {
                blurTarget.canvas = element;
              }}
              width={Math.max(1, Math.round(canvas.width / 8))}
              height={Math.max(1, Math.round(canvas.height / 8))}
              style={BLUR_FILL_MEDIA}
            />
          )}
        </div>
      </AbsoluteFill>
    ) : null;
  // Dim veils the clip's own visible picture; with blur-fill the blurred copy is the clip's too.
  const veil =
    clip.background === "blur_fill"
      ? FULL_VEIL
      : markBox(WHOLE_PICTURE, { fit: clip.fit, crop, asset: refs.get(clip.asset_id), canvas }, clip.position, motion);
  const dim =
    (clip.dim ?? 0) > 0 && veil ? (
      <AbsoluteFill
        data-testid="clip-dim"
        style={{
          backgroundColor: "#000000",
          opacity: clip.dim,
          ...(veil === FULL_VEIL
            ? {}
            : { left: percent(veil.left), top: percent(veil.top), width: percent(veil.width), height: percent(veil.height) }),
        }}
      />
    ) : null;
  const marks = clip.emphasis?.marks?.length ? (
    <ClipMarks clip={clip} view={{ fit: clip.fit, crop, asset: refs.get(clip.asset_id), canvas }} motion={motion} />
  ) : null;
  const emphasis = clip.emphasis;
  const layers = (
    <>
      {blurFill}
      {frame}
      {dim}
      {marks}
    </>
  );
  if (!emphasis?.highlight && !emphasis?.arrow) return blurFill || dim || marks ? layers : frame;
  const box = emphasisBox(clip.position, content, motion);
  return (
    <>
      {layers}
      {emphasis.highlight ? (
        <div
          data-testid="clip-highlight"
          style={{
            position: "absolute",
            left: percent(box.left),
            top: percent(box.top),
            width: percent(box.width),
            height: percent(box.height),
            outline: `${HIGHLIGHT.width}px solid ${HIGHLIGHT.color}`,
          }}
        />
      ) : null}
      {emphasis.arrow ? (
        // A fixed arrow pointing down at the top edge, centred on the media; a card with no
        // room above it gets the arrow below, pointing up, so it never leaves the canvas.
        <svg
          data-testid="clip-arrow"
          data-placement={box.top * canvas.height >= ARROW_SIZE ? "above" : "below"}
          width={ARROW_SIZE}
          height={ARROW_SIZE}
          viewBox="0 0 120 120"
          fill={HIGHLIGHT.color}
          style={{
            position: "absolute",
            left: percent(box.left + box.width / 2),
            ...(box.top * canvas.height >= ARROW_SIZE
              ? { top: percent(box.top), transform: "translate(-50%, -100%)" }
              : { top: percent(box.top + box.height), transform: "translate(-50%, 0) rotate(180deg)" }),
          }}
        >
          <path d="M48 0h24v70h28L60 120 20 70h28z" />
        </svg>
      ) : null}
    </>
  );
}

const MARK_COLORS: Record<string, string> = { accent: "#ffd23f", alert: "#ff3b30" };
const MARK_DRAW_FRAMES = 8;
const MARK_POP_FRAMES = 5;
const ARROW_TURN: Record<string, string> = {
  top: "translate(-50%, -100%)",
  bottom: "translate(-50%, 0) rotate(180deg)",
  left: "translate(-100%, -50%) rotate(-90deg)",
  right: "translate(0, -50%) rotate(90deg)",
};

/** Boxes that draw themselves in and arrows that pop in, stuck to the media (spec 2026-11-09, 3.4). */
const WHOLE_PICTURE: MarkShape = { kind: "box", x: 0, y: 0, w: 1, h: 1, from_frame: 0, to_frame: 1 };
const FULL_VEIL = { left: 0, top: 0, width: 1, height: 1 };

function ClipMarks({ clip, view, motion }: { clip: VideoClip; view: MarkView; motion: MotionState }) {
  const frame = useCurrentFrame();
  const source = sourceFrame(clip, frame);
  return (
    <>
      {(clip.emphasis?.marks ?? []).map((mark, index) => {
        const shape = mark as MarkShape & { side?: string; color?: string };
        if (!markWindowOpen(shape, clip, frame)) return null;
        const box = markBox(shape, view, clip.position, motion);
        if (!box) return null;
        const color = MARK_COLORS[shape.color ?? "accent"] ?? MARK_COLORS.accent!;
        const since = source - shape.from_frame;
        if (shape.kind === "box") {
          const drawn = Math.min(1, since / MARK_DRAW_FRAMES);
          return (
            <svg
              key={index}
              data-testid="clip-mark"
              data-mark-kind="box"
              style={{ position: "absolute", left: percent(box.left), top: percent(box.top), width: percent(box.width), height: percent(box.height), overflow: "visible" }}
            >
              <rect
                x="0"
                y="0"
                width="100%"
                height="100%"
                fill="none"
                stroke={color}
                strokeWidth={6}
                pathLength={100}
                strokeDasharray={100}
                strokeDashoffset={100 * (1 - drawn)}
              />
            </svg>
          );
        }
        const pop = Math.min(1, (since + 1) / MARK_POP_FRAMES);
        return (
          <svg
            key={index}
            data-testid="clip-mark"
            data-mark-kind="arrow"
            width={ARROW_SIZE}
            height={ARROW_SIZE}
            viewBox="0 0 120 120"
            fill={color}
            style={{
              position: "absolute",
              left: percent(box.left),
              top: percent(box.top),
              transform: `${ARROW_TURN[shape.side ?? "top"] ?? ARROW_TURN.top} scale(${pop})`,
              transformOrigin: "center",
            }}
          >
            <path d="M48 0h24v70h28L60 120 20 70h28z" />
          </svg>
        );
      })}
    </>
  );
}

/** A CSS percentage with enough precision to survive a fractional crop. */
function percent(ratio: number): string {
  return `${Number((ratio * 100).toFixed(4))}%`;
}

/** A crop edge never divides by zero, however the document was written. */
function span(size: number): number {
  return size > 0 ? size : 1;
}

/**
 * How much of the stored volume a frame keeps, from 0 to 1.
 *
 * `frame` is relative to the clip, which is exactly how the document stores
 * its fades, so no canvas offset enters the calculation.
 */
function fadeMultiplier(frame: number, clip: Faded): number {
  const fadeIn = clip.fade_in_frames ?? 0;
  const fadeOut = clip.fade_out_frames ?? 0;
  const rise = fadeIn > 0 ? frame / fadeIn : 1;
  const fall = fadeOut > 0 ? (clip.duration_in_frames - frame) / fadeOut : 1;
  return Math.min(1, Math.max(0, Math.min(rise, fall)));
}

type Faded = { duration_in_frames: number; fade_in_frames?: number; fade_out_frames?: number };

/** A stored draft carries video fades only when they are used (spec 2026-11-08 §6). */
const hasFades = (clip: Faded) => (clip.fade_in_frames ?? 0) > 0 || (clip.fade_out_frames ?? 0) > 0;

/** The picture's fade, inside the clip's sequence so the frame is clip-relative. */
function FadingClip({ clip, children }: { clip: Faded; children: ReactNode }) {
  const frame = useCurrentFrame();
  return (
    <AbsoluteFill data-testid="clip-fade" style={{ opacity: fadeMultiplier(frame, clip) }}>
      {children}
    </AbsoluteFill>
  );
}

/** Pixels the blur reaches past the canvas edge: 3 sigma of blur(6px). */
const BLUR_FILL_BLEED = 18;

/**
 * Draws a decoded frame over the whole target canvas, cropped to cover it plus the blur's reach, so
 * the blur's transparent edge falls outside the canvas; the last frame is cleared first.
 */
function drawCover(target: HTMLCanvasElement | null, image: CanvasImageSource): void {
  const context = target?.getContext("2d");
  if (!target || !context) return;
  const size = image as { displayWidth?: number; displayHeight?: number; width?: unknown; height?: unknown };
  const width = Number(size.displayWidth ?? size.width);
  const height = Number(size.displayHeight ?? size.height);
  if (!(width > 0 && height > 0)) return;
  const scale = Math.max((target.width + 2 * BLUR_FILL_BLEED) / width, (target.height + 2 * BLUR_FILL_BLEED) / height);
  context.clearRect(0, 0, target.width, target.height);
  context.filter = BLUR_FILL_RADIUS;
  context.drawImage(image, (target.width - width * scale) / 2, (target.height - height * scale) / 2, width * scale, height * scale);
}

function resolve(
  assetId: string,
  sources: PreviewSources,
  onPreviewUnavailable?: (assetId: string) => void,
): string | undefined {
  const source = safePreviewSource(sources[assetId]);
  if (!source) onPreviewUnavailable?.(assetId);
  return source;
}

function PreviewUnavailable({ label }: { label: string }) {
  return (
    <AbsoluteFill data-testid="preview-unavailable" style={UNAVAILABLE}>
      {label}
    </AbsoluteFill>
  );
}
