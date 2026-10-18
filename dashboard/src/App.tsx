import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams } from "react-router";
import { RunForm } from "@/components/RunForm";
import { JobList } from "@/components/JobList";
import { JobMonitor } from "@/components/JobMonitor";
import { ProfileStudio } from "@/components/ProfileStudio";
import { ProjectSwitcher } from "@/components/ProjectSwitcher";
import { Discovery } from "@/components/Discovery";
import { ContentSet } from "@/components/ContentSet";
import { GuidedStudio } from "@/features/studio/GuidedStudio";
import { StudioImportGate } from "@/features/studio/StudioImportGate";
import { StudioDocumentsPage } from "@/features/studio/StudioDocumentsPage";
import { WorkflowsPage } from "@/features/workflows/WorkflowsPage";
import { WorkflowDetailPage } from "@/features/workflows/WorkflowDetailPage";
import { SourceAccounts } from "@/components/SourceAccounts";
import { SourceProxies } from "@/components/SourceProxies";
import { sourceAccountsClient } from "@/api/source-accounts";
import { controlPlaneClient, type Project, type StudioSourceProjection, type WorkflowRun } from "@/api/control-plane";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CircleHelp, Clapperboard, Compass, Feather, KeyRound, Layers, Terminal, UserRound, Workflow } from "lucide-react";
import { DashboardSearch } from "@/components/DashboardSearch";
import { WorkspaceMenu } from "@/components/WorkspaceMenu";
import { PenDialog } from "@/components/PenDialog";
import { useActiveProject } from "@/lib/active-project";
import { documentLabel } from "@/lib/document-label";

const pages = {
  workflows: { path: "/workflows", label: "Workflows", eyebrow: "Workspace / 01", description: "Launch, track, and review your production runs.", icon: Workflow },
  discovery: { path: "/discovery", label: "Discover the next story", eyebrow: "Research / 02", description: "Turn signals into a focused production brief.", icon: Compass },
  contentset: { path: "/content-set", label: "Content Set", eyebrow: "Production / 03", description: "A source-backed brief, ready to shape in Creator Studio.", icon: Layers },
  profiles: { path: "/profiles", label: "Profiles", eyebrow: "Identity / 04", description: "Keep every production consistent with a reusable creative voice.", icon: UserRound },
  runs: { path: "/legacy", label: "Legacy Console", eyebrow: "Operations / 05", description: "Inspect jobs, review outputs, and intervene when a run needs attention.", icon: Terminal },
  studio: { path: "/studio", label: "Creator Studio", eyebrow: "Create / 06", description: "Your Studio drafts in this project.", icon: Clapperboard },
  accounts: { path: "/accounts", label: "Source Accounts", eyebrow: "Access / 07", description: "Logged-in sessions that acquisition rotates through, per platform.", icon: KeyRound },
  proxies: { path: "/accounts/proxies", label: "Proxies", eyebrow: "Access / 07", description: "Dedicated proxies for source accounts. Each proxy serves one account.", icon: KeyRound },
} as const;
type PageKey = keyof typeof pages;
const NAV: [PageKey, string][] = [
  ["workflows", "Workflows"], ["discovery", "Discovery"], ["contentset", "Content Set"], ["profiles", "Profiles"],
  ["runs", "Legacy console"], ["studio", "Creator Studio"], ["accounts", "Source Accounts"],
];

function pageFor(pathname: string): PageKey {
  if (pathname.startsWith(pages.proxies.path)) return "proxies";
  return (Object.keys(pages) as PageKey[]).find((key) => pathname.startsWith(pages[key].path)) ?? "workflows";
}

/** The router lives here rather than in main.tsx, so tests render <App /> as before (ruling P5). */
export default function App() {
  return <BrowserRouter><Shell /></BrowserRouter>;
}

