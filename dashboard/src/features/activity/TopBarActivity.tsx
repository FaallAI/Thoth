// The run tray and the inbox bell in the top bar (DESIGN §4, §7.6).
import { Popover } from "@base-ui/react/popover";
import { ArrowRight, Bell } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";

import type { Project } from "@/api/control-plane";
import { StageStepper } from "@/components/RunProgress";
import { useLocale } from "@/lib/locale";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

import { useActivity } from "./activity";

/** "2 running · 1 waiting"; opened, every active run with its compact stepper. */
export function RunTray({ projects }: { projects: Project[] }) {
  const activity = useActivity();
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  const now = useNow(1_000, open);
  if (!activity) return null;
  const waiting = activity.active.filter((run) => run.status === "awaiting_approval").length;
  const running = activity.active.length - waiting;
  const summary = t("tray.summary", { running, waiting });
  if (activity.active.length === 0) return null;
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={summary}
        className="flex h-10 items-center gap-2 rounded-md bg-surface px-3 text-sm text-ink hover:bg-raised"
      >
        <span aria-hidden="true" className={cn("size-2 rounded-full", running > 0 ? "animate-pulse bg-status-running" : "bg-status-waiting")} />
        <span className="max-sm:hidden">{summary}</span>
        <span aria-hidden="true" className="flex items-center gap-2 sm:hidden">
          {running}
          <span className="size-2 rounded-full bg-status-waiting" />
          {waiting}
        </span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={8} className="z-40">
          <Popover.Popup className="w-[min(480px,calc(100vw-32px))] rounded-[10px] border border-hairline bg-raised p-2 shadow-xl">
            <div className="flex items-baseline justify-between px-3 py-2">
              <Popover.Title className="text-sm font-semibold text-ink">{t("tray.title")}</Popover.Title>
              <span className="text-xs text-muted-ink">{summary}</span>
            </div>
            <ul className="flex max-h-[60vh] flex-col overflow-y-auto">
              {activity.active.map((run) => (
                <li key={run.workflow_id} className="flex items-start gap-3 rounded-md px-3 py-3 hover:bg-surface">
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/workflows/${encodeURIComponent(run.workflow_id)}`}
                      onClick={() => setOpen(false)}
                      className="block truncate text-sm font-medium text-ink hover:underline"
                    >
                      {run.title || run.source.display_url}
                    </Link>
                    <p className="text-xs text-muted-ink">
                      {projects.find((project) => project.project_id === run.project_id)?.name ?? t("inbox.noProject")}
                    </p>
                    <div className="mt-2">
                      <StageStepper stages={run.stages ?? []} variant="compact" now={now} />
                    </div>
                  </div>
                  {run.status === "awaiting_approval" && (
                    <Link
                      to={`/workflows/${encodeURIComponent(run.workflow_id)}`}
                      onClick={() => setOpen(false)}
                      className="shrink-0 rounded-md bg-copper px-3 py-1.5 text-sm font-medium text-[#1b1918]"
                    >
                      {t("tray.review")}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
            <Link
              to="/workflows"
              onClick={() => setOpen(false)}
              className="mt-1 flex items-center gap-2 border-t border-hairline px-3 pt-3 pb-1 text-sm text-copper"
            >
              {t("tray.allRuns")}
              <ArrowRight aria-hidden="true" className="size-4" />
            </Link>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** The bell names how many decisions wait and opens the inbox. */
export function InboxBell() {
  const activity = useActivity();
  const { t, plural } = useLocale();
  if (!activity) return null;
  const count = activity.waiting;
  return (
    <Link
      to="/inbox"
      aria-label={count > 0 ? t("topbar.inboxWith", { waiting: plural("inbox.count", count) }) : t("topbar.inbox")}
      className="relative grid size-10 place-items-center rounded-md text-ink hover:bg-raised"
    >
      <Bell aria-hidden="true" className="size-5" />
      {count > 0 && (
        <span aria-hidden="true" className="absolute top-1 right-1 grid min-w-4 place-items-center rounded-full bg-status-waiting px-1 text-[11px] font-semibold text-bg">
          {count}
        </span>
      )}
    </Link>
  );
}
