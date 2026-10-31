// The project's narration preset and the shared SFX library (spec 2026-10-31, decisions 2 and 8).
import { useEffect, useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type NarrationPreset,
  type SfxSummary,
} from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { MessageKey } from "@/lib/i18n";

const TEXT_FIELDS = ["language", "voice_id", "voice_model"] as const;
const NUMBER_FIELDS = [
  ["target_seconds", 1],
  ["words_per_second", 0.1],
  ["duck_volume", 0.01],
  ["leak_volume", 0.01],
  ["lead_in_seconds", 0.1],
  ["max_sfx_cues", 1],
] as const;

export function NarrationPresetForm({
  client,
  projectId,
}: {
  client: Pick<ControlPlaneClient, "getNarrationPreset" | "saveNarrationPreset">;
  projectId: string;
}) {
  const { t } = useLocale();
  const [preset, setPreset] = useState<NarrationPreset | null>(null);
  const [revision, setRevision] = useState(0);
  const [message, setMessage] = useState<MessageKey | null>(null);

  useEffect(() => {
    void client.getNarrationPreset(projectId).then(
      (stored) => {
        setPreset(stored.preset);
        setRevision(stored.revision);
      },
      () => {},
    );
  }, [client, projectId]);

  if (!preset) return null;
  const save = async () => {
    try {
      const stored = await client.saveNarrationPreset(projectId, preset, revision);
      setRevision(stored.revision);
      setMessage("studio.narration.presetSaved");
    } catch (error) {
      setMessage(
        error instanceof StudioImportRequestError && error.code === "narration_preset_conflict"
          ? "studio.narration.presetConflict"
          : "common.unavailable",
      );
    }
  };
  const field = (name: string) => t(`studio.narration.field.${name}` as MessageKey);
  return (
    <section aria-label={t("studio.narration.preset")} className="flex flex-col gap-3 rounded-[10px] bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">{t("studio.narration.preset")}</h2>
      <div className="grid gap-3 sm:grid-cols-2">
        {TEXT_FIELDS.map((name) => (
          <label key={name} className="flex flex-col gap-1 text-xs text-muted-ink">
            {field(name)}
            <input
              value={preset[name] ?? ""}
              onChange={(event) => setPreset({ ...preset, [name]: event.target.value })}
              className="rounded-md bg-well px-2 py-1.5 text-sm text-ink"
            />
          </label>
        ))}
        {NUMBER_FIELDS.map(([name, step]) => (
          <label key={name} className="flex flex-col gap-1 text-xs text-muted-ink">
            {field(name)}
            <input
              type="number"
              step={step}
              value={preset[name] ?? 0}
              onChange={(event) => setPreset({ ...preset, [name]: Number(event.target.value) })}
              className="rounded-md bg-well px-2 py-1.5 text-sm text-ink"
            />
          </label>
        ))}
      </div>
      <div className="flex items-center gap-3">
        <button type="button" onClick={save} className="rounded-md bg-copper px-3 py-1.5 text-[13px] text-bg">
          {t("studio.narration.presetSave")}
        </button>
        {message ? (
          <span role="status" className="text-xs text-muted-ink">
            {t(message)}
          </span>
        ) : null}
      </div>
    </section>
  );
}

export function SfxLibrary({ client }: { client: Pick<ControlPlaneClient, "listSfx"> }) {
  const { t } = useLocale();
  const [entries, setEntries] = useState<SfxSummary[] | null>(null);
  // The function, not the wrapper object, is stable across renders.
  const { listSfx } = client;
  useEffect(() => {
    void listSfx().then(setEntries, () => setEntries([]));
  }, [listSfx]);
  if (!entries) return null;
  return (
    <section aria-label={t("studio.sfx.title")} className="flex flex-col gap-2 rounded-[10px] bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">{t("studio.sfx.title")}</h2>
      {entries.length === 0 ? (
        <p className="text-xs text-muted-ink">{t("studio.sfx.empty")}</p>
      ) : (
        <ul className="flex flex-col gap-1 text-sm">
          {entries.map((entry) => (
            <li key={entry.sfx_id} className="flex flex-wrap items-baseline gap-2">
              <span className="text-ink">{entry.sfx_id}</span>
              <span className="text-xs text-muted-ink">{entry.duration_seconds.toFixed(1)} s</span>
              {typeof entry.labels.category === "string" ? (
                <span className="text-xs text-muted-ink">{entry.labels.category}</span>
              ) : null}
              {typeof entry.labels.licence === "string" ? (
                <span className="text-xs text-faint">{t("studio.sfx.licence", { licence: entry.labels.licence })}</span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
