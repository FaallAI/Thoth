// The keyboard shortcut list (spec 2026-11-08 §5.1), opened with ? or Ctrl+/ and from the workspace menu.
// It reads SHORTCUTS, the same list the right-click menus show their keys from.
import { useEffect, useRef } from "react";
import { X } from "lucide-react";

import { useLocale } from "@/lib/locale";
import { SHORTCUTS, type ShortcutGroup } from "./studio_keys";

const GROUPS: readonly ShortcutGroup[] = ["editing", "playback", "view", "studio"];

export function ShortcutsDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { t } = useLocale();
  const panel = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (open) panel.current?.focus();
  }, [open]);
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/70 p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={t("studio.shortcuts.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
        className="flex max-h-[85vh] w-full max-w-xl flex-col gap-4 overflow-auto rounded-lg border border-hairline bg-raised p-5 outline-none"
      >
        <header className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">{t("studio.shortcuts.title")}</h2>
          <button type="button" aria-label={t("studio.media.close")} onClick={onClose} className="rounded p-1 text-faint hover:text-ink">
            <X aria-hidden="true" size={16} />
          </button>
        </header>
        <div className="grid gap-4 sm:grid-cols-2">
          {GROUPS.map((group) => (
            <table key={group} aria-label={t(`studio.shortcuts.group.${group}`)} className="self-start text-[13px]">
              <caption className="pb-1 text-left text-[11px] uppercase tracking-wide text-faint">{t(`studio.shortcuts.group.${group}`)}</caption>
              <tbody>
                {SHORTCUTS.filter((entry) => entry.group === group).map((entry) => (
                  <tr key={entry.action}>
                    <th scope="row" className="py-0.5 pr-4 text-left font-normal text-ink">
                      {t(`studio.shortcuts.action.${entry.action}`)}
                    </th>
                    <td className="py-0.5 text-right">
                      <kbd className="rounded border border-hairline bg-well px-1.5 py-0.5 font-mono text-[11px] text-muted-ink">{entry.keys}</kbd>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ))}
        </div>
      </div>
    </div>
  );
}