function Shell() {
  const navigate = useNavigate();
  const location = useLocation();
  const [projectId, setProjectId] = useActiveProject();
  const [projects, setProjects] = useState<Project[]>([]);
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [helpOpen, setHelpOpen] = useState(false);
  // The import chooser keeps the project it was opened for, so a project switch never retargets it.
  const [studioImport, setStudioImport] = useState<{ projectId: string; source: StudioSourceProjection } | null>(null);
  const inStudio = /^\/studio\/[^/]+\/[^/]+/.test(location.pathname);
  const page = pageFor(location.pathname);
  const legacy = (location.state as { contentSet?: { path: string; forced: boolean } } | null)?.contentSet;
  const switcher = <ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} />;

  const needsProject = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>Select or create a project to begin.</p>
      <p className="text-xs">Use “New project” at the top right.</p>
    </div>
  );

  return (
    <div data-page={inStudio ? "studio" : page} className={`dashboard-shell ${inStudio ? "dashboard-shell--studio" : ""}`}>
      <a className="dashboard-skip" href="#workspace">Skip to workspace</a>
      <header className="dashboard-topbar" hidden={inStudio}>
        <div className="dashboard-brand"><Feather aria-hidden="true" /><span>Thoth</span></div>
        <span className="dashboard-brand-caption">Creator platform</span>
        <div className="dashboard-header-tools">
          <DashboardSearch projects={projects} workflows={runs} onWorkflow={(id) => navigate(`/workflows/${encodeURIComponent(id)}`)} onProject={setProjectId} onNavigate={(path) => navigate(path)} />
          <div className="dashboard-project">{switcher}</div>
          <WorkspaceMenu onProfiles={() => navigate("/profiles")} onHelp={() => setHelpOpen(true)} />
        </div>
      </header>
      <div className="dashboard-body">
        <nav className="dashboard-sidebar" aria-label="Workspace">
          <p className="dashboard-nav-label">Workspace</p>
          {NAV.map(([id, label]) => {
            const Icon = pages[id].icon;
            const current = page === id || (id === "accounts" && page === "proxies") || (id === "studio" && inStudio);
            return <div key={id} className={id === "runs" ? "dashboard-tools-start" : undefined}>
              {id === "runs" && <p className="dashboard-nav-label">Tools</p>}
              <NavLink to={pages[id].path} className={cn(buttonVariants({ variant: "ghost" }), "dashboard-nav-item")} aria-current={current ? "page" : undefined}>
                <Icon aria-hidden="true" /><span>{label}</span>
              </NavLink>
            </div>;
          })}
          <div className="dashboard-sidebar-footer"><button type="button" onClick={() => setHelpOpen(true)}><CircleHelp aria-hidden="true" />Help & documentation</button></div>
        </nav>
        <main id="workspace" tabIndex={-1} className={`dashboard-main dashboard-page-${page}`}>
          {!inStudio && <header className="dashboard-page-heading"><div>
            <p className="dashboard-eyebrow">{pages[page].eyebrow}</p>
            <h1>{pages[page].label}</h1>
            <p>{pages[page].description}</p>
          </div><div id="dashboard-page-actions" className="pen-page-actions" /></header>}
          <Routes>
            <Route path="/" element={<Navigate to="/workflows" replace />} />
            <Route path="/workflows" element={<WorkflowsPage client={controlPlaneClient} projectId={projectId} projects={projects} onRuns={setRuns} />} />
            <Route path="/workflows/:workflowId" element={<WorkflowDetailRoute />} />
            <Route path="/discovery" element={<Discovery />} />
            <Route path="/content-set" element={<ContentSet projectId={projectId}
              onSendToRender={(path, forced) => navigate("/legacy", { state: { contentSet: { path, forced } } })}
              onOpenInStudio={(source) => { if (projectId) setStudioImport({ projectId, source }); }} />} />
            <Route path="/profiles" element={projectId ? <div className="dashboard-profile-region"><ProfileStudio projectId={projectId} onProfileChanged={() => {}} /></div> : needsProject} />
            <Route path="/legacy" element={projectId ? <>
              <div id="dashboard-legacy-metrics" />
              <RunForm projectId={projectId} onCreated={setSelectedJobId} initialContentSet={legacy?.path} initialContentSetForced={legacy?.forced}
                onConsumed={() => navigate("/legacy", { replace: true, state: null })} />
              <div className="dashboard-legacy-columns">
                <div className="dashboard-job-list"><JobList selectedId={selectedJobId} onSelect={setSelectedJobId} /></div>
                <div className="min-h-0 min-w-0 flex-1"><JobMonitor jobId={selectedJobId} /></div>
              </div>
            </> : needsProject} />
            <Route path="/studio" element={projectId ? <StudioDocumentsPage client={controlPlaneClient} projectId={projectId} /> : needsProject} />
            <Route path="/studio/:projectId/:documentId" element={<StudioDocumentRoute workspaceControls={switcher} projects={projects} />} />
            <Route path="/accounts" element={<SourceAccounts client={sourceAccountsClient} onManageProxies={() => navigate("/accounts/proxies")} />} />
            <Route path="/accounts/proxies" element={<SourceProxies client={sourceAccountsClient} onBack={() => navigate("/accounts")} />} />
            <Route path="*" element={<Navigate to="/workflows" replace />} />
          </Routes>
        </main>
      </div>
      <PenDialog open={helpOpen} onOpenChange={setHelpOpen} title="Help & shortcuts" description="Your local production workspace."><div className="pen-help-body"><h3>Production flow</h3><p>Start a workflow from a source, open its result in Creator Studio, and render. Use Profiles for reusable production settings and Legacy Console for operational job logs.</p><h3>Keyboard</h3><p>Tab moves between controls. Escape closes dialogs and menus. Space plays or pauses the Studio preview.</p><p>Provider availability and supported operations depend on your configured server.</p></div></PenDialog>
      {studioImport ? (
        <StudioImportGate
          client={controlPlaneClient}
          projectId={studioImport.projectId}
          source={studioImport.source}
          onClose={() => setStudioImport(null)}
          onOpen={(documentId) => {
            const target = studioImport.projectId;
            setStudioImport(null);
            navigate(`/studio/${encodeURIComponent(target)}/${encodeURIComponent(documentId)}`);
          }}
        />
      ) : null}
    </div>
  );
}

