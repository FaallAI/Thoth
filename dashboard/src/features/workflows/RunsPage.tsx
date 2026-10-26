// Runs (DESIGN §8.1): metrics when real, filters kept in the URL, and live rows.
import { Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState, type SyntheticEvent } from "react";
import { Link, useNavigate, useSearchParams } from "react-router";

import type { ControlPlaneClient, Project, RunMetrics, RunStatus, WorkflowRun } from "@/api/control-plane";
import { EmptyState, MetricTile, Skeleton } from "@/components/Feedback";
import { PageActions } from "@/components/PageActions";
import { PlatformIcon } from "@/components/PlatformIcon";
import { SegmentedStageBar, StatusPill } from "@/components/RunProgress";
import { Button } from "@/components/ui/button";
import { ALL_PROJECTS } from "@/lib/active-project";
import { formatClock, messages, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { displayHost, PLATFORM_NAMES, PLATFORMS } from "@/lib/platforms";
import { stepText } from "@/lib/steps";
import { useNow } from "@/lib/use-now";
import { cn } from "@/lib/utils";

import { NewRunDialog, type NewRunClient } from "./NewRunDialog";

export type RunsClient = NewRunClient & Pick<ControlPlaneClient, "listRuns" | "runMetrics" | "moveWorkflow" | "cardUrl">;

/** The status tabs and the run statuses each one lists. */
const TABS = {
  all: [],
  running: ["queued", "running", "unknown"],
  waiting: ["awaiting_approval"],
  done: ["succeeded"],
  failed: ["failed"],
} satisfies Record<string, RunStatus[]>;
type Tab = keyof typeof TABS;
const ACTIVE = new Set<RunStatus>(["queued", "running", "awaiting_approval", "unknown"]);
/** Live rows refresh on this beat; the open run itself polls every second. */
const REFRESH_MS = 5_000;

function stageName(t: (key: MessageKey) => string, id: string, fallback = id): string {
  const key = `stage.${id}`;
  return key in messages.en ? t(key as MessageKey) : fallback;
}

function RunRow({
  run,
  client,
  now,
  projects,
  allProjects,
  onMove,
}: {
  run: WorkflowRun;
  client: RunsClient;
  now: Date;
  projects: Project[];
  allProjects: boolean;
  onMove: (workflowId: string, projectId: string) => void;
}) {
  const { locale, t, day } = useLocale();
  const stages = run.stages ?? [];
  const title = run.title || run.source.display_url;
  const time = (iso: string) =>
    new Intl.DateTimeFormat(locale === "id" ? "id-ID" : "en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(
      new Date(iso),
    );
  const failed = stages.find((stage) => stage.status === "failed");
  const running = stages.find((stage) => stage.status === "running");
  let line: string | null = null;
  if (run.status === "awaiting_approval") {
    line = t("runs.row.waitingSince", { stage: stageName(t, "approval"), time: time(run.updated_at) });
  } else if (run.status === "failed" && failed) {
    line = t("runs.row.failedAt", { stage: stageName(t, failed.id, failed.label) });
  } else if (running) {
    const step = run.current_step ? stepText(locale, run.current_step) : null;
    line = [stageName(t, running.id, running.label), step].filter(Boolean).join(" · ");
  }
  const seconds = (new Date(ACTIVE.has(run.status) ? now : run.updated_at).getTime() - new Date(run.created_at).getTime()) / 1_000;
  const project = projects.find((item) => item.project_id === run.project_id);
  return (
    <tr className="group border-b border-hairline hover:bg-raised">
      <td className="py-4 pr-4 pl-3">
        <StatusPill status={run.history_expired ? "expired" : run.status} />
      </td>
      <td className="py-3 pr-4">
        <div className="flex min-w-0 items-center gap-3">
          {run.has_post_card ? (
            <img src={client.cardUrl(run.workflow_id, "post")} alt="" className="size-12 shrink-0 rounded-md bg-well object-cover object-top" />
          ) : (
            <span aria-hidden="true" className="grid size-12 shrink-0 place-items-center rounded-md bg-well text-muted-ink">
              <PlatformIcon platform={run.source.platform} />
            </span>
          )}
          <div className="min-w-0">
            <Link
              to={`/workflows/${encodeURIComponent(run.workflow_id)}`}
              title={title}
              className="block max-w-[52ch] truncate text-[15px] text-ink after:absolute after:inset-0 group-hover:underline"
            >
              {title}
            </Link>
            <p className="truncate text-[13px] text-muted-ink">
              {displayHost(run.source.display_url)}
              {line && (
                <span className={cn(run.status === "failed" ? "text-status-failed" : run.status === "awaiting_approval" && "text-status-waiting")}>
                  {" · "}
                  {line}
                </span>
              )}
            </p>
          </div>
        </div>
      </td>
      <td className="py-3 pr-4 text-muted-ink max-md:hidden">
        <PlatformIcon platform={run.source.platform} label />
      </td>
      {allProjects && (
        <td className="relative z-10 py-3 pr-4 text-sm text-ink max-lg:hidden">
          {project ? (
            project.name
          ) : (
            <select
              aria-label={t("runs.row.moveLabel", { name: title })}
              defaultValue=""
              onChange={(event) => event.target.value && onMove(run.workflow_id, event.target.value)}
              className="h-8 rounded-md border border-hairline bg-well px-2 text-sm text-muted-ink"
            >
              <option value="">{t("runs.row.move")}</option>
              {projects.map((item) => (
                <option key={item.project_id} value={item.project_id}>
                  {item.name}
                </option>
              ))}
            </select>
          )}
        </td>
      )}
      <td className="py-3 pr-4 max-md:hidden">{stages.length > 0 && <SegmentedStageBar stages={stages} />}</td>
      <td className="py-3 pr-4 text-sm whitespace-nowrap text-ink max-md:hidden">{day(run.created_at)}</td>
      <td className="py-3 pr-3 font-mono text-[13px] text-ink max-md:hidden">
        {run.status === "awaiting_approval" ? "–" : formatClock(seconds)}
      </td>
    </tr>
  );
}

/** The run list of one project, or of all of them with a Project column (DESIGN §5.5). */
export function RunsPage({
  client,
  projectId,
  projects,
  onRuns,
}: {
  client: RunsClient;
  projectId: string | null;
  projects: Project[];
  onRuns?: (runs: WorkflowRun[]) => void;
}) {
  const { t, number, duration, locale } = useLocale();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("status") as Tab | null) ?? "all";
  const platform = params.get("platform") ?? "";
  const q = params.get("q") ?? "";
  const [draft, setDraft] = useState(q);
  const [runs, setRuns] = useState<WorkflowRun[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [error, setError] = useState<"load" | "move" | null>(null);
  const [dialog, setDialog] = useState<{ open: boolean; url: string }>({ open: false, url: "" });
  const [reload, setReload] = useState(0);
  const allProjects = projectId === ALL_PROJECTS;
  const scope = allProjects ? null : projectId;
  const live = (runs ?? []).some((run) => ACTIVE.has(run.status));
  const now = useNow(1_000, live);
  const query = useMemo(
    () => ({ projectId: scope, status: TABS[tab] ?? [], platform: platform || undefined, q: q || undefined }),
    [scope, tab, platform, q],
  );

  const load = useCallback(
    async (quiet: boolean) => {
      try {
        const page = await client.listRuns(query);
        setRuns((current) => {
          // A refresh keeps the pages loaded after the first one.
          if (!quiet || !current) return page.items;
          const fresh = new Set(page.items.map((run) => run.workflow_id));
          return [...page.items, ...current.slice(page.items.length).filter((run) => !fresh.has(run.workflow_id))];
        });
        if (!quiet) setNext(page.next_cursor ?? null);
        setError(null);
      } catch {
        if (!quiet) setError("load");
      }
    },
    [client, query],
  );

  useEffect(() => {
    if (!projectId) {
      setRuns([]);
      return;
    }
    setRuns(null);
    void load(false);
    client.runMetrics(scope).then(setMetrics, () => setMetrics(null));
  }, [client, projectId, scope, load, reload]);

  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      if (document.visibilityState === "visible") void load(true);
    }, REFRESH_MS);
    return () => clearInterval(timer);
  }, [live, load]);

  useEffect(() => {
    onRuns?.(runs ?? []);
  }, [runs, onRuns]);

  const setFilter = (key: string, value: string) => {
    const nextParams = new URLSearchParams(params);
    if (value) nextParams.set(key, value);
    else nextParams.delete(key);
    setParams(nextParams, { replace: true });
  };
  const search = (event: SyntheticEvent) => {
    event.preventDefault();
    setFilter("q", draft.trim());
  };
  const more = async () => {
    if (!next) return;
    try {
      const page = await client.listRuns(query, next);
      setRuns((current) => [...(current ?? []), ...page.items]);
      setNext(page.next_cursor ?? null);
    } catch {
      setError("load");
    }
  };
  const move = async (workflowId: string, target: string) => {
    try {
      await client.moveWorkflow(workflowId, target);
      setReload((n) => n + 1);
    } catch {
      setError("move");
    }
  };

  const filtered = tab !== "all" || platform !== "" || q !== "";
  const percent = (value: number) =>
    new Intl.NumberFormat(locale === "id" ? "id-ID" : "en-US", { style: "percent", maximumFractionDigits: 0 }).format(value);
  const tiles = metrics
    ? [
        metrics.runs_this_week > 0 ? { value: number(metrics.runs_this_week), label: t("runs.metric.week") } : null,
        metrics.median_run_seconds != null ? { value: duration(metrics.median_run_seconds), label: t("runs.metric.median") } : null,
        metrics.success_rate != null ? { value: percent(metrics.success_rate), label: t("runs.metric.success") } : null,
        metrics.content_sets > 0 ? { value: number(metrics.content_sets), label: t("runs.metric.contentSets") } : null,
      ].filter((tile) => tile !== null)
    : [];

  return (
    <div className="flex flex-col gap-6">
      <PageActions>
        <Button size="lg" onClick={() => setDialog({ open: true, url: "" })} disabled={!projectId || projects.length === 0}>
          {t("runs.new")}
        </Button>
      </PageActions>
      <NewRunDialog
        client={client}
        open={dialog.open}
        initialUrl={dialog.url}
        onOpenChange={(open) => setDialog((current) => ({ ...current, open }))}
        projectId={projectId}
        projects={projects}
        onStarted={(workflowId) => navigate(`/workflows/${encodeURIComponent(workflowId)}`)}
      />

      {tiles.length > 0 && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {tiles.map((tile) => (
            <MetricTile key={tile.label} value={tile.value} label={tile.label} />
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        <div role="group" aria-label={t("runs.filter.label")} className="flex rounded-md bg-surface p-1">
          {(Object.keys(TABS) as Tab[]).map((key) => (
            <button
              key={key}
              type="button"
              aria-pressed={tab === key}
              onClick={() => setFilter("status", key === "all" ? "" : key)}
              className={cn("rounded px-3 py-1.5 text-sm text-muted-ink", tab === key && "bg-raised text-ink")}
            >
              {t(`runs.filter.${key}`)}
            </button>
          ))}
        </div>
        <select
          aria-label={t("runs.filter.platform")}
          value={platform}
          onChange={(event) => setFilter("platform", event.target.value)}
          className="h-10 rounded-md border border-hairline bg-bg px-3 text-sm text-ink"
        >
          <option value="">{t("runs.filter.platformAll")}</option>
          {PLATFORMS.map((value) => (
            <option key={value} value={value}>
              {PLATFORM_NAMES[value]}
            </option>
          ))}
        </select>
        <form onSubmit={search} className="relative ml-auto w-full sm:w-72" role="search">
          <Search aria-hidden="true" className="absolute top-3 left-3 size-4 text-faint" />
          <input
            type="search"
            aria-label={t("runs.filter.search")}
            placeholder={t("runs.filter.search")}
            value={draft}
            maxLength={100}
            onChange={(event) => setDraft(event.target.value)}
            onBlur={() => draft.trim() !== q && setFilter("q", draft.trim())}
            className="h-10 w-full rounded-md border border-hairline bg-well pr-3 pl-9 text-sm text-ink"
          />
        </form>
      </div>

      {error === "move" && (
        <p role="alert" className="text-sm text-status-failed">
          {t("runs.moveFailed")}
        </p>
      )}
      {error === "load" && (
        <EmptyState action={<Button variant="secondary" onClick={() => setReload((n) => n + 1)}>{t("common.retry")}</Button>}>
          {t("runs.error")}
        </EmptyState>
      )}
      {!projectId && <EmptyState>{t("project.choose")}</EmptyState>}
      {projectId && runs === null && error === null && <Skeleton rows={6} />}
      {projectId && runs?.length === 0 && error === null &&
        (filtered ? (
          <EmptyState>{t("runs.emptyFiltered")}</EmptyState>
        ) : (
          <EmptyState
            action={
              <form
                className="flex w-full max-w-md gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  const url = String(new FormData(event.currentTarget).get("url") ?? "");
                  setDialog({ open: true, url });
                }}
              >
                <input name="url" type="url" aria-label={t("newRun.link")} placeholder={t("newRun.placeholder")} className="h-10 flex-1 rounded-md border border-hairline bg-well px-3 text-sm text-ink" />
                <Button type="submit">{t("runs.new")}</Button>
              </form>
            }
          >
            {t("runs.empty")}
          </EmptyState>
        ))}
      {runs && runs.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="border-b border-hairline text-[13px] text-muted-ink">
                <th className="py-3 pr-4 pl-3 font-medium">{t("runs.col.status")}</th>
                <th className="py-3 pr-4 font-medium">{t("runs.col.post")}</th>
                <th className="py-3 pr-4 font-medium max-md:hidden">
                  <span className="sr-only">{t("runs.col.platform")}</span>
                </th>
                {allProjects && <th className="py-3 pr-4 font-medium max-lg:hidden">{t("runs.col.project")}</th>}
                <th className="py-3 pr-4 font-medium max-md:hidden">{t("runs.col.stage")}</th>
                <th className="py-3 pr-4 font-medium max-md:hidden">{t("runs.col.started")}</th>
                <th className="py-3 pr-3 font-medium max-md:hidden">{t("runs.col.duration")}</th>
              </tr>
            </thead>
            <tbody className="[&_tr]:relative">
              {runs.map((run) => (
                <RunRow key={run.workflow_id} run={run} client={client} now={now} projects={projects} allProjects={allProjects} onMove={(id, target) => void move(id, target)} />
              ))}
            </tbody>
          </table>
          {next && (
            <div className="mt-4 flex justify-center">
              <Button variant="secondary" onClick={() => void more()}>
                {t("runs.more")}
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
