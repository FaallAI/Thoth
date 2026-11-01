// Studio's top bar (spec 2026-11-01, Studio shell v2): one 56 px row from 1024 up; whatever does
// not fit lives in the overflow menu, so nothing wraps or stacks.
import { useId, type ReactNode } from "react";
import { ArrowLeft, Ellipsis } from "lucide-react";

import { useLocale } from "@/lib/locale";

import type { StudioViewport } from "./studio_viewport";

type Props = {
  title: string;
  viewport: StudioViewport;
  onBack: () => void;
  backDisabled: boolean;
  jobs: ReactNode;
  mode?: ReactNode;
  history?: ReactNode;
  save: ReactNode;
  /** Request review: the one primary action. */
  primary?: ReactNode;
  /** The narration status: inline at full desktop, at the top of the menu below it. */
  narration?: ReactNode;
  menu: ReactNode;
  /** A beat needs re-voice: the menu button carries an amber dot. */
  menuAttention?: boolean;
  /** Anything else the header must keep, after the title (a compact-screen note). */
  extra?: ReactNode;
};

export function StudioHeader({
  title,
  viewport,
  onBack,
  backDisabled,
  jobs,
  mode,
  history,
  save,
  primary,
  narration,
  menu,
  menuAttention = false,
  extra,
}: Props) {
  const { t } = useLocale();
  const backDescriptionId = useId();
  const oneRow = viewport === "compact_desktop" || viewport === "full_desktop";
  const inlineNarration = viewport === "full_desktop";
  return (
    <header
      className={`studio-topbar relative flex items-center gap-x-3 border-b border-hairline bg-bg px-4 ${
        oneRow ? "h-14 flex-nowrap" : "min-h-14 flex-wrap gap-y-1 py-1"
      }`}
    >
      <button
        type="button"
        className="inline-flex h-9 shrink-0 items-center gap-1.5 rounded-md px-2 text-sm text-muted-ink hover:bg-surface hover:text-ink focus-visible:outline-2 focus-visible:outline-copper disabled:cursor-not-allowed disabled:opacity-40"
        onClick={onBack}
        disabled={backDisabled}
        aria-label={t("studio.editor.backLabel")}
        aria-describedby={backDisabled ? backDescriptionId : undefined}
      >
        <ArrowLeft aria-hidden="true" size={16} />
        {viewport === "compact_desktop" ? null : t("studio.editor.back")}
      </button>
      <span id={backDescriptionId} className="sr-only">
        {t("studio.editor.backDisabled")}
      </span>
      <span aria-hidden="true" className="h-5 w-px shrink-0 bg-hairline" />
      <span className={`min-w-0 truncate text-[15px] font-semibold text-ink ${oneRow ? "max-w-[16rem] flex-initial" : "flex-1"}`} title={title}>
        {title}
      </span>
      {oneRow ? (
        <>
          {jobs}
          {mode}
          {extra}
          <span aria-hidden="true" className="flex-1" />
        </>
      ) : (
        // Below 1024 the title keeps the first row; jobs and mode take the second.
        <div className="order-last flex min-w-0 basis-full items-center gap-2">
          {jobs}
          {mode}
          {extra}
        </div>
      )}
      {inlineNarration ? narration : null}
      {history}
      <div className="flex min-w-0 shrink-0 items-center gap-2 text-[13px] whitespace-nowrap text-muted-ink">{save}</div>
      {primary && viewport !== "phone" ? <div className="shrink-0 whitespace-nowrap">{primary}</div> : null}
      <details className="relative shrink-0">
        <summary
          aria-label={t("studio.editor.menu")}
          className="relative grid size-9 cursor-pointer list-none place-items-center rounded-md border border-hairline text-muted-ink hover:bg-surface hover:text-ink focus-visible:outline-2 focus-visible:outline-copper [&::-webkit-details-marker]:hidden"
        >
          <Ellipsis aria-hidden="true" size={16} />
          {menuAttention ? (
            <span data-testid="menu-attention" aria-hidden="true" className="absolute top-1 right-1 size-2 rounded-full bg-status-waiting" />
          ) : null}
        </summary>
        <div className="absolute top-11 right-0 z-40 flex w-80 flex-col gap-3 rounded-[10px] border border-hairline bg-raised p-4 text-sm shadow-xl">
          {inlineNarration ? null : narration}
          {menu}
          {viewport === "phone" ? primary : null}
        </div>
      </details>
    </header>
  );
}