function WorkflowDetailRoute() {
  const { workflowId = "" } = useParams();
  return <WorkflowDetailPage client={controlPlaneClient} workflowId={workflowId} />;
}

/** Studio from its URL alone; "Resolve source items" opens the gate without a Content Set. */
function StudioDocumentRoute({ workspaceControls, projects }: { workspaceControls: ReactNode; projects: Project[] }) {
  const { projectId = "", documentId = "" } = useParams();
  const navigate = useNavigate();
  // `opened` rises on every return from the gate, so Studio reloads the revision decisions saved.
  const [opened, setOpened] = useState(0);
  const [resolving, setResolving] = useState(false);
  const [title, setTitle] = useState<string>();
  useEffect(() => {
    let live = true;
    controlPlaneClient.getEditDocument(projectId, documentId).then(
      (document) => { if (live) setTitle(documentLabel(document)); },
      () => {},
    );
    return () => { live = false; };
  }, [projectId, documentId, opened]);
  const reopen = () => {
    setResolving(false);
    setOpened((n) => n + 1);
  };
  return (
    <>
      <GuidedStudio
        key={`${documentId}:${opened}`}
        client={controlPlaneClient}
        projectId={projectId}
        documentId={documentId}
        documentTitle={title}
        projectName={projects.find((project) => project.project_id === projectId)?.name}
        workspaceControls={workspaceControls}
        onBack={() => navigate("/studio")}
        onResolveImports={() => setResolving(true)}
      />
      {resolving ? (
        <StudioImportGate client={controlPlaneClient} projectId={projectId} resumeDocumentId={documentId} onClose={reopen} onOpen={reopen} />
      ) : null}
    </>
  );
}
