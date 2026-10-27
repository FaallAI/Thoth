// Run progress pieces: status pill, stage bar, stage stepper and step row (DESIGN §6, §7).
import { Check, CircleX, Hourglass, LoaderCircle, TriangleAlert } from "lucide-react";

import type { components } from "@/api/generated/control-plane";
import { messages, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { stepText } from "@/lib/steps";
import { cn } from "@/lib/utils";

type Stage = components["schemas"]["StageSummary"];
type Step = components["schemas"]["WorkflowStep"];
type RunStatus = components["schemas"]["WorkflowStatus"] | "unknown";
export type Status = RunStatus | Stage["status"] | "expired";

type Tone = "running" | "waiting" | "done" | "failed" | "idle";

/** Runs and stages name their states differently; both read through one tone (§5.1). */
function tone(status: Status): Tone {
  if (status === "running") return "running";
  if (status === "waiting" || status === "awaiting_approval") return "waiting";
  if (status === "succeeded" || status === "completed") return "done";
  if (status === "failed") return "failed";
  return "idle";
}

const DOT: Record<Tone, string> = {
  running: "bg-status-running",
  waiting: "bg-status-waiting",
  done: "bg-status-done",
  failed: "bg-status-failed",
  idle: "bg-status-idle",
};

const LABEL: Record<Status, MessageKey> = {
  queued: "status.queued",
  running: "status.running",
  awaiting_approval: "status.waiting",
  waiting: "status.waiting",
  succeeded: "status.succeeded",
  completed: "status.succeeded",
  failed: "status.failed",
  cancelled: "status.cancelled",
  skipped: "status.skipped",
  expired: "status.expired",
  unknown: "common.unavailable",
};

/** A dot and a label; running pulses. `muted` de-emphasises it in a quiet row. */
export function StatusPill({ status, muted = false }: { status: Status; muted?: boolean }) {
  const { t } = useLocale();
  const shade = tone(status);
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-raised px-2.5 text-[13px] font-medium whitespace-nowrap text-ink">
      <span
        aria-hidden="true"
        className={cn("size-2 rounded-full", muted ? DOT.idle : DOT[shade], shade === "running" && !muted && "animate-pulse")}
      />
      {t(LABEL[status])}
    </span>
  );
}

/** This dashboard's label for a stage, or the server's for a stage it does not know yet. */
function stageLabel(t: (key: MessageKey) => string, stage: Stage): string {
  const key = `stage.${stage.id}`;
  return key in messages.en ? t(key as MessageKey) : stage.label;
}

/** One segment per stage, coloured by its state; a skipped stage stays dim (§7.6). */
export function SegmentedStageBar({ stages, className }: { stages: Stage[]; className?: string }) {
  const { t } = useLocale();
  const summary = stages.map((stage) => `${stageLabel(t, stage)}: ${t(LABEL[stage.status])}`).join(", ");
  return (
    <span role="img" aria-label={summary} className={cn("inline-flex gap-1", className)}>
      {stages.map((stage) => (
        <span
          key={stage.id}
          className={cn("h-1 w-7 rounded-full", DOT[tone(stage.status)], stage.status === "skipped" && "opacity-40")}
        />
      ))}
    </span>
  );
}

function seconds(from: string, to: Date): number {
  return (to.getTime() - new Date(from).getTime()) / 1_000;
}

/** The line under a stage: its current or last step, why it was skipped, or "not started". */
function stageLine(locale: "en" | "id", t: (key: MessageKey) => string, stage: Stage): string {
  if (stage.status === "skipped" && stage.skip_reason) return t(`skip.${stage.skip_reason}`);
  if (stage.current_step) {
    return stepText(locale, stage.current_step, stage.status !== "running" && stage.status !== "waiting");
  }
  if (stage.status === "queued") return t("stage.notStarted");
  return t(LABEL[stage.status]);
}

/**
 * The whole plan of a run. Vertical (run detail): every stage with its duration, or the time
 * elapsed for the current one, and a one-line step. Compact (list rows, run tray): the stage
 * bar with the current stage and its step.
 */
