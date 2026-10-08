import { useCallback, useState } from "react";
import { RunForm } from "@/components/RunForm";
import { JobList } from "@/components/JobList";
import { JobMonitor } from "@/components/JobMonitor";
import { ProfileStudio } from "@/components/ProfileStudio";
import { ProjectSwitcher } from "@/components/ProjectSwitcher";
import { Discovery } from "@/components/Discovery";
import { ContentSet } from "@/components/ContentSet";
import { GuidedStudio } from "@/features/studio/GuidedStudio";
import { StudioImportGate } from "@/features/studio/StudioImportGate";
import { WorkflowMonitor } from "@/components/WorkflowMonitor";
import { WorkflowWizard } from "@/components/WorkflowWizard";
import { SourceAccounts } from "@/components/SourceAccounts";
import { SourceProxies } from "@/components/SourceProxies";
import { sourceAccountsClient } from "@/api/source-accounts";
import { controlPlaneClient, type StudioSourceProjection, type WorkflowSummary } from "@/api/control-plane";
import type { ProjectRecord } from "@/api";
import { Button } from "@/components/ui/button";
import { ArrowRight, CircleHelp, Clapperboard, Compass, Feather, KeyRound, Layers, Plus, Terminal, UserRound, Workflow } from "lucide-react";
import { DashboardSearch } from "@/components/DashboardSearch";
import { WorkspaceMenu } from "@/components/WorkspaceMenu";
import { PenDialog } from "@/components/PenDialog";
import { WorkflowDraftDialog, type LocalWorkflowDraft } from "@/components/WorkflowDraftDialog";

const pages = {
  workflows: { label: "Workflows", eyebrow: "Workspace / 01", description: "Launch, track, and review your video production pipeline.", icon: Workflow },
  discovery: { label: "Discover the next story", eyebrow: "Research / 02", description: "Turn signals into a focused production brief.", icon: Compass },
  contentset: { label: "Content Set", eyebrow: "Production / 03", description: "A source-backed brief, ready to shape in Creator Studio.", icon: Layers },
  profiles: { label: "Profiles", eyebrow: "Identity / 04", description: "Keep every production consistent with a reusable creative voice.", icon: UserRound },
  runs: { label: "Legacy Console", eyebrow: "Operations / 05", description: "Inspect jobs, review outputs, and intervene when a run needs attention.", icon: Terminal },
  studio: { label: "Creator Studio", eyebrow: "Create / 06", description: "Shape your story, one scene at a time.", icon: Clapperboard },
  accounts: { label: "Source Accounts", eyebrow: "Access / 07", description: "Logged-in sessions that acquisition rotates through, per platform.", icon: KeyRound },
  proxies: { label: "Proxies", eyebrow: "Access / 07", description: "Dedicated proxies for source accounts. Each proxy serves one account.", icon: KeyRound },
};

/** Cockpit shell with a Runs/Profiles/Discovery/Content Set view toggle,
 *  scoped to the active project chosen in the ProjectSwitcher. */
