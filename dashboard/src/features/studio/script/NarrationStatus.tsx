// The narration's status in Studio's header (spec 2026-11-01, Studio shell v2, goal 2): it says
// where the narration stands and what can be done next, instead of a button that looks dead.
import type { MessageKey } from "@/lib/i18n";
import { useEffect, useRef, useState, type MouseEvent } from "react";
import { LoaderCircle, Mic } from "lucide-react";

import { StudioImportRequestError, type ControlPlaneClient, type NarrationState } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { RevoiceConfirm } from "./RevoiceConfirm";
import type { StudioViewport } from "../studio_viewport";
import { isNarrationActive } from "./useNarration";

type Props = {
  client: Pick<ControlPlaneClient, "startNarration" | "revoiceNarrationBeat" | "restartNarration" | "getNarration">;
  projectId: string;
  documentId: string;
  state: NarrationState | null;
  /** "chip": a header chip that opens the block; "block": the block itself, inside a menu. */
  variant: "chip" | "block";
  onChange: (state: NarrationState) => void;
  onOpenScript: () => void;
  /** The script panel is open: the same button closes it. */
  scriptOpen?: boolean;
  onCloseScript?: () => void;
  /** How often a running re-voice is read back; tests shorten it. */
  pollMs?: number;
  /** A new or recreated narration started: Studio opens its script. */
  onStarted?: () => void;
};

/** The menu's amber dot: a completed narration has stale beats, and the menu (below 1440) holds the re-voice. */
export function narrationAttention(state: NarrationState | null, viewport: StudioViewport): boolean {
  return viewport !== "full_desktop" && state?.status === "completed" && (state.stale_beats ?? []).length > 0;
}

const action =
  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-[13px] text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40";

/** How long one beat's re-voice may run before the loop gives up. */
const REVOICE_WAIT_MS = 10 * 60 * 1000;

const reasonOf = (error: unknown) =>
  error instanceof StudioImportRequestError ? (error.code ?? "narration_unavailable") : "narration_unavailable";

/** Holds the control's place until the draft's narration has been read; it offers nothing to click. */
export function NarrationChecking({ variant }: Pick<Props, "variant">) {
  const { t } = useLocale();
  const label = t("studio.narration.checking");
  return (
    <p
      role="status"
      aria-label={label}
      className={
        variant === "chip"
          ? "inline-flex h-9 shrink-0 items-center gap-2 rounded-md border border-hairline px-3 text-[13px] text-muted-ink"
          : "flex items-center gap-2 px-2 py-1 text-[13px] text-muted-ink"
      }
    >
      <LoaderCircle aria-hidden="true" size={14} className="animate-spin" />
      {label}
    </p>
  );
}

/** Refusals a person can act on; any other shows a plain sentence, never its code. */
export const EXPLAINED_REFUSALS = new Set([
  "narration_not_available",
  "prompt_not_configured",
  "narration_in_progress",
  "narration_exists",
  "narration_preset_conflict",
  "revoice_failed",
]);

