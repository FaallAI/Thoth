import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
import { ProjectSwitcher } from "@/components/ProjectSwitcher";
import { GuidedStudio } from "@/features/studio/GuidedStudio";
import { StudioImportGate } from "@/features/studio/StudioImportGate";
import { StudioDocumentsPage } from "@/features/studio/StudioDocumentsPage";
import { WorkflowsPage } from "@/features/workflows/WorkflowsPage";
import { WorkflowDetailPage } from "@/features/workflows/WorkflowDetailPage";
import { SourceAccounts } from "@/components/SourceAccounts";
import { SourceProxies } from "@/components/SourceProxies";
import { sourceAccountsClient } from "@/api/source-accounts";
import { controlPlaneClient, type Project, type WorkflowRun } from "@/api/control-plane";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { CircleHelp, Clapperboard, CreditCard, Feather, Gauge, KeyRound, Workflow } from "lucide-react";
import { DashboardSearch } from "@/components/DashboardSearch";
import { WorkspaceMenu } from "@/components/WorkspaceMenu";
import { PenDialog } from "@/components/PenDialog";
import { authClient } from "@/api/auth";
import { AuthGate } from "@/features/auth/AuthGate";
import { useAuth } from "@/features/auth/auth-context";
import { TokensPage } from "@/features/settings/TokensPage";
import { UsagePage } from "@/features/usage/UsagePage";
import { BillingPage } from "@/features/billing/BillingPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { VerifyPage } from "@/features/auth/VerifyPage";
import { useActiveProject } from "@/lib/active-project";
import { LocaleProvider } from "@/lib/locale";
import { documentLabel } from "@/lib/document-label";

const pages = {
  workflows: { path: "/workflows", label: "Workflows", eyebrow: "Workspace / 01", description: "Launch, track, and review your production runs.", icon: Workflow },
  studio: { path: "/studio", label: "Creator Studio", eyebrow: "Create / 02", description: "Your Studio drafts in this project.", icon: Clapperboard },
  usage: { path: "/usage", label: "Usage", eyebrow: "Workspace / 03", description: "What this workspace used this month, and today's source-account sessions.", icon: Gauge },
  billing: { path: "/billing", label: "Billing", eyebrow: "Workspace / 04", description: "Your plan, what is left this period, and payments.", icon: CreditCard },
  accounts: { path: "/accounts", label: "Source Accounts", eyebrow: "Access / 03", description: "Logged-in sessions that acquisition rotates through, per platform.", icon: KeyRound },
  tokens: { path: "/settings/tokens", label: "Developer tokens", eyebrow: "Access / 03", description: "Personal tokens for the API and the CLI. Each token is shown once.", icon: KeyRound },
  proxies: { path: "/accounts/proxies", label: "Proxies", eyebrow: "Access / 03", description: "Dedicated proxies for source accounts. Each proxy serves one account.", icon: KeyRound },
} as const;
type PageKey = keyof typeof pages;
const NAV: [PageKey, string][] = [
  ["workflows", "Workflows"], ["studio", "Creator Studio"], ["usage", "Usage"], ["billing", "Billing"], ["accounts", "Source Accounts"],
];

function pageFor(pathname: string): PageKey {
  if (pathname.startsWith(pages.proxies.path)) return "proxies";
  if (pathname.startsWith(pages.tokens.path)) return "tokens";
  return (Object.keys(pages) as PageKey[]).find((key) => pathname.startsWith(pages[key].path)) ?? "workflows";
}

/** The router lives here rather than in main.tsx, so tests render <App /> as before (ruling P5). */
export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LocaleProvider><LoginPage /></LocaleProvider>} />
        <Route path="/login/verify" element={<LocaleProvider><VerifyPage /></LocaleProvider>} />
        <Route path="*" element={<AuthGate><SignedInLocale><Shell /></SignedInLocale></AuthGate>} />
      </Routes>
    </BrowserRouter>
  );
}

/** The signed-in language: the user's saved choice, saved again on every change (spec D1). */
function SignedInLocale({ children }: { children: ReactNode }) {
  const { me } = useAuth();
  const save = me.user_id ? async (locale: "en" | "id") => void (await authClient.updateMe({ locale })) : undefined;
  return <LocaleProvider serverLocale={me.locale ?? null} save={save}>{children}</LocaleProvider>;
}

