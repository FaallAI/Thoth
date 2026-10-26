// One open run, polled every second until it ends (DESIGN §7.6), and the reports it wrote.
import { useEffect, useState } from "react";

import type { ArtifactRef, ControlPlaneClient, WorkflowStep, WorkflowSummary } from "@/api/control-plane";

export type RunClient = Pick<ControlPlaneClient, "getWorkflow" | "listWorkflowSteps" | "downloadWorkflowArtifact">;

const TERMINAL = new Set(["succeeded", "failed", "cancelled"]);
export const POLL_MS = 1_000;

export function finished(summary: WorkflowSummary | null): boolean {
  return summary !== null && (TERMINAL.has(summary.status) || Boolean(summary.history_expired));
}

/**
 * The run's snapshot and its steps. Steps come in pages after the last seen `seq`, so a poll
 * reads only what is new. Once the run ends, one last read settles it and polling stops. The
 * page is keyed by the run, so another run starts from empty state.
 */
export function useRun(client: RunClient, workflowId: string) {
  const [summary, setSummary] = useState<WorkflowSummary | null>(null);
  const [steps, setSteps] = useState<WorkflowStep[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    let after = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      let done = false;
      try {
        const [next, page] = await Promise.all([client.getWorkflow(workflowId), client.listWorkflowSteps(workflowId, after)]);
        if (!live) return;
        setSummary(next);
        setFailed(false);
        if (page.steps.length > 0) {
          after = page.steps[page.steps.length - 1].seq;
          setSteps((current) => [...current, ...page.steps]);
        }
        done = finished(next);
      } catch {
        if (live) setFailed(true);
      }
      if (live && !done) timer = setTimeout(() => void poll(), POLL_MS);
    };
    void poll();
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [client, workflowId]);

  /** Lets an action (approve, cancel) show its answer before the next poll. */
  return { summary, steps, failed, setSummary };
}

/** A JSON report the run wrote, read once when it appears among the run's artifacts. */
export function useReport<T>(client: RunClient, workflowId: string, artifact: ArtifactRef | undefined): T | null | "error" {
  const [report, setReport] = useState<T | null | "error">(null);
  const id = artifact?.artifact_id;
  useEffect(() => {
    if (!id) return;
    let live = true;
    client
      .downloadWorkflowArtifact(workflowId, id)
      .then((blob) => blob.text())
      .then(
        (text) => live && setReport(JSON.parse(text) as T),
        () => live && setReport("error"),
      );
    return () => {
      live = false;
    };
  }, [client, workflowId, id]);
  return report;
}
