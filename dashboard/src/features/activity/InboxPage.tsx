// Inbox (DESIGN §8.7): approvals, failed runs and accounts, each with one action.
import { Link } from "react-router";
import { useState, type ReactNode } from "react";

import type { InboxRun, Project } from "@/api/control-plane";
import { EmptyState, Skeleton } from "@/components/Feedback";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Button } from "@/components/ui/button";
import { useLocale } from "@/lib/locale";
import { PLATFORM_NAMES } from "@/lib/platforms";

import { useActivity } from "./activity";

function Group({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-base font-semibold text-ink">{title}</h2>
      <ul className="flex flex-col divide-y divide-hairline rounded-[10px] bg-surface">{children}</ul>
    </section>
  );
}

function Row({ lead, title, detail, action }: { lead: ReactNode; title: ReactNode; detail: string; action: ReactNode }) {
  return (
    <li className="flex flex-wrap items-center gap-4 px-5 py-4">
      <span className="grid size-10 shrink-0 place-items-center rounded-md bg-well text-muted-ink">{lead}</span>
      <div className="min-w-0 flex-1">
        <p className="truncate text-[15px] text-ink">{title}</p>
        <p className="text-sm text-muted-ink">{detail}</p>
      </div>
      {action}
    </li>
  );
}

export function InboxPage({ projects }: { projects: Project[] }) {
  const activity = useActivity();
  const { t, day } = useLocale();
  const [failed, setFailed] = useState(false);
  if (!activity) return null;
  const inbox = activity.inbox;
  if (inbox === null) return <Skeleton rows={4} />;
  const approvals = inbox.approvals ?? [];
  const failures = inbox.failures ?? [];
  const accounts = inbox.accounts ?? [];
  const project = (run: InboxRun) => projects.find((item) => item.project_id === run.project_id)?.name ?? t("inbox.noProject");
  const title = (run: InboxRun) => run.title || run.display_url;
  const open = (run: InboxRun, label: string, primary = false) => (
    <Link
      to={`/workflows/${encodeURIComponent(run.workflow_id)}`}
      className={primary ? "rounded-md bg-copper px-3 py-2 text-sm font-medium text-[#1b1918]" : "rounded-md bg-raised px-3 py-2 text-sm text-ink"}
    >
      {label}
    </Link>
  );
  const acknowledge = async (workflowId: string) => {
    setFailed(false);
    try {
      await activity.acknowledge(workflowId);
    } catch {
      setFailed(true);
    }
  };

  if (approvals.length + failures.length + accounts.length === 0) return <EmptyState>{t("inbox.empty")}</EmptyState>;
  return (
    <div className="flex max-w-[1200px] flex-col gap-8">
      {failed && (
        <p role="alert" className="text-sm text-status-failed">
          {t("inbox.ackFailed")}
        </p>
      )}
      {approvals.length > 0 && (
        <Group title={t("inbox.approvals")}>
          {approvals.map((run) => (
            <Row
              key={run.workflow_id}
              lead={<PlatformIcon platform={run.platform} />}
              title={title(run)}
              detail={`${project(run)} · ${t("inbox.waitingSince", { time: day(run.updated_at) })}`}
              action={open(run, t("inbox.review"), true)}
            />
          ))}
        </Group>
      )}
      {failures.length > 0 && (
        <Group title={t("inbox.failures")}>
          {failures.map((run) => (
            <Row
              key={run.workflow_id}
              lead={<PlatformIcon platform={run.platform} />}
              title={<Link to={`/workflows/${encodeURIComponent(run.workflow_id)}`} className="hover:underline">{title(run)}</Link>}
              detail={`${project(run)} · ${t("inbox.failedAt", { time: day(run.updated_at) })}`}
              action={
                <Button variant="secondary" onClick={() => void acknowledge(run.workflow_id)}>
                  {t("inbox.acknowledge")}
                </Button>
              }
            />
          ))}
        </Group>
      )}
      {accounts.length > 0 && (
        <Group title={t("inbox.accounts")}>
          {accounts.map((account) => (
            <Row
              key={account.account_id}
              lead={<PlatformIcon platform={account.platform} />}
              title={`${account.label} · ${PLATFORM_NAMES[account.platform] ?? account.platform}`}
              detail={
                account.status === "cooldown" && account.cooldown_until
                  ? t("inbox.cooldown", { time: day(account.cooldown_until) })
                  : account.status === "expired"
                    ? t("inbox.expired")
                    : t("inbox.attention")
              }
              action={
                <Link to="/accounts" className="rounded-md bg-raised px-3 py-2 text-sm text-ink">
                  {t("inbox.openAccounts")}
                </Link>
              }
            />
          ))}
        </Group>
      )}
    </div>
  );
}
