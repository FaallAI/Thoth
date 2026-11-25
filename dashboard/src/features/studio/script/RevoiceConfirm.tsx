// Every re-voice is a paid TTS call, so its characters and price show before any voice is made
// (operator, 2026-11-01). Shared by the narration status and the script panel.
import type { BeatName, NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

// Audio tags such as [curious] are sent to, and billed by, Eleven v4 only; an older model is sent
// the text without them, the way the server's estimate counted it (spec 2026-11-24).
const AUDIO_TAGS = /\[[A-Za-z][A-Za-z ]{0,39}\]/g;

function billedText(text: string, model: string | null | undefined): string {
  if (model?.startsWith("eleven_v4")) return text;
  return text.replace(/\s*\[[A-Za-z][A-Za-z ]{0,39}\](?=[.,!?;:])/g, "").replace(AUDIO_TAGS, " ").split(/\s+/).filter(Boolean).join(" ");
}

/** The beats' characters, and their share of the script's estimated price (null when unpriced). */
export function revoiceCost(state: NarrationState, beats: readonly BeatName[]): { characters: number; usd: number | null } {
  const estimate = state.estimate;
  const characters = (state.script?.beats ?? [])
    .filter((beat) => beats.includes(beat.beat))
    .reduce((sum, beat) => sum + billedText(beat.text, estimate?.voice_model).length, 0);
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
  const { t, plural } = useLocale();
  const { characters, usd } = revoiceCost(state, beats);
  // A styled beat with hand edits only stretches: said before the voice is paid for (2026-11-10).
  const kept = beats.filter((beat) => (state.edited_beats ?? []).includes(beat));
  return (
    <div className="flex flex-col gap-2 rounded-md bg-surface p-2 text-xs text-muted-ink">
      {kept.length ? (
        <p>
          {plural("studio.narration.revoiceKept", kept.length, {
            beats: kept.map((beat) => t(`studio.story.beat.${beat}` as never)).join(", "),
          })}
        </p>
      ) : null}
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
