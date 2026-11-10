import { useEffect, useId, useState } from "react";

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
}) {
  const { t } = useLocale();
  const id = useId();
  const [styles, setStyles] = useState<StyleSummary[]>([]);
  const [asking, setAsking] = useState<StyleSummary | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    void client.listStyles(projectId).then(
      (listed) => live && setStyles(listed),
      () => live && setStyles([]),
    );
    return () => {
      live = false;
    };
  }, [client, projectId]);

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

  return (
    <div className="flex flex-col gap-2">
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
        <div role="alertdialog" aria-labelledby={`${id}-title`} className="flex flex-col gap-2 rounded-md bg-surface p-2 text-xs text-muted-ink">
          <p id={`${id}-title`} className="font-medium text-ink">
            {t("studio.style.confirmTitle", { name: asking.name })}
          </p>
          <p>{t("studio.style.confirmRebuild")}</p>
          <p>{t("studio.style.confirmScript")}</p>
          <div className="flex gap-2">
            <button
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
      {message ? (
        <p role="status" className="text-xs text-muted-ink">
          {message}
        </p>
      ) : null}
    </div>
  );
}
