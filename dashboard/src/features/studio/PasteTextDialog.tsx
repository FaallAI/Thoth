// Where pasted text goes (spec 2026-11-08 §6): the person picks the place, and nothing is placed
// until they do. Text comes from the system clipboard; clips and media never do.
import { useEffect, useRef } from "react";
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
  "w-full rounded-md border border-hairline px-3 py-2 text-left text-sm text-ink transition-colors hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40";

export function PasteTextDialog({ text, targets, onPick, onClose }: Props) {
  const { t } = useLocale();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => panel.current?.focus(), []);

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
          {targets.map(({ target, disabled, reason }) => (
            <button key={target} type="button" className={choice} disabled={disabled} title={reason} onClick={() => onPick(target)}>
              {t(`studio.paste.target.${target}`)}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
