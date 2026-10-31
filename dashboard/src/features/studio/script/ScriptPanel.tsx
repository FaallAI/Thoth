// Script mode (DESIGN §13.1, spec 2026-10-31): the narration's steps, the read-only approval
// with its TTS estimate, then the editable script with per-beat re-voice.
import { useState } from "react";

import type { BeatName, ControlPlaneClient, NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { MessageKey } from "@/lib/i18n";

type Client = Pick<ControlPlaneClient, "decideNarration" | "editNarrationBeat" | "revoiceNarrationBeat">;
type Props = {
  client: Client;
  projectId: string;
  documentId: string;
  state: NarrationState;
  onChange: (state: NarrationState) => void;
};

const STEPS = ["transcribing", "scripting", "awaiting_approval", "voicing", "writing"] as const;

/** The beat's text with every word the evidence lacks underlined. */
function Marked({ text, unsupported }: { text: string; unsupported: string[] }) {
  const { t } = useLocale();
  const missing = new Set(unsupported);
  return (
    <>
      {text.split(/(\s+)/).map((part, index) => {
        const bare = part.replace(/^[("'“‘]+|[)"'”’.,!?;:]+$/g, "");
        return bare && missing.has(bare) ? (
          <span key={index}>
            {part.slice(0, part.indexOf(bare))}
            <mark title={t("studio.narration.unsupported")} className="bg-transparent text-danger underline decoration-wavy">
              {bare}
            </mark>
            {part.slice(part.indexOf(bare) + bare.length)}
          </span>
        ) : (
          <span key={index}>{part}</span>
        );
      })}
    </>
  );
}

export function ScriptPanel({ client, projectId, documentId, state, onChange }: Props) {
  const { t } = useLocale();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<Record<string, string>>({});
  const beatLabel = (beat: BeatName) => t(`studio.story.beat.${beat}` as MessageKey);
  const script = state.script;

  const act = async (work: () => Promise<NarrationState | void>) => {
    setBusy(true);
    try {
      const next = await work();
      if (next) onChange(next);
    } finally {
      setBusy(false);
    }
  };

  if (state.status === "failed" || state.status === "cancelled") {
    return (
      <p role="status" className="text-sm text-muted-ink">
        {state.status === "failed"
          ? t("studio.narration.failed", { code: state.failure_code ?? "narration_failed" })
          : t("studio.narration.cancelled")}
      </p>
    );
  }

  if (state.status !== "awaiting_approval" && state.status !== "completed") {
    return (
      <ol aria-label={t("studio.narration.script")} className="flex flex-col gap-1 text-sm">
        {STEPS.map((step) => (
          <li key={step} aria-current={step === state.status ? "step" : undefined} className="text-muted-ink aria-[current=step]:font-semibold aria-[current=step]:text-ink">
            {t(`studio.narration.step.${step}` as MessageKey)}
          </li>
        ))}
      </ol>
    );
  }

  if (state.status === "awaiting_approval" && script) {
    const estimate = state.estimate;
    return (
      <section aria-label={t("studio.narration.step.awaiting_approval")} className="flex flex-col gap-3 text-sm">
        <h2 className="font-semibold text-ink">{t("studio.narration.step.awaiting_approval")}</h2>
        {script.beats.map((beat) => (
          <article key={beat.beat} className="rounded-md bg-surface p-3">
            <h3 className="text-xs uppercase text-muted-ink">{beatLabel(beat.beat)}</h3>
            <p className="text-ink">
              <Marked text={beat.text} unsupported={state.unsupported?.[beat.beat] ?? []} />
            </p>
            {(script.sfx_cues ?? [])
              .filter((cue) => cue.beat === beat.beat)
              .map((cue, index) => (
                <p key={index} className="text-xs text-muted-ink">
                  {t("studio.narration.sfx")}: {cue.sfx_id} · {cue.moment}
                </p>
              ))}
          </article>
        ))}
        {estimate ? (
          <p className="text-xs text-muted-ink">
            <span>{t("studio.narration.estimate", { characters: estimate.characters, provider: estimate.provider, voice: estimate.voice_id })}</span>{" "}
            <span>{estimate.usd == null ? t("studio.narration.unpriced") : t("studio.narration.price", { usd: estimate.usd.toFixed(4) })}</span>
          </p>
        ) : null}
        <label className="flex flex-col gap-1 text-xs text-muted-ink">
          {t("studio.narration.note")}
          <textarea value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} className="rounded-md bg-well p-2 text-sm text-ink" />
        </label>
        <div className="flex gap-2">
          <button type="button" disabled={busy} className="rounded-md bg-copper px-3 py-1.5 text-bg disabled:opacity-40"
            onClick={() => act(() => client.decideNarration(projectId, documentId, { decision: "approve", note: null }))}>
            {t("studio.narration.approve")}
          </button>
          <button type="button" disabled={busy} className="rounded-md bg-surface px-3 py-1.5 text-ink disabled:opacity-40"
            onClick={() => act(() => client.decideNarration(projectId, documentId, { decision: "reject", note: note.trim() || null }))}>
            {t("studio.narration.reject")}
          </button>
        </div>
      </section>
    );
  }

  // Completed: every line is editable; an edited line's voice is out of date until re-voiced.
  const stale = new Set(state.stale_beats ?? []);
  return (
    <section aria-label={t("studio.narration.script")} className="flex flex-col gap-3 text-sm">
      {stale.size > 0 ? <p className="text-xs text-copper">{t("studio.narration.staleCount", { count: stale.size })}</p> : null}
      {(script?.beats ?? []).map((beat) => (
        <article key={beat.beat} className="flex flex-col gap-1 rounded-md bg-surface p-3">
          <label className="flex flex-col gap-1 text-xs uppercase text-muted-ink">
            {beatLabel(beat.beat)}
            <textarea
              value={lines[beat.beat] ?? beat.text}
              maxLength={2000}
              onChange={(event) => setLines((current) => ({ ...current, [beat.beat]: event.target.value }))}
              className="rounded-md bg-well p-2 text-sm normal-case text-ink"
            />
          </label>
          <div className="flex items-center gap-2">
            <button type="button" disabled={busy || !(lines[beat.beat] ?? "").trim()} className="rounded bg-raised px-2 py-1 text-xs disabled:opacity-40"
              onClick={() => act(async () => {
                const updated = await client.editNarrationBeat(projectId, documentId, beat.beat, lines[beat.beat]!.trim());
                onChange({ ...state, script: updated, stale_beats: [...new Set([...stale, beat.beat])] });
              })}>
              {t("studio.narration.saveLine")}
            </button>
            {stale.has(beat.beat) ? (
              <>
                <span className="text-xs text-copper">{t("studio.narration.stale")}</span>
                <button type="button" disabled={busy} className="rounded bg-copper px-2 py-1 text-xs text-bg disabled:opacity-40"
                  onClick={() => act(() => client.revoiceNarrationBeat(projectId, documentId, beat.beat))}>
                  {t("studio.narration.revoice")}
                </button>
              </>
            ) : null}
          </div>
        </article>
      ))}
    </section>
  );
}
