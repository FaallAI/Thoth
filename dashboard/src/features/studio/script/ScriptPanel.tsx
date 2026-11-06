// Script mode (DESIGN §13.1, spec 2026-10-31): the narration's steps, the read-only approval
// with its TTS estimate, then the editable script with per-beat re-voice.
import { useState } from "react";
import { X } from "lucide-react";

import type { BeatName, ControlPlaneClient, NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import type { MessageKey } from "@/lib/i18n";

import { RevoiceConfirm } from "./RevoiceConfirm";

type Client = Pick<
  ControlPlaneClient,
  "decideNarration" | "editNarrationBeat" | "revoiceNarrationBeat" | "cancelNarration" | "restartNarration"
>;
type Props = {
  client: Client;
  projectId: string;
  documentId: string;
  state: NarrationState;
  onChange: (state: NarrationState) => void;
  onClose?: () => void;
};

const STEPS = ["transcribing", "scripting", "awaiting_approval", "voicing", "writing"] as const;
const PROVIDER_NAMES: Record<string, string> = { elevenlabs: "ElevenLabs" };
// The beats scroll between a fixed header and footer, so the decision never leaves the screen.
const PANEL = "flex h-full min-h-0 flex-col text-sm";
const HEADER = "flex h-12 shrink-0 items-center justify-between border-b border-hairline px-4";
const BEATS = "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto p-4";
const FOOTER = "flex shrink-0 flex-col gap-3 border-t border-hairline p-4";

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

export function ScriptPanel({ client, projectId, documentId, state, onChange, onClose }: Props) {
  const { t } = useLocale();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [lines, setLines] = useState<Record<string, string>>({});
  const [confirmRestart, setConfirmRestart] = useState(false);
  const [confirmRevoice, setConfirmRevoice] = useState<BeatName | null>(null);
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
      <p role="status" className="p-4 text-sm text-muted-ink">
        {state.status === "failed"
          ? t("studio.narration.failed", { code: state.failure_code ?? "narration_failed" })
          : t("studio.narration.cancelled")}
      </p>
    );
  }

  const cancel = (
    <button
      type="button"
      disabled={busy}
      className="flex-1 self-start rounded-md bg-surface px-3 py-1.5 text-[13px] text-muted-ink disabled:opacity-40"
      onClick={() => act(() => client.cancelNarration(projectId, documentId))}
    >
      {t("studio.narration.cancel")}
    </button>
  );

  if (state.status !== "awaiting_approval" && state.status !== "completed") {
    return (
      <div className="flex flex-col gap-3 p-4">
      <ol aria-label={t("studio.narration.script")} className="flex flex-col gap-1 text-sm">
        {STEPS.map((step) => (
          <li key={step} aria-current={step === state.status ? "step" : undefined} className="text-muted-ink aria-[current=step]:font-semibold aria-[current=step]:text-ink">
            {t(`studio.narration.step.${step}` as MessageKey)}
          </li>
        ))}
      </ol>
      {cancel}
      </div>
    );
  }

  if (state.status === "awaiting_approval" && script) {
    const estimate = state.estimate;
    return (
      <section aria-label={t("studio.narration.step.awaiting_approval")} className={PANEL}>
        <header className={HEADER}>
          <h2 className="font-semibold text-ink">{t("studio.narration.step.awaiting_approval")}</h2>
        </header>
        <div data-testid="script-beats" className={BEATS}>
          {script.beats.map((beat) => (
            <article key={beat.beat} className="flex flex-col gap-1">
              <h3 className="font-mono text-[11px] tracking-wide text-faint uppercase">{beatLabel(beat.beat)}</h3>
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
          <label className="flex flex-col gap-1 text-xs text-muted-ink">
            {t("studio.narration.note")}
            <textarea value={note} maxLength={500} onChange={(event) => setNote(event.target.value)} className="rounded-md bg-well p-2 text-sm text-ink" />
          </label>
        </div>
        <div className={FOOTER}>
          {estimate ? (
            <p className="flex flex-col gap-0.5 text-xs text-muted-ink">
              <span>{t("studio.narration.estimate", { characters: estimate.characters, provider: PROVIDER_NAMES[estimate.provider] ?? estimate.provider })}</span>
              <span className="text-faint">{estimate.usd == null ? t("studio.narration.unpriced") : t("studio.narration.price", { usd: estimate.usd.toFixed(4) })}</span>
            </p>
          ) : null}
          <button type="button" disabled={busy} className="rounded-md bg-copper px-3 py-2 font-medium text-bg disabled:opacity-40"
            onClick={() => act(() => client.decideNarration(projectId, documentId, { decision: "approve", note: null }))}>
            {t("studio.narration.approve")}
          </button>
          <div className="flex gap-2">
            <button type="button" disabled={busy} className="flex-1 rounded-md bg-surface px-3 py-1.5 text-ink disabled:opacity-40"
              onClick={() => act(() => client.decideNarration(projectId, documentId, { decision: "reject", note: note.trim() || null }))}>
              {t("studio.narration.reject")}
            </button>
            {cancel}
          </div>
        </div>
      </section>
    );
  }

  // Completed: every line is editable; an edited line's voice is out of date until re-voiced.
  const stale = new Set(state.stale_beats ?? []);
  return (
    <section aria-label={t("studio.narration.script")} className={PANEL}>
      <header className={HEADER}>
        <h2 className="font-semibold text-ink">{t("studio.narration.script")}</h2>
        {onClose ? (
          <button type="button" aria-label={t("studio.narration.closeScript")} onClick={onClose} className="grid size-7 place-items-center rounded-md text-muted-ink hover:bg-surface hover:text-ink focus-visible:outline-2 focus-visible:outline-copper">
            <X aria-hidden="true" size={15} />
          </button>
        ) : null}
      </header>
      <div data-testid="script-beats" className={BEATS}>
      {stale.size > 0 ? <p className="text-xs text-copper">{t("studio.narration.staleCount", { count: stale.size })}</p> : null}
      {state.status === "completed" && state.failure_code ? (
        <p role="status" className="text-xs text-danger">{t("studio.narration.revoiceFailed", { code: state.failure_code })}</p>
      ) : null}
      {(script?.beats ?? []).map((beat) => (
        <article key={beat.beat} className="flex flex-col gap-1">
          <label className="flex flex-col gap-1 font-mono text-[11px] tracking-wide text-faint uppercase">
            {beatLabel(beat.beat)}
            <textarea
              value={lines[beat.beat] ?? beat.text}
              maxLength={2000}
              onChange={(event) => setLines((current) => ({ ...current, [beat.beat]: event.target.value }))}
              // The whole line reads without scrolling inside its field.
              className="rounded-md bg-well p-2 font-sans text-sm tracking-normal normal-case text-ink [field-sizing:content]"
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
                  onClick={() => setConfirmRevoice(beat.beat)}>
                  {t("studio.narration.revoice")}
                </button>
              </>
            ) : null}
          </div>
          {confirmRevoice === beat.beat ? (
            <RevoiceConfirm
              state={state}
              beats={[beat.beat]}
              busy={busy}
              onConfirm={() => {
                setConfirmRevoice(null);
                void act(() => client.revoiceNarrationBeat(projectId, documentId, beat.beat));
              }}
              onCancel={() => setConfirmRevoice(null)}
            />
          ) : null}
        </article>
      ))}
      </div>
      <div className={FOOTER}>
        {/* A whole new script, approved again before any voice (operator, 2026-10-31). */}
        {confirmRestart ? (
          <div role="alert" className="flex flex-col gap-2 rounded-md bg-surface p-3 text-xs text-muted-ink">
            {t("studio.narration.restartWarning")}
            <div className="flex gap-2">
              <button type="button" disabled={busy} className="rounded bg-copper px-2 py-1 text-bg disabled:opacity-40"
                onClick={() => act(() => client.restartNarration(projectId, documentId))}>
                {t("studio.narration.restartConfirm")}
              </button>
              <button type="button" className="rounded bg-raised px-2 py-1 text-ink" onClick={() => setConfirmRestart(false)}>
                {t("common.cancel")}
              </button>
            </div>
          </div>
        ) : (
          <button type="button" className="rounded-md bg-surface px-3 py-1.5 text-[13px] text-muted-ink"
            onClick={() => setConfirmRestart(true)}>
            {t("studio.narration.restart")}
          </button>
        )}
      </div>
    </section>
  );
}