function Shell() {
  const navigate = useNavigate();
  const location = useLocation();
  const { me } = useAuth();
  const nav = NAV.filter(([id]) => id !== "accounts" || me.platform_admin);
  const [projectId, setProjectId] = useActiveProject();
  const [loadedProjects, setProjects] = useState<Project[] | null>(null);
  const projects = loadedProjects ?? [];
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const [helpOpen, setHelpOpen] = useState(false);
  const inStudio = /^\/studio\/[^/]+\/[^/]+/.test(location.pathname);
  const page = pageFor(location.pathname);
  const switcher = <ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} />;

  const needsProject = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>{loadedProjects?.length === 0 ? "Create your first project" : "Select or create a project to begin."}</p>
      <p className="text-xs">Use “New project” at the top right.</p>
    </div>
  );

  const platformOnly = (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      <p>Source accounts are managed by the platform administrators.</p>
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
          <WorkspaceMenu me={me} onHelp={() => setHelpOpen(true)} onTokens={() => navigate("/settings/tokens")} onSignOut={(forget) => void authClient.logout(forget).finally(() => window.location.assign("/login"))} />
        </div>
      </header>
      <div className="dashboard-body">
        <nav className="dashboard-sidebar" aria-label="Workspace">
          <p className="dashboard-nav-label">Workspace</p>
          {nav.map(([id, label]) => {
            const Icon = pages[id].icon;
            const current = page === id || (id === "accounts" && page === "proxies") || (id === "studio" && inStudio);
            return <div key={id} className={id === "accounts" ? "dashboard-tools-start" : undefined}>
              {id === "accounts" && <p className="dashboard-nav-label">Tools</p>}
              <NavLink to={pages[id].path} className={cn(buttonVariants({ variant: "ghost" }), "dashboard-nav-item")} aria-current={current ? "page" : undefined}>
                <Icon aria-hidden="true" /><span>{label}</span>
              </NavLink>
            </div>;
          })}
          <div className="dashboard-sidebar-footer"><button type="button" onClick={() => setHelpOpen(true)}><CircleHelp aria-hidden="true" />Help & documentation</button></div>
        </nav>
        <main id="workspace" tabIndex={-1} className={`dashboard-main dashboard-page-${page === "studio" && !inStudio ? "drafts" : page}`}>
          {!inStudio && <header className="dashboard-page-heading"><div>
            <p className="dashboard-eyebrow">{pages[page].eyebrow}</p>
            <h1>{pages[page].label}</h1>
            <p>{pages[page].description}</p>
          </div><div id="dashboard-page-actions" className="pen-page-actions" /></header>}
          <Routes>
            <Route path="/" element={<Navigate to="/workflows" replace />} />
            <Route path="/workflows" element={<WorkflowsPage client={controlPlaneClient} projectId={projectId} projects={projects} onRuns={setRuns} />} />
            <Route path="/workflows/:workflowId" element={<WorkflowDetailRoute projectId={projectId} />} />
            <Route path="/studio" element={projectId ? <StudioDocumentsPage client={controlPlaneClient} projectId={projectId} /> : needsProject} />
            <Route path="/studio/:projectId/:documentId" element={<StudioDocumentRoute workspaceControls={switcher} projects={projects} />} />
            <Route path="/accounts" element={me.platform_admin ? <SourceAccounts client={sourceAccountsClient} onManageProxies={() => navigate("/accounts/proxies")} /> : platformOnly} />
            <Route path="/accounts/proxies" element={me.platform_admin ? <SourceProxies client={sourceAccountsClient} onBack={() => navigate("/accounts")} /> : platformOnly} />
            <Route path="/usage" element={<UsagePage />} />
            <Route path="/billing" element={<BillingPage />} />
            <Route path="/settings/tokens" element={<TokensPage />} />
            <Route path="*" element={<Navigate to="/workflows" replace />} />
          </Routes>
        </main>
      </div>
      <PenDialog open={helpOpen} onOpenChange={setHelpOpen} title="Help & shortcuts" description="Your local production workspace."><div className="pen-help-body"><h3>Production flow</h3><p>Start a workflow from a source, open its result in Creator Studio, and render.</p><h3>Keyboard</h3><p>Tab moves between controls. Escape closes dialogs and menus. Space plays or pauses the Studio preview.</p><p>Provider availability and supported operations depend on your configured server.</p></div></PenDialog>
    </div>
  );
}

function WorkflowDetailRoute({ projectId }: { projectId: string | null }) {
  const { workflowId = "" } = useParams();
  const navigate = useNavigate();
  return (
    <WorkflowDetailPage
      client={controlPlaneClient}
      workflowId={workflowId}
      projectId={projectId}
      onOpenStudio={(project, document, resolve) =>
        navigate(`/studio/${encodeURIComponent(project)}/${encodeURIComponent(document)}${resolve ? "?resolve=1" : ""}`)
      }
    />
  );
}

/** Studio from its URL alone; "Resolve source items" opens the gate without a Content Set. */
function StudioDocumentRoute({ workspaceControls, projects }: { workspaceControls: ReactNode; projects: Project[] }) {
  const { projectId = "", documentId = "" } = useParams();
  const navigate = useNavigate();
  // `opened` rises on every return from the gate, so Studio reloads the revision decisions saved.
  const [opened, setOpened] = useState(0);
  const [searchParams] = useSearchParams();
  // `?resolve=1`: a workflow import left an item unresolved, so the gate opens with the draft.
  const [resolving, setResolving] = useState(() => searchParams.get("resolve") === "1");
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