export default function App() {
  const [projectId, setProjectId] = useState<string | null>(null);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [view, setView] = useState<keyof typeof pages>("workflows");
  const [workflowId, setWorkflowId] = useState<string | null>(null);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [newWorkflowOpen, setNewWorkflowOpen] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [recentRunsOpen, setRecentRunsOpen] = useState(false);
  const [localDraft, setLocalDraft] = useState<LocalWorkflowDraft | null>(null);
  const [recentWorkflows, setRecentWorkflows] = useState<WorkflowSummary[]>([]);
  const rememberWorkflow = useCallback((summary: WorkflowSummary) => {
    setRecentWorkflows((current) => [summary, ...current.filter((entry) => entry.workflow_id !== summary.workflow_id)]);
  }, []);
  const projectName = projects.find((project) => project.id === projectId)?.name ?? "";
  // Sub-project D: one-shot content-set path handed from the Content-Set view to
  // RunForm (cleared by RunForm.onConsumed once consumed on mount).
  const [pendingContentSet, setPendingContentSet] = useState<{
    path: string;
    forced: boolean;
  } | null>(null);
  // `opened` rises on every entry, so Studio reloads the revision the import decisions just saved.
  const [studioDocument, setStudioDocument] = useState<{
    projectId: string;
    documentId: string;
    source: StudioSourceProjection;
    opened: number;
  } | null>(null);
  // The import chooser keeps the project it was opened for, so a project switch never retargets it.
  const [studioImport, setStudioImport] = useState<{
    projectId: string;
    source: StudioSourceProjection;
    resumeDocumentId?: string;
  } | null>(null);
  const handleSendToRender = (path: string, forced: boolean) => {
    setPendingContentSet({ path, forced });
    setView("runs");
  };
  const handleOpenInStudio = (source: StudioSourceProjection) => {
    if (projectId) setStudioImport({ projectId, source });
  };
  const openStudio = (documentId: string) => {
    if (!studioImport) return;
    const { projectId: importProjectId, source } = studioImport;
    setStudioDocument((current) => ({ projectId: importProjectId, documentId, source, opened: (current?.opened ?? 0) + 1 }));
    setStudioImport(null);
    setView("studio");
  };

  const needsProject = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>Select or create a project to begin.</p>
      <p className="text-xs">Use “New project” at the top right.</p>
    </div>
  );

  return (
    <div data-page={view} className={`dashboard-shell ${view === "studio" ? "dashboard-shell--studio" : ""}`}>
      <a className="dashboard-skip" href="#workspace">Skip to workspace</a>
      <header className="dashboard-topbar" hidden={view === "studio"}>
        <div className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></div>
        <span className="dashboard-brand-caption">Creator platform</span>
        <div className="dashboard-header-tools">
          <DashboardSearch projects={projects} workflows={recentWorkflows} onWorkflow={(id) => { setWorkflowId(id); setView("workflows"); }} onProject={setProjectId} onNavigate={setView} />
          <div className="dashboard-project"><ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} /></div>
          <WorkspaceMenu onProfiles={() => setView("profiles")} onHelp={() => setHelpOpen(true)} />
        </div>
      </header>
      <div className="dashboard-body">
        <nav className="dashboard-sidebar" aria-label="Workspace">
          <p className="dashboard-nav-label">Workspace</p>
          {([
            ["workflows", "Workflows"], ["discovery", "Discovery"],
            ["contentset", "Content Set"], ["profiles", "Profiles"],
            ["runs", "Legacy console"], ["studio", "Creator Studio"], ["accounts", "Source Accounts"],
          ] as const).map(([id, label]) => {
            const Icon = pages[id].icon;
            return <div key={id} className={id === "runs" ? "dashboard-tools-start" : undefined}>
              {id === "runs" && <p className="dashboard-nav-label">Tools</p>}
              <Button className="dashboard-nav-item" variant="ghost" aria-current={view === id || (id === "accounts" && view === "proxies") ? "page" : undefined}
                onClick={() => setView(id === "studio" && !studioDocument ? "contentset" : id)}>
                <Icon aria-hidden="true" /><span>{label}</span>
              </Button>
            </div>;
          })}
          <div className="dashboard-sidebar-footer"><button type="button" onClick={() => setHelpOpen(true)}><CircleHelp aria-hidden="true" />Help & documentation</button></div>
        </nav>
        <main id="workspace" tabIndex={-1} className={`dashboard-main dashboard-page-${view}`}>
          {view !== "studio" && <header className="dashboard-page-heading"><div>
            <p className="dashboard-eyebrow">{pages[view].eyebrow}</p>
            <h1>{pages[view].label}</h1>
            <p>{pages[view].description}</p>
          </div><div id="dashboard-page-actions" className="pen-page-actions">{view === "workflows" && <Button onClick={() => setNewWorkflowOpen(true)}><Plus aria-hidden="true" />New workflow</Button>}</div></header>}
      {view === "workflows" ? (
        <div className="dashboard-workflows">
          <div className="pen-workflow-metrics" aria-label="Workflow metrics" title="Aggregate workflow statistics are not provided by this server.">
            {[["Active runs", "Running workflows", "cyan"], ["Awaiting review", "Decisions pending", "copper"], ["Completed this week", "Weekly total unavailable", "gold"], ["Success rate", "Last 30 days", "purple"]].map(([label, hint, color]) => <div key={label}><p>{label}</p><strong>—<i className={`pen-dot-${color}`} aria-hidden="true" /></strong><small>{hint}</small></div>)}
          </div>
          {localDraft && <div className="pen-local-draft" role="status"><strong>{localDraft.name}</strong><span>Local {localDraft.startingPoint} draft · {localDraft.firstStep || "Source → Script → Media → Render"}</span><small>{localDraft.startingPoint === "blank" ? "Custom stage execution is unavailable. This draft is kept in this session only." : "This draft is kept in this session only. Add a source below to run the existing pipeline."}</small><button type="button" onClick={() => setLocalDraft(null)}>Close draft</button></div>}
          <div className="dashboard-workflow-columns">
          <WorkflowWizard client={controlPlaneClient} onStarted={setWorkflowId} disabledReason={localDraft?.startingPoint === "blank" ? "Custom stage execution is not available on this server." : undefined} />
          <WorkflowMonitor workflowId={workflowId} client={controlPlaneClient} onSnapshot={rememberWorkflow} />
          </div>
          <section className="pen-recent-runs"><header><h2>Recent runs</h2><button type="button" onClick={() => setRecentRunsOpen(true)}>View all<ArrowRight aria-hidden="true" /></button></header>
            <div id="recent-workflows" tabIndex={-1} className="pen-runs-table"><table><thead><tr>{['Project', 'Source', 'Status', 'Last update', 'Output'].map((heading) => <th key={heading}>{heading}</th>)}</tr></thead><tbody>{recentWorkflows.map((entry) => <tr key={entry.workflow_id}><td>—</td><td>{entry.source.display_url}</td><td>{entry.status}</td><td>{entry.updated_at}</td><td>{entry.artifacts?.length ? `${entry.artifacts.length} artifacts` : '—'}</td></tr>)}</tbody></table>{!recentWorkflows.length && <p className="pen-empty-runs">Runs tracked in this session will appear here.</p>}</div>
          </section>
        </div>
      ) : view === "profiles" ? (
        projectId ? (
          <div className="dashboard-profile-region">
            <ProfileStudio projectId={projectId} onProfileChanged={() => {}} />
          </div>
        ) : (
          needsProject
        )
      ) : view === "discovery" ? (
        <Discovery />
      ) : view === "contentset" ? (
        <ContentSet
          onSendToRender={handleSendToRender}
          projectId={projectId}
          onOpenInStudio={handleOpenInStudio}
        />
      ) : view === "accounts" ? (
        <SourceAccounts client={sourceAccountsClient} onManageProxies={() => setView("proxies")} />
      ) : view === "proxies" ? (
        <SourceProxies client={sourceAccountsClient} onBack={() => setView("accounts")} />
      ) : view === "studio" && studioDocument ? (
        <GuidedStudio
          key={`${studioDocument.documentId}:${studioDocument.opened}`}
          client={controlPlaneClient}
          projectId={studioDocument.projectId}
          documentId={studioDocument.documentId}
          documentTitle={studioDocument.source.items.find((item) => item.role === "main")?.title ?? undefined}
          projectName={projects.find((project) => project.id === studioDocument.projectId)?.name}
          workspaceControls={<ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} />}
          onBack={() => setView("contentset")}
          onResolveImports={() =>
            setStudioImport({
              projectId: studioDocument.projectId,
              source: studioDocument.source,
              resumeDocumentId: studioDocument.documentId,
            })
          }
        />
      ) : projectId ? (
        <>
          <div id="dashboard-legacy-metrics" />
          <RunForm
            projectId={projectId}
            onCreated={setSelectedJobId}
            initialContentSet={pendingContentSet?.path}
            initialContentSetForced={pendingContentSet?.forced}
            onConsumed={() => setPendingContentSet(null)}
          />
          <div className="dashboard-legacy-columns">
            <div className="dashboard-job-list">
              <JobList selectedId={selectedJobId} onSelect={setSelectedJobId} />
            </div>
            <div className="min-h-0 min-w-0 flex-1">
              <JobMonitor jobId={selectedJobId} />
            </div>
          </div>
        </>
      ) : (
        needsProject
      )}
        </main>
      </div>
      <WorkflowDraftDialog open={newWorkflowOpen} onOpenChange={setNewWorkflowOpen} projectName={projectName} onCreate={setLocalDraft} />
      <PenDialog open={recentRunsOpen} onOpenChange={setRecentRunsOpen} title="Recent runs" description="Workflows tracked during this session."><div className="pen-managed-projects">{recentWorkflows.length ? recentWorkflows.map((run) => <button type="button" key={run.workflow_id} onClick={() => { setWorkflowId(run.workflow_id); setView("workflows"); setRecentRunsOpen(false); }}><Workflow aria-hidden="true" /><span>{run.source.display_url}</span><small>{run.status}</small></button>) : <p>No workflows have been tracked in this session.</p>}</div></PenDialog>
      <PenDialog open={helpOpen} onOpenChange={setHelpOpen} title="Help & shortcuts" description="Your local production workspace."><div className="pen-help-body"><h3>Production flow</h3><p>Discover a source, prepare the Content Set, and open it in Creator Studio. Use Profiles for reusable production settings and Legacy Console for operational job logs.</p><h3>Keyboard</h3><p>Tab moves between controls. Escape closes dialogs and menus. Space plays or pauses the Studio preview.</p><p>Provider availability and supported operations depend on your configured server.</p></div></PenDialog>
      {studioImport ? (
        <StudioImportGate
          client={controlPlaneClient}
          projectId={studioImport.projectId}
          source={studioImport.source}
          resumeDocumentId={studioImport.resumeDocumentId}
          onClose={() => {
            setStudioImport(null);
            // Decisions made before closing saved a new revision: reload Studio onto it.
            if (studioImport.resumeDocumentId) openStudio(studioImport.resumeDocumentId);
          }}
          onOpen={openStudio}
        />
      ) : null}
    </div>
  );
}
