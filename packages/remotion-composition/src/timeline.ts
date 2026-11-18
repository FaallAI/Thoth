/**
 * The document shape and the one lane projection the composition draws.
 *
 * The document type comes from the generated control-plane contract, so the
 * renderer and the browser agree with the server by construction instead of by
 * a second handwritten schema.
 */

import type { components } from "../../../dashboard/src/api/generated/control-plane";

export type EditDocumentV2 = components["schemas"]["EditDocumentV2"];
export type TimelineTrack = EditDocumentV2["tracks"][number];
export type TimelineClip = NonNullable<EditDocumentV2["clips"]>[number];
export type AssetKind = NonNullable<EditDocumentV2["asset_refs"]>[number]["kind"];
/**
 * One track's clips. `clips` is in time order, for the editor's rules and gestures; `layered`
 * is the draw order, by layer then start, so a higher layer is drawn on top (spec 2026-11-17).
 */
export type TimelineLane = {
  track: TimelineTrack;
  clips: TimelineClip[];
  layered: TimelineClip[];
  layers: number;
  layerOf: Map<string, number>;
};

/**
 * Whether drawing this document actually produces sound.
 *
 * The rules are the composition's own: a hidden track or clip is not drawn, a
 * muted track plays every source at zero, an audio clip is silent at zero
 * volume, and a video clip only sounds when its asset carries an audio stream.
 * Both the preview and the renderer ask here so neither can drift from what
 * `AdvancedTimelineComposition` renders.
 */
export function hasAudibleContent(document: EditDocumentV2): boolean {
  const references = new Map((document.asset_refs ?? []).map((ref) => [ref.asset_id, ref]));
  return visibleLanes(document).some(({ track, clips }) => {
    if (track.hidden || track.muted === true) {
      return false;
    }
    return clips.some((clip) => {
      if (clip.hidden) {
        return false;
      }
      if (clip.kind === "audio") {
        return clip.volume > 0;
      }
      if (clip.kind !== "video") {
        return false;
      }
      const reference = references.get(clip.asset_id);
      return reference?.kind === "video" && reference.has_audio === true;
    });
  });
}

/**
 * Clips that play at once stack as layers, as in an editor timeline (spec 2026-11-17, goal 5):
 * taken by start frame then document order, each goes on the lowest layer whose last clip has
 * ended by its start. A hidden clip is not drawn, so it takes no layer.
 */
export function clipLayers(clips: TimelineClip[]): Map<string, number> {
  const order = clips
    .map((clip, index) => ({ clip, index }))
    .filter(({ clip }) => !clip.hidden)
    .sort((a, b) => a.clip.from_frame - b.clip.from_frame || a.index - b.index);
  const ends: number[] = [];
  const layers = new Map<string, number>();
  for (const { clip } of order) {
    let layer = ends.findIndex((end) => end <= clip.from_frame);
    if (layer < 0) layer = ends.push(0) - 1;
    ends[layer] = clip.from_frame + clip.duration_in_frames;
    layers.set(clip.clip_id, layer);
  }
  return layers;
}

/** Tracks in draw order, each carrying its own clips in time order and in layer order. */
export function visibleLanes(document: EditDocumentV2): TimelineLane[] {
  const clips = document.clips ?? [];
  return [...document.tracks]
    .sort((left, right) => left.order - right.order)
    .map((track) => {
      const own = clips
        .filter((clip) => clip.track_id === track.track_id)
        .sort((left, right) => left.from_frame - right.from_frame);
      const layerOf = clipLayers(own);
      const layered = [...own].sort(
        (left, right) =>
          (layerOf.get(left.clip_id) ?? 0) - (layerOf.get(right.clip_id) ?? 0) ||
          left.from_frame - right.from_frame,
      );
      const layers = Math.max(1, ...[...layerOf.values()].map((layer) => layer + 1));
      return { track, clips: own, layered, layers, layerOf };
    });
}