export function StageStepper({
  stages,
  variant = "vertical",
  now,
  label,
}: {
  stages: Stage[];
  variant?: "vertical" | "compact";
  /** The list's name for assistive tech; a run's progress by default. */
  label?: string;
  /** The caller's clock, ticking once a second while the run is live. */
  now: Date;
}) {
  const { locale, t, duration } = useLocale();
  if (variant === "compact") {
    const current =
      stages.find((stage) => ["running", "waiting", "failed"].includes(stage.status)) ?? null;
    return (
      <span className="inline-flex min-w-0 items-center gap-2.5 text-[13px] text-muted-ink">
        <SegmentedStageBar stages={stages} className="shrink-0" />
        {current && (
          <span className={cn("truncate", current.status === "waiting" && "text-status-waiting")}>
            {stageLabel(t, current)} · {stageLine(locale, t, current)}
          </span>
        )}
      </span>
    );
  }
  return (
    <ol aria-label={label ?? t("stage.progress")} className="flex flex-col">
      {stages.map((stage, index) => {
        const shade = tone(stage.status);
        const time = stage.started_at
          ? stage.finished_at
            ? duration(seconds(stage.started_at, new Date(stage.finished_at)))
            : stage.status === "running"
              ? t("stage.elapsed", { time: duration(seconds(stage.started_at, now)) })
              : null
          : null;
        return (
          <li key={stage.id} className="relative flex gap-3.5 pb-6 last:pb-0">
            {index < stages.length - 1 && (
              <span
                aria-hidden="true"
                className={cn("absolute top-5 bottom-1 left-[7px] w-0.5", shade === "done" ? DOT.done : "bg-hairline")}
              />
            )}
            <span
              aria-hidden="true"
              className={cn(
                "relative mt-1 size-4 shrink-0 rounded-full",
                stage.status === "queued" ? "border-2 border-status-idle" : DOT[shade],
                stage.status === "skipped" && "opacity-40",
                shade === "running" && "animate-pulse",
              )}
            />
            <div className="min-w-0 flex-1">
              <div className="flex items-baseline justify-between gap-3">
                <span className={cn("font-semibold text-ink", stage.status === "skipped" && "text-faint")}>
                  {stageLabel(t, stage)}
                </span>
                {time && <span className="font-mono text-[12.5px] text-muted-ink">{time}</span>}
              </div>
              <p className={cn("truncate text-sm text-muted-ink", shade === "failed" && "text-status-failed")}>
                {stageLine(locale, t, stage)}
              </p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}

const ICON = {
  info: Check,
  progress: Check,
  done: Check,
  wait: Hourglass,
  warning: TriangleAlert,
  error: CircleX,
} as const;

const ICON_TONE: Record<Step["kind"], string> = {
  info: "text-status-done",
  progress: "text-status-done",
  done: "text-status-done",
  wait: "text-status-waiting",
  warning: "text-status-waiting",
  error: "text-status-failed",
};

/**
 * One line of the activity log: time, icon, sentence, and on the right the count with its bar
 * or the countdown of a wait (§7.4). `current` marks the step the stage is on now.
 */
export function StepRow({ step, current = false, now }: { step: Step; current?: boolean; now: Date }) {
  const { locale, t, duration } = useLocale();
  const Icon = current && (step.kind === "info" || step.kind === "progress") ? LoaderCircle : ICON[step.kind];
  const time = new Intl.DateTimeFormat(locale === "id" ? "id-ID" : "en-US", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hourCycle: "h23",
  }).format(new Date(step.at));
  const left = step.wait_until ? Math.ceil(seconds(now.toISOString(), new Date(step.wait_until))) : 0;
  const counted = step.n != null && step.total != null && step.total > 0;
  return (
    <li
      className={cn(
        "flex items-center gap-4 rounded-md px-3 py-2 text-sm",
        current && "border-l-2 border-status-running bg-raised",
        step.kind === "warning" && "text-status-waiting",
        step.kind === "error" && "text-status-failed",
      )}
    >
      <time dateTime={step.at} className="w-20 shrink-0 font-mono text-[12.5px] text-faint">
        {time}
      </time>
      <Icon
        aria-hidden="true"
        className={cn("size-4 shrink-0", current ? "animate-spin text-status-running" : ICON_TONE[step.kind])}
      />
      <span className="min-w-0 flex-1 truncate text-ink">{stepText(locale, step, !current && left <= 0)}</span>
      {counted && (
        <span className="flex shrink-0 items-center gap-3 font-mono text-[12.5px] text-muted-ink">
          {step.n} / {step.total}
          <span className="h-1 w-20 overflow-hidden rounded-full bg-hairline">
            <span
              className={cn("block h-full rounded-full", current ? DOT.running : DOT.done)}
              style={{ width: `${Math.min(100, (100 * (step.n ?? 0)) / (step.total ?? 1))}%` }}
            />
          </span>
        </span>
      )}
      {left > 0 && (
        <span className="shrink-0 rounded-full bg-raised px-2.5 py-0.5 text-[12px] text-status-waiting">
          {t("step.waitNext", { time: duration(left) })}
        </span>
      )}
    </li>
  );
}
