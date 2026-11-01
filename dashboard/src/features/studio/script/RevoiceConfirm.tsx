// Every re-voice is a paid TTS call, so its characters and price show before any voice is made
// (operator, 2026-11-01). Shared by the narration status and the script panel.
import type { BeatName, NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

/** The beats' characters, and their share of the script's estimated price (null when unpriced). */
export function revoiceCost(state: NarrationState, beats: readonly BeatName[]): { characters: number; usd: number | null } {
  const characters = (state.script?.beats ?? []).filter((beat) => beats.includes(beat.beat)).reduce((sum, beat) => sum + beat.text.length, 0);
  const estimate = state.estimate;
  const usd = estimate?.usd != null && estimate.characters > 0 ? (estimate.usd * characters) / estimate.characters : null;
  return { characters, usd };
}

export function RevoiceConfirm({
  state,
  beats,
  busy,
  onConfirm,
  onCancel,
}: {
  state: NarrationState;
  beats: readonly BeatName[];
  busy: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useLocale();
  const { characters, usd } = revoiceCost(state, beats);
  return (
    <div className="flex flex-col gap-2 rounded-md bg-surface p-2 text-xs text-muted-ink">
      <p>
        {t("studio.narration.revoiceCost", {
          count: beats.length,
          characters,
          price: usd == null ? t("studio.narration.unpriced") : t("studio.narration.price", { usd: usd.toFixed(2) }),
        })}
      </p>
      <div className="flex gap-2">
        <button type="button" className="rounded-md bg-copper px-3 py-1 text-[13px] text-bg disabled:opacity-40" disabled={busy} onClick={onConfirm}>
          {t("studio.narration.revoiceYes", { count: beats.length })}
        </button>
        <button type="button" className="rounded-md border border-hairline px-3 py-1 text-[13px] text-ink" onClick={onCancel}>
          {t("studio.narration.notNow")}
        </button>
      </div>
    </div>
  );
}
