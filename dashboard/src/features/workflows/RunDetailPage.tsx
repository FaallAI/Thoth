// Run detail (DESIGN §8.3-8.6): the live stepper and log, the approval card, the failure, the results.
import { Bell, Check } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router";

import type { ArtifactRef, ControlPlaneClient, Project, WorkflowSummary } from "@/api/control-plane";
import { ConfirmDialog, EmptyState, Skeleton } from "@/components/Feedback";
import { PlatformIcon } from "@/components/PlatformIcon";
import { StageStepper, StatusPill, StepRow } from "@/components/RunProgress";
import { Button } from "@/components/ui/button";
import { downloadName } from "@/lib/download-name";
import { messages, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { askPermission, dismissOffer, notifyOnce, offerWanted, type RunEvent } from "@/lib/notifications";
import { PLATFORM_NAMES } from "@/lib/platforms";
import { useNow } from "@/lib/use-now";
import { useActivity } from "@/features/activity/activity";

import { OpenInStudio, type OpenInStudioClient } from "./OpenInStudio";
import { RunResults, type ContentSet } from "./RunResults";
import { finished, useReport, useRun, type RunClient } from "./useRun";

export type DetailClient = RunClient &
  OpenInStudioClient &
  Pick<
    ControlPlaneClient,
    "approveWorkflow" | "cancelWorkflow" | "listStylePresets" | "startProjectWorkflow" | "cardUrl" | "mediaUrl"
  >;

/** The parts of a source report the approval card counts. */
type SourceReport = {
  post?: { owner_handle?: string };
  media?: unknown[];
  comments?: { card?: unknown }[];
};

const EVENTS: Partial<Record<WorkflowSummary["status"], RunEvent>> = {
  awaiting_approval: "waiting",
  succeeded: "done",
  failed: "failed",
};

function artifact(summary: WorkflowSummary | null, kind: string): ArtifactRef | undefined {
  return summary?.artifacts?.find((item) => item.kind === kind);
}

function stageName(t: (key: MessageKey) => string, id: string, fallback: string): string {
  const key = `stage.${id}`;
  return key in messages.en ? t(key as MessageKey) : fallback;
}

export function RunDetailPage({
  client,
  workflowId,
  projects,
  onOpenStudio,
}: {
  client: DetailClient;
  workflowId: string;
  projects: Project[];
  onOpenStudio: (projectId: string, documentId: string, resolve: boolean) => void;
}) {
  const { locale, t, duration } = useLocale();
  const navigate = useNavigate();
  const { summary, steps, failed: unreachable, setSummary } = useRun(client, workflowId);
  const done = finished(summary);
  const now = useNow(1_000, !done);
  const report = useReport<SourceReport>(client, workflowId, artifact(summary, "source_report"));
  const contentSet = useReport<ContentSet>(client, workflowId, summary?.status === "succeeded" ? artifact(summary, "content_set") : undefined);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState<MessageKey | null>(null);
  const [offer, setOffer] = useState(offerWanted);
  const [announcement, setAnnouncement] = useState("");
  const seen = useRef<{ status?: string; stages: Record<string, string> }>({ stages: {} });
  const activity = useActivity();

  // Stage changes go to the live region, one sentence each, never per tick (§7.6); run events
  // become a desktop notification when the person has allowed them and looks elsewhere (§12.3).
  useEffect(() => {
    if (!summary) return;
    const before = seen.current;
    for (const stage of summary.stages) {
      const previous = before.stages[stage.id];
      if (previous !== undefined && previous !== stage.status) {
        setAnnouncement(
          t("detail.announce", {
            stage: stageName(t, stage.id, stage.label),
            status: t(`status.${stage.status === "completed" ? "succeeded" : stage.status}` as MessageKey),
          }),
        );
      }
      before.stages[stage.id] = stage.status;
    }
    const event = EVENTS[summary.status];
    if (event && before.status !== undefined && before.status !== summary.status) {
      notifyOnce(workflowId, event, t(`notify.${event}`), summary.title || summary.source.display_url);
    }
    before.status = summary.status;
  }, [summary, t, workflowId]);

  if (!summary) {
    return unreachable ? <EmptyState>{t("detail.notFound")}</EmptyState> : <Skeleton rows={8} />;
  }

  const act = async (action: () => Promise<WorkflowSummary>) => {
    setBusy(true);
    setActionError(null);
    try {
      setSummary(await action());
      activity?.refresh();
    } catch {
      setActionError("detail.actionFailed");
    } finally {
      setBusy(false);
    }
  };
  const retry = async () => {
    if (!summary.project_id) return;
    setBusy(true);
    setActionError(null);
    try {
      // Until per-stage retry exists, a retry is a new run of the same link (§7.5).
      const [preset] = await client.listStylePresets();
      const started = await client.startProjectWorkflow(
        summary.project_id,
        {
          source: { url: summary.source.display_url, intent: "produce_video" },
          style: { preset_id: preset?.preset_id ?? "" },
          output: { format: "mp4", language: "id" },
          review: { require_publish_approval: true },
        },
        crypto.randomUUID(),
      );
      navigate(`/workflows/${encodeURIComponent(started.workflow_id)}`);
    } catch {
      setActionError("detail.retryFailed");
    } finally {
      setBusy(false);
    }
  };
  const download = async (item: ArtifactRef) => {
    try {
      const url = URL.createObjectURL(await client.downloadWorkflowArtifact(workflowId, item.artifact_id));
      const link = document.createElement("a");
      link.href = url;
      link.download = downloadName(item);
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    } catch {
      setActionError("detail.downloadFailed");
    }
  };

  const time = (iso: string) =>
    new Intl.DateTimeFormat(locale === "id" ? "id-ID" : "en-US", { hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).format(
      new Date(iso),
    );
  const status = summary.status;
  const active = status === "queued" || status === "running" || status === "awaiting_approval";
  const project = projects.find((item) => item.project_id === summary.project_id);
  const title = summary.title || summary.source.display_url;
  const review = summary.stages.find((stage) => stage.id === "approval");
  const failedStage = summary.stages.find((stage) => stage.status === "failed");
  const lastStep = steps.at(-1);
  const content = artifact(summary, "content_set");
  const kept = (summary.artifacts ?? []).map((item) => item.label);
  const totalSeconds = (new Date(summary.updated_at).getTime() - new Date(summary.created_at).getTime()) / 1_000;
  const minutes = summary.estimate_seconds_remaining == null ? null : Math.max(1, Math.ceil(summary.estimate_seconds_remaining / 60));
  const sourceReport = report !== "error" ? report : null;

  let statusLine: string | null = null;
  if (status === "queued" || status === "running") {
    statusLine = minutes === null ? t("estimate.fewMinutes") : t("estimate.minutes", { minutes });
  } else if (status === "awaiting_approval" && review?.started_at) {
    statusLine = t("detail.waitingSince", { time: time(review.started_at) });
  } else if (status === "succeeded") {
    statusLine = t("detail.finishedIn", { duration: duration(totalSeconds) });
  } else if (status === "failed" && kept.length > 0) {
    statusLine = t("detail.kept", { items: kept.join(", ") });
  }

  const log = (
    <ul className="flex flex-col gap-0.5 rounded-[10px] bg-well p-3">
      {steps.length === 0 && <li className="px-3 py-2 text-sm text-muted-ink">{t("detail.emptyLog")}</li>}
      {steps.map((step) => (
        <StepRow key={step.seq} step={step} now={now} current={active && step === lastStep} />
      ))}
      {status === "failed" && (
        <li className="mt-1 rounded-md border-l-2 border-status-failed bg-raised px-3 py-2 text-sm">
          <p className="text-ink">{t("detail.failedStep", { stage: stageName(t, failedStage?.id ?? "", failedStage?.label ?? "") })}</p>
          <p className="text-muted-ink">{t("detail.whatToDo")}</p>
        </li>
      )}
    </ul>
  );

  return (
    <div className="flex flex-col gap-8">
      <p aria-live="polite" className="sr-only">
        {announcement}
      </p>
      <header className="flex flex-wrap items-start gap-4">
        {summary.has_post_card ? (
          <img src={client.cardUrl(workflowId, "post")} alt="" className="size-16 shrink-0 rounded-md bg-well object-cover object-top" />
        ) : (
          <span aria-hidden="true" className="grid size-16 shrink-0 place-items-center rounded-md bg-well text-muted-ink">
            <PlatformIcon platform={summary.source.platform} className="size-6" />
          </span>
        )}
        <div className="min-w-0 flex-1">
          <h2 className="truncate text-2xl leading-tight font-semibold text-ink" title={title}>
            {title}
          </h2>
          <p className="mt-1 text-sm text-muted-ink">
            {[
              PLATFORM_NAMES[summary.source.platform] ?? summary.source.platform,
              summary.owner_handle ? `@${summary.owner_handle}` : null,
              project ? t("project.current", { name: project.name }) : null,
            ]
              .filter(Boolean)
              .join(" · ")}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <StatusPill status={summary.history_expired ? "expired" : status} />
          {statusLine && <span className="text-sm text-muted-ink">{statusLine}</span>}
          {active && (
            <Button variant="ghost" disabled={busy} onClick={() => setConfirming(true)}>
              {t("detail.cancel")}
            </Button>
          )}
          {status === "failed" && summary.project_id && (
            <Button size="lg" disabled={busy} onClick={() => void retry()}>
              {t("detail.retry")}
            </Button>
          )}
          {status === "succeeded" && content && (
            <Button variant="secondary" size="lg" onClick={() => void download(content)}>
              {t("detail.download")}
            </Button>
          )}
          {status === "succeeded" && (
            <OpenInStudio client={client} projectId={summary.project_id ?? null} workflowId={workflowId} summary={summary} onOpen={onOpenStudio} />
          )}
        </div>
      </header>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("detail.cancelTitle")}
        description={t("detail.cancelBody")}
        confirmLabel={t("detail.cancel")}
        cancelLabel={t("detail.keepRunning")}
        danger
        onConfirm={() => void act(() => client.cancelWorkflow(workflowId))}
      />
      {actionError && (
        <p role="alert" className="text-sm text-status-failed">
          {t(actionError)}
        </p>
      )}
      {summary.history_expired && <p className="text-sm text-muted-ink">{t("detail.expired")}</p>}

      {offer && active && (
        <div className="flex flex-wrap items-center gap-3 rounded-[10px] bg-surface px-5 py-3 text-sm text-ink">
          <Bell aria-hidden="true" className="size-4 text-muted-ink" />
          <span className="flex-1">{t("notify.offer")}</span>
          <Button
            variant="ghost"
            onClick={() => {
              dismissOffer();
              setOffer(false);
            }}
          >
            {t("notify.notNow")}
          </Button>
          <Button
            onClick={() => {
              setOffer(false);
              void askPermission();
            }}
          >
            {t("notify.yes")}
          </Button>
        </div>
      )}

      {status === "awaiting_approval" && summary.approval && (
        <section aria-labelledby="approval-title" className="rounded-[10px] bg-surface p-6">
          <h2 id="approval-title" className="mb-5 text-base font-semibold text-ink">
            {t("approval.title")}
          </h2>
          <div className="grid gap-6 md:grid-cols-[minmax(0,22rem)_1fr]">
            {summary.has_post_card ? (
              <img src={client.cardUrl(workflowId, "post")} alt={t("results.card.post")} className="w-full rounded-md bg-well" />
            ) : (
              <div className="grid aspect-[4/5] place-items-center rounded-md bg-well text-sm text-faint">{t("results.notCaptured")}</div>
            )}
            <dl className="flex flex-col text-sm">
              {[
                [t("approval.media"), sourceReport?.media?.length],
                [t("approval.comments"), sourceReport?.comments?.length],
                [t("approval.commentCards"), sourceReport?.comments?.filter((comment) => comment.card).length],
                [t("approval.creator"), sourceReport?.post?.owner_handle ? `@${sourceReport.post.owner_handle}` : undefined],
              ].map(([label, value]) => (
                <div key={String(label)} className="flex justify-between border-b border-hairline py-3">
                  <dt className="text-muted-ink">{label}</dt>
                  <dd className="text-ink">{value ?? "–"}</dd>
                </div>
              ))}
            </dl>
          </div>
          <div className="mt-6 flex flex-wrap items-center gap-4 border-t border-hairline pt-5">
            <Button
              size="lg"
              disabled={busy}
              onClick={() => void act(() => client.approveWorkflow(workflowId, { approval_id: summary.approval!.approval_id, decision: "approve" }))}
            >
              {t("approval.approve")}
            </Button>
            {summary.approval.allowed_decisions.includes("reject") && (
              <Button
                variant="ghost"
                size="lg"
                disabled={busy}
                onClick={() => void act(() => client.approveWorkflow(workflowId, { approval_id: summary.approval!.approval_id, decision: "reject" }))}
              >
                {t("approval.stop")}
              </Button>
            )}
            <span className="text-sm text-muted-ink">{t("approval.kept")}</span>
          </div>
        </section>
      )}

      <div className="grid gap-10 lg:grid-cols-[minmax(0,5fr)_minmax(0,7fr)]">
        <section aria-labelledby="progress-title" className="flex flex-col gap-5">
          <h2 id="progress-title" className="text-base font-semibold text-ink">
            {t("detail.progress")}
          </h2>
          <StageStepper stages={summary.stages} now={now} />
          {status === "succeeded" && (
            <p className="flex justify-between border-t border-hairline pt-4 pl-8 text-sm text-ink">
              {t("detail.total")}
              <span className="font-mono">{duration(totalSeconds)}</span>
            </p>
          )}
        </section>
        <section aria-labelledby="activity-title" className="flex min-w-0 flex-col gap-5">
          <h2 id="activity-title" className="text-base font-semibold text-ink">
            {t(status === "succeeded" ? "detail.results" : "detail.activity")}
          </h2>
          {status === "succeeded" ? (
            <>
              {contentSet === "error" && <p className="text-sm text-status-failed">{t("results.unavailable")}</p>}
              {contentSet && contentSet !== "error" && <RunResults set={contentSet} workflowId={workflowId} client={client} />}
              <details className="border-t border-hairline pt-4">
                <summary className="cursor-pointer text-sm text-ink">{t("detail.showActivity", { count: steps.length })}</summary>
                <div className="mt-4">{log}</div>
              </details>
            </>
          ) : (
            <>
              {summary.has_post_card && (
                <div className="flex items-center gap-3">
                  <img src={client.cardUrl(workflowId, "post")} alt="" className="size-20 rounded-md bg-well object-cover object-top" />
                  <span className="inline-flex items-center gap-2 text-sm text-ink">
                    <Check aria-hidden="true" className="size-4 text-status-done" />
                    {t("detail.postCaptured")}
                  </span>
                </div>
              )}
              {log}
            </>
          )}
        </section>
      </div>
    </div>
  );
}
