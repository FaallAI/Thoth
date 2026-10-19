import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router";

import type { ControlPlaneClient, Project, WorkflowRequest, WorkflowRun } from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { WorkflowWizard } from "@/components/WorkflowWizard";
import { formatWhen } from "@/lib/format-time";

type WorkflowsClient = Pick<
  ControlPlaneClient,
  "listStylePresets" | "startProjectWorkflow" | "listProjectWorkflows" | "listUnassignedWorkflows" | "moveWorkflow"
>;

const NO_PROJECT = "Select or create a project to start a workflow.";
const runStatus = (run: WorkflowRun) => (run.history_expired ? `${run.status} · history expired` : run.status);

/** The active project's runs and the runs no project owns yet (spec 2026-10-18, 4.3). */
export function WorkflowsPage({
  client,
  projectId,
  projects,
  onRuns,
}: {
  client: WorkflowsClient;
  projectId: string | null;
  projects: Project[];
  onRuns?: (runs: WorkflowRun[]) => void;
}) {
  const navigate = useNavigate();
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [next, setNext] = useState<string | null>(null);
  const [loose, setLoose] = useState<WorkflowRun[]>([]);
  const [looseNext, setLooseNext] = useState<string | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);

  useEffect(() => {
    setError("");
    if (!projectId) {
      setRuns([]);
      setNext(null);
      onRuns?.([]);
      return;
    }
    let live = true;
    client.listProjectWorkflows(projectId).then(
      (page) => {
        if (!live) return;
        setRuns(page.items);
        setNext(page.next_cursor ?? null);
        onRuns?.(page.items);
      },
      () => {
        if (live) setError("Runs could not be loaded. Try again.");
      },
    );
    return () => {
      live = false;
    };
  }, [client, projectId, reload, onRuns]);

  useEffect(() => {
    let live = true;
    client.listUnassignedWorkflows().then(
      (page) => {
        if (!live) return;
        setLoose(page.items);
        setLooseNext(page.next_cursor ?? null);
      },
      () => {
        if (live) setError("Unassigned runs could not be loaded. Try again.");
      },
    );
    return () => {
      live = false;
    };
  }, [client, reload]);

  const wizardClient = useMemo(
    () => ({
      listStylePresets: () => client.listStylePresets(),
      createWorkflow: (request: WorkflowRequest, key: string) =>
        client.startProjectWorkflow(projectId ?? "", request, key),
    }),
    [client, projectId],
  );

  const more = async () => {
    if (!projectId || !next) return;
    try {
      const page = await client.listProjectWorkflows(projectId, next);
      setRuns((current) => [...current, ...page.items]);
      setNext(page.next_cursor ?? null);
    } catch {
      setError("Runs could not be loaded. Try again.");
    }
  };
  const moreLoose = async () => {
    if (!looseNext) return;
    try {
      const page = await client.listUnassignedWorkflows(looseNext);
      setLoose((current) => [...current, ...page.items]);
      setLooseNext(page.next_cursor ?? null);
    } catch {
      setError("Unassigned runs could not be loaded. Try again.");
    }
  };
  const move = async (workflowId: string, target: string) => {
    try {
      await client.moveWorkflow(workflowId, target);
      setReload((n) => n + 1);
    } catch {
      setError("The run could not be moved. Try again.");
    }
  };
  const open = (workflowId: string) => navigate(`/workflows/${encodeURIComponent(workflowId)}`);

  return (
    <div className="dashboard-workflows">
      <WorkflowWizard client={wizardClient} onStarted={open} disabledReason={projectId ? undefined : NO_PROJECT} />
      <section className="pen-recent-runs">
        <header><h2>Runs in this project</h2></header>
        <div className="pen-runs-table">
          <table>
            <thead><tr>{["Source", "Status", "Last update", "Output"].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead>
            <tbody>
              {runs.map((run) => (
                <tr key={run.workflow_id}>
                  <td><button type="button" className="pen-run-link" onClick={() => open(run.workflow_id)}>{run.source.display_url}</button></td>
                  <td>{runStatus(run)}</td>
                  <td>{formatWhen(run.updated_at)}</td>
                  <td>{run.artifact_count ? `${run.artifact_count} artifacts` : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {!runs.length && <p className="pen-empty-runs">{projectId ? "No runs in this project yet." : NO_PROJECT}</p>}
          {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
          {next && <Button variant="outline" onClick={() => void more()}>Load more</Button>}
        </div>
      </section>
      {loose.length > 0 && (
        <details className="pen-unassigned-runs">
          <summary>{`Unassigned (${loose.length}${looseNext ? "+" : ""})`}</summary>
          <ul>
            {loose.map((run) => (
              <li key={run.workflow_id}>
                <button type="button" className="pen-run-link" onClick={() => open(run.workflow_id)}>{run.source.display_url}</button>
                <span>{runStatus(run)}</span>
                <select
                  aria-label={`Move ${run.source.display_url} to project`}
                  defaultValue=""
                  onChange={(event) => {
                    if (event.target.value) void move(run.workflow_id, event.target.value);
                  }}
                >
                  <option value="">Move to project…</option>
                  {projects.map((project) => <option key={project.project_id} value={project.project_id}>{project.name}</option>)}
                </select>
              </li>
            ))}
          </ul>
          {looseNext && <Button variant="outline" onClick={() => void moreLoose()}>Load more unassigned</Button>}
        </details>
      )}
    </div>
  );
}
