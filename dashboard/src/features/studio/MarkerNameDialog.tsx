// A marker's name (Tier 3a): at most 60 characters, saved only on Save.
import { useEffect, useId, useRef, useState } from "react";

import { useLocale } from "@/lib/locale";

type Props = {
  label: string;
  onSave: (label: string) => void;
  onClose: () => void;
};

/** The server's longest marker name. */
const MAX_LABEL = 60;

const button = "rounded-md border border-hairline px-3 py-1.5 text-[13px] text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper";

export function MarkerNameDialog({ label, onSave, onClose }: Props) {
  const { t } = useLocale();
  const fieldId = useId();
  const field = useRef<HTMLInputElement>(null);
  const [text, setText] = useState(label);
  // Where focus was before the dialog opened; it goes back there when the dialog closes.
  const opener = useRef<Element | null>(document.activeElement);
  useEffect(() => {
    field.current?.focus();
    const back = opener.current as HTMLElement | null;
    return () => back?.focus?.({ preventScroll: true });
  }, []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/70 p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <form
        role="dialog"
        aria-modal="true"
        aria-label={t("studio.marker.renameTitle")}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
        onSubmit={(event) => {
          event.preventDefault();
          onSave(text.trim());
        }}
        className="flex w-full max-w-sm flex-col gap-3 rounded-lg border border-hairline bg-raised p-5"
      >
        <h2 className="text-sm font-semibold text-ink">{t("studio.marker.renameTitle")}</h2>
        <label htmlFor={fieldId} className="text-xs text-muted-ink">
          {t("studio.marker.name")}
        </label>
        <input
          ref={field}
          id={fieldId}
          type="text"
          maxLength={MAX_LABEL}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className="rounded-md border border-hairline bg-well px-2 py-1.5 text-sm text-ink focus-visible:outline-2 focus-visible:outline-copper"
        />
        <div className="flex justify-end gap-2">
          <button type="button" className={button} onClick={onClose}>
            {t("studio.marker.cancel")}
          </button>
          <button type="submit" className={`${button} text-copper`}>
            {t("studio.marker.save")}
          </button>
        </div>
      </form>
    </div>
  );
}
