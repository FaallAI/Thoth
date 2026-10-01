import { useEffect, useState } from "react";
import { Circle, CircleCheck, LoaderCircle, Workflow } from "lucide-react";

import type { ControlPlaneClient, WorkflowSummary } from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";

type MonitorClient = Pick<
  ControlPlaneClient,
  "streamWorkflow" | "cancelWorkflow" | "retryWorkflow" | "approveWorkflow"
>;

function workflowProgress(workflow: WorkflowSummary | null): number {
  const stages = workflow?.stages ?? [];
  if (stages.length === 0) return 0;
  const completed = stages.reduce(
    (total, stage) => total + (stage.status === "completed" ? 1 : (stage.progress ?? 0)),
    0,
  );
  return (completed / stages.length) * 100;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "The workflow action could not be completed.";
}

export function WorkflowMonitor({ workflowId, client, onSnapshot }: { workflowId: string | null; client: MonitorClient; onSnapshot?: (summary: WorkflowSummary) => void }) {
  const [workflow, setWorkflow] = useState<WorkflowSummary | null>(null);
  const [diagnostics, setDiagnostics] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);

  useEffect(() => {
    if (!workflowId) {
      setWorkflow(null);
      setActionError(null);
      return;
    }
    let live = true;
    const stop = client.streamWorkflow(workflowId, (value) => {
      if (live) { setWorkflow(value); onSnapshot?.(value); }
    });
    return () => {
      live = false;
      stop();
    };
  }, [client, workflowId, onSnapshot]);

  const applyAction = async (action: () => Promise<WorkflowSummary>) => {
    try {
      setActionError(null);
      const summary = await action();
      setWorkflow(summary);
      onSnapshot?.(summary);
    } catch (error) {
      setActionError(errorMessage(error));
    }
  };

  if (!workflowId) {
    return <Card className="workflow-monitor workflow-monitor-empty"><CardHeader><CardTitle>Live pipeline</CardTitle></CardHeader><CardContent className="text-sm text-muted-foreground"><Workflow aria-hidden="true" /><p>Start a workflow to follow its progress.</p><p>Stages, review decisions, and results will appear here.</p></CardContent></Card>;
  }

  const approval = workflow?.approval;
  const artifacts = workflow?.artifacts ?? [];
  return <div className="workflow-monitor flex flex-col gap-3">
    <Card className="pen-pipeline-card"><CardHeader><CardTitle>Live pipeline</CardTitle><span className="pen-pipeline-badge">{workflow?.status ?? "Loading"}</span></CardHeader><CardContent>
      <h2 title={workflowId}>{workflow?.source.display_url ?? `Workflow ${workflowId}`}</h2>
      <p className="pen-pipeline-progress-copy">Stage {Math.min((workflow?.stages.filter((stage) => stage.status === "completed").length ?? 0) + 1, workflow?.stages.length ?? 0)} of {workflow?.stages.length ?? 0} · {workflow?.stages.find((stage) => stage.status === "running")?.label ?? workflow?.status}</p>
      <p className="sr-only">Progress</p><Progress value={workflowProgress(workflow)} />
      <ul className="pen-pipeline-stages">{workflow?.stages.map((stage) => { const Icon = stage.status === "completed" ? CircleCheck : stage.status === "running" ? LoaderCircle : Circle; return <li key={stage.id} data-state={stage.status}><Icon aria-hidden="true" /><span>{stage.label}</span><span className="sr-only"> — {stage.status}</span></li>; })}</ul>
    </CardContent></Card>
    <details className="pen-workflow-details"><summary>Actions & results</summary><div>
      {actionError && <p role="alert" className="text-sm text-destructive">{actionError}</p>}
      <div className="flex gap-2"><Button size="sm" variant="outline" onClick={() => void applyAction(() => client.retryWorkflow(workflowId))}>Retry</Button><Button size="sm" variant="outline" onClick={() => void applyAction(() => client.cancelWorkflow(workflowId))}>Cancel</Button></div>
    </div></details>
    {approval && <Card><CardHeader><CardTitle>Needs your decision</CardTitle></CardHeader><CardContent className="space-y-2"><p>{approval.prompt}</p><div className="flex gap-2">{approval.allowed_decisions.map((decision) => <Button key={decision} size="sm" onClick={() => void applyAction(() => client.approveWorkflow(workflowId, { approval_id: approval.approval_id, decision }))}>{decision}</Button>)}</div></CardContent></Card>}
    {artifacts.length > 0 && <Card><CardHeader><CardTitle>Results</CardTitle></CardHeader><CardContent><ul className="text-sm">{artifacts.map((artifact) => <li key={artifact.artifact_id}>{artifact.label}</li>)}</ul></CardContent></Card>}
    {workflow?.failure && <Button size="sm" variant="ghost" onClick={() => setDiagnostics((shown) => !shown)}>Diagnostics</Button>}
    {diagnostics && workflow?.failure && <Card><CardContent className="py-3 text-xs">{workflow.failure.message}</CardContent></Card>}
  </div>;
}
