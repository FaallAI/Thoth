/**
 * The platform's unsafe areas over the preview (spec 2026-10-27 §9): TikTok's interface
 * covers the top 10% and the bottom 18%. Drawn over the player only, never into the video.
 */
export const SAFE_ZONE = { top: 0.1, bottom: 0.18 } as const;

export function SafeZoneOverlay() {
  const band = "pointer-events-none absolute inset-x-0 border-dashed border-copper/70 bg-copper/15";
  return (
    <div aria-hidden="true" className="pointer-events-none absolute inset-0">
      <div data-testid="safe-zone-top" className={`${band} top-0 border-b`} style={{ height: `${SAFE_ZONE.top * 100}%` }} />
      <div data-testid="safe-zone-bottom" className={`${band} bottom-0 border-t`} style={{ height: `${SAFE_ZONE.bottom * 100}%` }} />
    </div>
  );
}
