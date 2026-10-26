// Metric tile, empty state, skeleton and confirm dialog (DESIGN §6).
import { AlertDialog } from "@base-ui/react/alert-dialog";
import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";

/** Only real numbers: with no value there is no tile. */
export function MetricTile({ value, label, delta }: { value: string | null; label: string; delta?: string }) {
  if (value === null) return null;
  return (
    <div className="rounded-[10px] bg-surface px-5 py-4">
      <p className="text-[28px] leading-[1.1] font-semibold text-ink tabular-nums">{value}</p>
      <p className="mt-2 text-sm text-muted-ink">
        {label}
        {delta && <span className="ml-2 text-faint">{delta}</span>}
      </p>
    </div>
  );
}

/** One sentence and one action; no illustration. */
export function EmptyState({ children, action }: { children: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-4 rounded-[10px] bg-surface px-6 py-12 text-center">
      <p className="text-sm text-muted-ink">{children}</p>
      {action}
    </div>
  );
}

/** Loading rows in the shape of what is coming; never a full-page spinner. */
export function Skeleton({ rows = 3, className }: { rows?: number; className?: string }) {
  const { t } = useLocale();
  return (
    <div role="status" aria-label={t("common.loading")} className={cn("flex flex-col gap-3", className)}>
      {Array.from({ length: rows }, (_, index) => (
        <span key={index} className="h-10 animate-pulse rounded-md bg-surface" />
      ))}
    </div>
  );
}

/**
 * Asks before an action that cannot be undone, saying what happens and what is kept. The
 * confirm label is a verb and an object ("Cancel run"); `danger` paints it red.
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  onConfirm,
  danger = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  onConfirm: () => void;
  danger?: boolean;
}) {
  const { t } = useLocale();
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Backdrop className="fixed inset-0 bg-black/60" />
        <AlertDialog.Popup className="fixed top-1/2 left-1/2 w-[min(440px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-[10px] bg-raised p-6 shadow-xl">
          <AlertDialog.Title className="text-base font-semibold text-ink">{title}</AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm text-muted-ink">{description}</AlertDialog.Description>
          <div className="mt-6 flex justify-end gap-2">
            <AlertDialog.Close render={<Button variant="ghost" />}>{t("common.cancel")}</AlertDialog.Close>
            <Button
              variant={danger ? "destructive" : "default"}
              onClick={() => {
                onConfirm();
                onOpenChange(false);
              }}
            >
              {confirmLabel}
            </Button>
          </div>
        </AlertDialog.Popup>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
