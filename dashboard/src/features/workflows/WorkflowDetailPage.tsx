import { useCallback, useState } from "react";

import type { ControlPlaneClient, WorkflowSummary } from "@/api/control-plane";
import { WorkflowMonitor } from "@/components/WorkflowMonitor";

import { OpenInStudio, type OpenInStudioClient } from "./OpenInStudio";

type DetailClient = Pick<
  ControlPlaneClient,
  "streamWorkflow" | "cancelWorkflow" | "retryWorkflow" | "approveWorkflow" | "downloadWorkflowArtifact"
> &
  OpenInStudioClient;

/** One workflow by URL: its monitor, decisions, downloadable results, and the way into Studio. */
export function WorkflowDetailPage({
  client,
  workflowId,
  projectId = null,
  onOpenStudio = () => {},
}: {
  client: DetailClient;
  workflowId: string;
  projectId?: string | null;
  onOpenStudio?: (projectId: string, documentId: string, resolve: boolean) => void;
}) {
  const [summary, setSummary] = useState<WorkflowSummary | null>(null);
  // Stable, so the monitor's stream is not reopened on every snapshot.
  const onSnapshot = useCallback((value: WorkflowSummary) => setSummary(value), []);
  return (
    <div className="dashboard-workflows">
      <OpenInStudio client={client} projectId={projectId} workflowId={workflowId} summary={summary} onOpen={onOpenStudio} />
      <WorkflowMonitor workflowId={workflowId} client={client} onSnapshot={onSnapshot} />
    </div>
  );
}
