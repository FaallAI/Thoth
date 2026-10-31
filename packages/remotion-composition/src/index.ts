/**
 * The one trusted composition, shared by the Studio preview and the renderer.
 *
 * Both surfaces import the same component under the same ID, so what a creator
 * approves in the browser is what the server renders.
 */

export {
  AdvancedTimelineComposition,
  CAPTION_STYLE_IDS,
  type PreviewSources,
  volumeAt,
} from "./AdvancedTimelineComposition";
export { safePreviewSource } from "./media";
// The media box the composition draws, so Story places cards by what is actually visible.
export { contentBox, emphasisBox } from "./story_effects";
// One projection for both surfaces: Studio's Player and the parity harness are
// only comparable while they take their props and geometry from here.
export { playerConfig, timelineComposition, type PlayerProjection } from "./preview-projection";
export { COMPOSITION_FONT_FAMILY, loadCompositionFonts, useCompositionFonts } from "./fonts";
export {
  hasAudibleContent,
  visibleLanes,
  type AssetKind,
  type EditDocumentV2,
  type TimelineClip,
  type TimelineLane,
  type TimelineTrack,
} from "./timeline";

/** The only composition ID the renderer will accept. */
export const COMPOSITION_ID = "advanced-timeline-v1";
