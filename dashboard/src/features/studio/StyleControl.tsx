import { useEffect, useId, useRef, useState } from "react";

import type { AppliedStyleResult, EditDocumentV2, StyleSummary } from "@/api/control-plane";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

import { EXPLAINED_REFUSALS } from "./script/NarrationStatus";

/**
 * The draft's style (spec 2026-11-10): choosing Style A or Style B asks first, because a style
 * rebuilds the cuts and look, replaces hand edits and writes a new script for approval. No voice
 * is made until that script is approved with its cost shown.
 */
export function StyleControl({
  client,
  projectId,
  documentId,
  document,
  disabled,
  onApplied,
  variant = "chip",
}: {
  client: {
    listStyles: (projectId: string) => Promise<StyleSummary[]>;
    applyStyle: (
      projectId: string,
      documentId: string,
      request: { template_id: string; base_revision: number },
    ) => Promise<AppliedStyleResult>;
  };
  projectId: string;
  documentId: string;
  document: EditDocumentV2;
  disabled: boolean;
  onApplied: (result: AppliedStyleResult) => void;
  /** "chip" in the wide header, "block" inside the narrower menu, as NarrationChecking does. */
  variant?: "chip" | "block";
}) {
  const { t } = useLocale();
  const id = useId();
  const [styles, setStyles] = useState<StyleSummary[]>([]);
  const [asking, setAsking] = useState<StyleSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const keptKey = (document.style?.kept ?? []).join(",");
  const [dismissed, setDismissed] = useState<string | null>(null);
  const applyButton = useRef<HTMLButtonElement>(null);
  const { listStyles } = client;
  // Read once per project: the parent passes a new client object on every render.
  useEffect(() => {
    let live = true;
    void listStyles(projectId).then(
      (listed) => live && setStyles(listed),
      () => live && setStyles([]),
    );
    return () => {
      live = false;
    };
  }, [listStyles, projectId]);
  // The confirmation takes focus, so a keyboard or screen reader user knows it opened.
  useEffect(() => {
    if (asking) applyButton.current?.focus();
  }, [asking]);

  const current = document.style?.template_id ?? "";
  const apply = (style: StyleSummary) => {
    setBusy(true);
    setMessage(null);
    void client
      .applyStyle(projectId, documentId, { template_id: style.template_id, base_revision: document.revision })
      .then(
        (result) => {
          setAsking(null);
          onApplied(result);
          const code = result.narration_refused;
          if (code) {
            const reason = t(
              EXPLAINED_REFUSALS.has(code)
                ? (`studio.narration.refused.${code}` as MessageKey)
                : "studio.narration.refused.other",
            );
            setMessage(t("studio.style.narrationRefused", { reason }));
          }
        },
        () => setMessage(t("studio.style.failed")),
      )
      .finally(() => setBusy(false));
  };

  const keptNote = keptKey && dismissed !== keptKey;
  // The header is one row: the confirmation and the notes float under the control (e2e, 2026-11-10).
  // In the menu they flow under it instead: floating, they ran past a phone's edge (e2e, 2026-11-12).
  const panel = "rounded-md border border-hairline bg-surface p-2 text-xs text-muted-ink";
  const floating =
    variant === "chip" ? `absolute left-0 top-full z-50 mt-2 w-80 shadow-lg ${panel}` : panel;
  return (
    <div className="relative flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <label htmlFor={id} className="text-xs text-muted-ink">
          {t("studio.style.label")}
        </label>
        <select
          id={id}
          className="rounded-md border border-hairline bg-well px-2 py-1 text-xs text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:opacity-40"
          value={current}
          disabled={disabled || busy || !styles.length}
          onChange={(event) => {
            const chosen = styles.find((style) => style.template_id === event.target.value);
            if (chosen && chosen.template_id !== current) setAsking(chosen);
          }}
        >
          <option value="" disabled>
            {t("studio.style.none")}
          </option>
          {styles.map((style) => (
            <option key={style.template_id} value={style.template_id}>
              {style.name}
            </option>
          ))}
        </select>
      </div>
      {asking ? (
        <div
          role="alertdialog"
          aria-labelledby={`${id}-title`}
          aria-describedby={`${id}-rebuild ${id}-script`}
          className={`${floating} flex flex-col gap-2`}
          onKeyDown={(event) => {
            if (event.key === "Escape") setAsking(null);
          }}
        >
          <p id={`${id}-title`} className="font-medium text-ink">
            {t("studio.style.confirmTitle", { name: asking.name })}
          </p>
          <p id={`${id}-rebuild`}>{t("studio.style.confirmRebuild")}</p>
          <p id={`${id}-script`}>{t("studio.style.confirmScript")}</p>
          <div className="flex gap-2">
            <button
              ref={applyButton}
              type="button"
              className="rounded-md bg-copper px-3 py-1 text-[13px] text-bg disabled:opacity-40"
              disabled={busy}
              onClick={() => apply(asking)}
            >
              {t("studio.style.apply")}
            </button>
            <button type="button" className="rounded-md border border-hairline px-3 py-1 text-[13px] text-ink" onClick={() => setAsking(null)}>
              {t("studio.style.cancel")}
            </button>
          </div>
        </div>
      ) : null}
      {!asking && (message || keptNote) ? (
        <div className={`${floating} flex flex-col gap-2`}>
          {message ? <p role="status">{message}</p> : null}
          {/* A re-voice only stretches a beat that holds hand edits (operator, 2026-11-10). */}
          {keptNote ? (
            <p>
              {t("studio.style.kept", {
                beats: (document.style?.kept ?? []).map((beat) => t(`studio.story.beat.${beat}` as never)).join(", "),
              })}
            </p>
          ) : null}
          <button
            type="button"
            className="self-end rounded-md border border-hairline px-3 py-1 text-[13px] text-ink"
            onClick={() => {
              setMessage(null);
              setDismissed(keptKey);
            }}
          >
            {t("studio.style.dismiss")}
          </button>
        </div>
      ) : null}
    </div>
  );
}
