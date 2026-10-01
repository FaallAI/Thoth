import { useState } from "react";
import { Compass, FolderOpen, Search, UserRound, Workflow } from "lucide-react";
import type { ProjectRecord } from "@/api";
import type { WorkflowSummary } from "@/api/control-plane";
import { PenDialog } from "./PenDialog";

export function DashboardSearch({ projects, workflows = [], onWorkflow, onProject, onNavigate }: {
  projects: ProjectRecord[];
  workflows?: WorkflowSummary[];
  onWorkflow?: (id: string) => void;
  onProject: (id: string) => void;
  onNavigate: (view: "workflows" | "profiles" | "discovery") => void;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const matches = (value: string) => value.toLowerCase().includes(query.trim().toLowerCase());
  return <>
    <button type="button" className="pen-search-trigger" onClick={() => setOpen(true)}><Search aria-hidden="true" /><span>Search projects, workflows…</span></button>
    <PenDialog open={open} onOpenChange={setOpen} title="Search workspace" className="pen-search-dialog">
      <div className="pen-search-field"><Search aria-hidden="true" /><input aria-label="Search workspace" placeholder="Search projects, workflows, profiles…" value={query} onChange={(event) => setQuery(event.target.value)} autoFocus /><button type="button" onClick={() => setOpen(false)}>ESC</button></div>
      <div className="pen-search-results"><p>Workspace</p>
        {workflows.filter((run) => matches(run.source.display_url)).map((run) => <button type="button" key={run.workflow_id} onClick={() => { onWorkflow?.(run.workflow_id); setOpen(false); }}><Workflow aria-hidden="true" /><span>{run.source.display_url}</span><small>{run.status}</small></button>)}
        {projects.filter((project) => matches(project.name)).map((project) => <button type="button" key={project.id} onClick={() => { onProject(project.id); setOpen(false); }}><FolderOpen aria-hidden="true" /><span>{project.name}</span><small>Project</small></button>)}
        {([['workflows', 'From source to finished cut', Workflow, 'Workflow'], ['profiles', 'Creator profiles', UserRound, 'Profiles'], ['discovery', 'Discovery', Compass, 'Research']] as const).filter(([, label]) => matches(label)).map(([view, label, Icon, kind]) => <button type="button" key={view} onClick={() => { onNavigate(view); setOpen(false); }}><Icon aria-hidden="true" /><span>{label}</span><small>{kind}</small></button>)}
        {query && !workflows.some((run) => matches(run.source.display_url)) && !projects.some((project) => matches(project.name)) && !['From source to finished cut', 'Creator profiles', 'Discovery'].some(matches) && <div className="pen-search-empty">No matching workspace items.</div>}
      </div>
      <footer className="pen-search-footer">Select a result to open it<span>Esc to close</span></footer>
    </PenDialog>
  </>;
}
