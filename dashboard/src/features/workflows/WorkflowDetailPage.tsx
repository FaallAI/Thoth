import type { ControlPlaneClient } from "@/api/control-plane";
import { WorkflowMonitor } from "@/components/WorkflowMonitor";

type DetailClient = Pick<
  ControlPlaneClient,
  "streamWorkflow" | "cancelWorkflow" | "retryWorkflow" | "approveWorkflow" | "downloadWorkflowArtifact"
>;

/** One workflow by URL: its monitor, decisions, and downloadable results. */
export function WorkflowDetailPage({ client, workflowId }: { client: DetailClient; workflowId: string }) {
  return (
    <div className="dashboard-workflows">
      <WorkflowMonitor workflowId={workflowId} client={client} />
    </div>
  );
}
