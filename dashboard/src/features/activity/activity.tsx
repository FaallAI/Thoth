// What needs the person, across every page (DESIGN §7.6, §12.3): the inbox, the active runs,
// desktop notifications for any run, and the tab title.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import type { ControlPlaneClient, Inbox, RunStatus, WorkflowRun } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";
import { notifyOnce, type RunEvent } from "@/lib/notifications";

export type ActivityClient = Pick<ControlPlaneClient, "getInbox" | "listRuns" | "getWorkflow" | "acknowledgeWorkflow">;

type Activity = {
  inbox: Inbox | null;
  /** Every active run of the caller in the workspace, newest first. */
  active: WorkflowRun[];
  waiting: number;
  /** Re-reads the inbox now: after an approve, a reject or an acknowledge (§7.6). */
  refresh: () => void;
  acknowledge: (workflowId: string) => Promise<void>;
};

const ActivityContext = createContext<Activity | null>(null);

const ACTIVE: RunStatus[] = ["queued", "running", "awaiting_approval", "unknown"];
/** The inbox at most every 15 s (§7.6: the server settles stale rows no faster). */
export const INBOX_MS = 15_000;
/** The run tray and the notifications follow active runs on this beat. */
export const ACTIVE_MS = 10_000;

type Notify = (workflowId: string, event: RunEvent, title: string, body: string) => void;

/**
 * Follows the inbox and the active runs while the page is in view, and on window focus. A run
 * that turns to waiting, or leaves the active list as done or failed, is told once as a
 * desktop notification, whichever page is open; the first read only learns what is there.
 */
export function ActivityProvider({
  client,
  children,
  notify = notifyOnce,
  inboxMs = INBOX_MS,
  activeMs = ACTIVE_MS,
}: {
  client: ActivityClient;
  children: ReactNode;
  notify?: Notify;
  inboxMs?: number;
  activeMs?: number;
}) {
  const { t } = useLocale();
  const [inbox, setInbox] = useState<Inbox | null>(null);
  const [active, setActive] = useState<WorkflowRun[]>([]);
  // ponytail: the first page of 20 active runs is followed; past that, older ones go unnoticed.
  const known = useRef<Map<string, WorkflowRun> | null>(null);

  const readInbox = useCallback(() => {
    client.getInbox().then(setInbox, () => {});
  }, [client]);

  const readActive = useCallback(async () => {
    let page: WorkflowRun[];
    try {
      page = (await client.listRuns({ projectId: null, status: ACTIVE })).items;
    } catch {
      return;
    }
    setActive(page);
    const before = known.current;
    known.current = new Map(page.map((run) => [run.workflow_id, run]));
    if (before === null) return;
    const name = (run: { title?: string | null; source: { display_url: string } }) => run.title || run.source.display_url;
    for (const run of page) {
      if (run.status === "awaiting_approval" && before.get(run.workflow_id)?.status !== "awaiting_approval") {
        notify(run.workflow_id, "waiting", t("notify.waiting"), name(run));
      }
    }
    const ended = [...before.values()].filter((run) => !known.current!.has(run.workflow_id));
    if (ended.length > 0) readInbox();
    for (const run of ended) {
      try {
        const final = await client.getWorkflow(run.workflow_id);
        if (final.status === "succeeded") notify(run.workflow_id, "done", t("notify.done"), name(run));
        if (final.status === "failed") notify(run.workflow_id, "failed", t("notify.failed"), name(run));
      } catch {
        // The run page or the inbox still shows it.
      }
    }
  }, [client, notify, readInbox, t]);

  useEffect(() => {
    readInbox();
    void readActive();
    const visible = () => document.visibilityState === "visible";
    const inboxTimer = setInterval(() => visible() && readInbox(), inboxMs);
    // Notifications matter most while the person looks elsewhere, so runs are followed then too.
    const activeTimer = setInterval(() => void readActive(), activeMs);
    const onFocus = () => {
      readInbox();
      void readActive();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      clearInterval(inboxTimer);
      clearInterval(activeTimer);
      window.removeEventListener("focus", onFocus);
    };
  }, [readInbox, readActive, inboxMs, activeMs]);

  const waiting = (inbox?.approvals?.length ?? 0) + (inbox?.failures?.length ?? 0) + (inbox?.accounts?.length ?? 0);

  useEffect(() => {
    document.title = waiting > 0 ? `(${waiting}) Thoth` : "Thoth";
  }, [waiting]);

  const acknowledge = useCallback(
    async (workflowId: string) => {
      await client.acknowledgeWorkflow(workflowId);
      readInbox();
    },
    [client, readInbox],
  );

  const value = useMemo(
    () => ({ inbox, active, waiting, refresh: readInbox, acknowledge }),
    [inbox, active, waiting, readInbox, acknowledge],
  );
  return <ActivityContext.Provider value={value}>{children}</ActivityContext.Provider>;
}

/** The activity, or null outside the signed-in shell (a lone page in a test, the login page). */
export function useActivity(): Activity | null {
  return useContext(ActivityContext);
}
