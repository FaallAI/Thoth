/**
 * A clip's speed in whole percent (Tier 3a): the server, the editor and the renderer count source
 * frames in this one unit, so they agree to the frame. A clip without speed plays at 100.
 */
export function speedPercent(clip: object): number {
  const speed = "speed" in clip && typeof clip.speed === "number" ? clip.speed : 1;
  return Math.round(speed * 100);
}
