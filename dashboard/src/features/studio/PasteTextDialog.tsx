// Where pasted text goes (spec 2026-11-08 §6): the person picks the place, and nothing is placed
// until they do. Text comes from the system clipboard; clips and media never do.
import { useEffect, useId, useRef } from "react";
import { X } from "lucide-react";

import { useLocale } from "@/lib/locale";
import type { PasteTarget } from "./timeline_edits";

type Props = {
  text: string;
  targets: { target: PasteTarget; disabled?: boolean; reason?: string }[];
  onPick: (target: PasteTarget) => void;
  onClose: () => void;
};

const choice =
  "w-full rounded-md border border-hairline px-3 py-2 text-left text-sm text-ink transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper aria-disabled:cursor-not-allowed aria-disabled:opacity-60 aria-disabled:hover:bg-transparent";

export function PasteTextDialog({ text, targets, onPick, onClose }: Props) {
  const { t } = useLocale();
  const panel = useRef<HTMLDivElement>(null);
  const reasonId = useId();
  // Where focus was before the dialog opened; it goes back there when the dialog closes.
  const opener = useRef<Element | null>(document.activeElement);
  useEffect(() => {
    panel.current?.focus();
    const back = opener.current as HTMLElement | null;
    return () => back?.focus?.({ preventScroll: true });
  }, []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/70 p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={t("studio.paste.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
        className="flex w-full max-w-sm flex-col gap-3 rounded-lg border border-hairline bg-raised p-5 outline-none"
      >
        <header className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">{t("studio.paste.title")}</h2>
          <button type="button" aria-label={t("studio.media.close")} onClick={onClose} className="rounded p-1 text-faint hover:text-ink">
            <X aria-hidden="true" size={16} />
          </button>
        </header>
        <blockquote className="line-clamp-3 break-words rounded-md bg-well px-3 py-2 text-xs text-muted-ink">{text}</blockquote>
        <div className="flex flex-col gap-2">
          {/* A place that does not apply stays in the tab order and says why in words (final review 2026-11-08). */}
          {targets.map(({ target, disabled, reason }) => (
            <button
              key={target}
              type="button"
              className={choice}
              aria-label={t(`studio.paste.target.${target}`)}
              aria-disabled={disabled || undefined}
              aria-describedby={disabled && reason ? `${reasonId}-${target}` : undefined}
              onClick={() => !disabled && onPick(target)}
            >
              {t(`studio.paste.target.${target}`)}
              {disabled && reason ? (
                <span id={`${reasonId}-${target}`} className="block text-xs text-faint">
                  {reason}
                </span>
              ) : null}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