export function NarrationStatus({ client, projectId, documentId, state, variant, onChange, onOpenScript, scriptOpen = false, onCloseScript, pollMs = 3000, onStarted }: Props) {
  const { t } = useLocale();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [confirmingRevoice, setConfirmingRevoice] = useState(false);
  // A re-voice in flight stops when Studio closes: no more reads and no more paid beats.
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  const stale = state?.status === "completed" ? (state.stale_beats ?? []) : [];
  const beats = state?.script?.beats.length ?? 0;

  const run = async (work: () => Promise<void>) => {
    setBusy(true);
    setProblem(null);
    try {
      await work();
    } catch (error) {
      setProblem(reasonOf(error));
    } finally {
      setBusy(false);
    }
  };
  const create = () =>
    run(async () => {
      onChange(await client.startNarration(projectId, documentId));
      onStarted?.();
    });
  // One beat at a time, in story order; the first refusal stops the rest.
  const revoiceChanged = () =>
    run(async () => {
      setConfirmingRevoice(false);
      for (const beat of stale) {
        if (!mounted.current) return;
        let current = await client.revoiceNarrationBeat(projectId, documentId, beat);
        onChange(current);
        // The server takes one re-voice at a time (completed -> voicing until written), so each
        // beat must finish before the next is asked for; a stalled one gives up after the cap.
        const deadline = Date.now() + REVOICE_WAIT_MS;
        while (isNarrationActive(current)) {
          await new Promise((resolve) => setTimeout(resolve, pollMs));
          if (!mounted.current) return;
          if (Date.now() > deadline) throw new StudioImportRequestError(null, "narration_unavailable");
          // Studio's own poller reports the reads in between; this loop reports the end.
          current = await client.getNarration(projectId, documentId);
        }
        onChange(current);
        // A failed re-voice ends "completed" with a failure code (NarrationRevoiceWorkflow).
        if (current.status !== "completed" || current.failure_code) {
          throw new StudioImportRequestError(null, current.failure_code ?? current.status);
        }
      }
    });
  // The chip's menu would stay open over the canvas controls, beside the panel it just opened.
  const toggleScript = (event: MouseEvent<HTMLButtonElement>, toggle?: () => void) => {
    event.currentTarget.closest("details")?.removeAttribute("open");
    toggle?.();
  };
  const recreate = () =>
    run(async () => {
      setConfirming(false);
      onChange(await client.restartNarration(projectId, documentId));
      onStarted?.();
    });

  const summary =
    state === null || state.status === "failed" || state.status === "cancelled"
      ? null
      : state.status === "completed"
        ? t("studio.narration.narrated", { count: beats })
        : state.status === "awaiting_approval"
          ? t("studio.narration.readyToApprove")
          : t(`studio.narration.step.${state.status}`);

  const block = (
    <div className="flex flex-col gap-1" aria-label={t("studio.narration.title")} role="group">
      {summary ? (
        <p className="flex items-center gap-2 px-2 py-1 text-[13px] text-ink">
          {isNarrationActive(state) && state?.status !== "awaiting_approval" ? (
            <LoaderCircle aria-hidden="true" size={14} className="animate-spin text-muted-ink" />
          ) : (
            <Mic aria-hidden="true" size={14} className="text-status-done" />
          )}
          <span>{summary}</span>
          {stale.length ? (
            <span className="text-xs text-status-waiting">
              <span aria-hidden="true">· </span>
              <span>{t("studio.narration.needRevoice", { count: stale.length })}</span>
            </span>
          ) : null}
        </p>
      ) : null}
      {state?.status === "failed" ? (
        <p className="px-2 text-xs text-muted-ink">{t("studio.narration.failed", { code: state.failure_code ?? "unknown" })}</p>
      ) : null}
      {state?.status === "cancelled" ? <p className="px-2 text-xs text-muted-ink">{t("studio.narration.cancelled")}</p> : null}
      {summary === null ? (
        <button type="button" className="self-start rounded-md bg-copper px-3 py-1.5 text-[13px] font-medium text-bg disabled:opacity-40" disabled={busy} onClick={create}>
          {t("studio.narration.create")}
        </button>
      ) : null}
      {state?.status === "awaiting_approval" && !scriptOpen ? (
        <button type="button" className={action} onClick={(event) => toggleScript(event, onOpenScript)}>
          {t("studio.narration.readyToApprove")}
        </button>
      ) : null}
      {state?.status === "completed" ? (
        <>
          {stale.length && confirmingRevoice && state ? (
            <RevoiceConfirm state={state} beats={stale} busy={busy} onConfirm={revoiceChanged} onCancel={() => setConfirmingRevoice(false)} />
          ) : stale.length ? (
            <button type="button" className={action} disabled={busy} onClick={() => setConfirmingRevoice(true)}>
              {t("studio.narration.revoiceChanged", { count: stale.length })}
            </button>
          ) : null}
          {confirming ? (
            <div className="flex flex-col gap-2 rounded-md bg-surface p-2 text-xs text-muted-ink">
              <p>{t("studio.narration.restartWarning")}</p>
              <button type="button" className="self-start rounded-md bg-copper px-3 py-1 text-[13px] text-bg" disabled={busy} onClick={recreate}>
                {t("studio.narration.restartConfirm")}
              </button>
            </div>
          ) : (
            <button type="button" className={action} disabled={busy} onClick={() => setConfirming(true)}>
              {t("studio.narration.restartMenu")}
            </button>
          )}
        </>
      ) : null}
      {state && (scriptOpen || state.status !== "awaiting_approval") ? (
        <button type="button" className={action} onClick={(event) => toggleScript(event, scriptOpen ? onCloseScript : onOpenScript)}>
          {t(scriptOpen ? "studio.narration.closeScript" : "studio.narration.openScript")}
        </button>
      ) : null}
      {problem ? (
        <p role="status" className="px-2 text-xs text-danger">
          {t(EXPLAINED_REFUSALS.has(problem) ? (`studio.narration.refused.${problem}` as MessageKey) : "studio.narration.refused.other")}
        </p>
      ) : null}
    </div>
  );

  if (variant === "block" || state === null) return block;
  // A stopped narration is one chip in the header; its reason and Create sit behind it.
  const label = summary ?? t("studio.narration.stopped");
  return (
    <details className="relative shrink-0">
      <summary className="inline-flex h-9 cursor-pointer list-none items-center gap-2 rounded-md border border-hairline px-3 text-[13px] text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper [&::-webkit-details-marker]:hidden">
        <Mic aria-hidden="true" size={14} className={summary === null ? "text-status-failed" : stale.length ? "text-status-waiting" : "text-status-done"} />
        {label}
        {stale.length ? <span aria-hidden="true" className="size-1.5 rounded-full bg-status-waiting" /> : null}
      </summary>
      <div className="absolute top-11 right-0 z-40 w-72 rounded-[10px] border border-hairline bg-raised p-2 shadow-xl">{block}</div>
    </details>
  );
}
