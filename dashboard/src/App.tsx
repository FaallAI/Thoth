import { useEffect, useState, type ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation, useNavigate, useParams, useSearchParams } from "react-router";
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
import { AppShell, NAV } from "@/components/AppShell";
import { CommandPalette } from "@/components/CommandPalette";
import { authClient } from "@/api/auth";
import { AuthGate } from "@/features/auth/AuthGate";
import { useAuth } from "@/features/auth/auth-context";
import { TokensPage } from "@/features/settings/TokensPage";
import { UsagePage } from "@/features/usage/UsagePage";
import { BillingPage } from "@/features/billing/BillingPage";
import { LoginPage } from "@/features/auth/LoginPage";
import { VerifyPage } from "@/features/auth/VerifyPage";
import { useActiveProject } from "@/lib/active-project";
import type { MessageKey } from "@/lib/i18n";
import { LocaleProvider, useLocale } from "@/lib/locale";
import { documentLabel } from "@/lib/document-label";

/** Each page's title, by path prefix; the longest prefix wins. Runs and Studio are project pages. */
const PAGES: { path: string; title: MessageKey; project?: boolean }[] = [
  { path: "/workflows", title: "nav.runs", project: true },
  { path: "/studio", title: "nav.studio", project: true },
  { path: "/usage", title: "nav.usage" },
  { path: "/billing", title: "nav.billing" },
  { path: "/accounts/proxies", title: "page.proxies" },
  { path: "/accounts", title: "nav.accounts" },
  { path: "/settings/tokens", title: "page.tokens" },
];

function pageFor(pathname: string) {
  return PAGES.find((page) => pathname.startsWith(page.path)) ?? PAGES[0];
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
  const { t } = useLocale();
  const [projectId, setProjectId] = useActiveProject();
  const [loadedProjects, setProjects] = useState<Project[] | null>(null);
  const projects = loadedProjects ?? [];
  const [runs, setRuns] = useState<WorkflowRun[]>([]);
  const inStudio = /^\/studio\/[^/]+\/[^/]+/.test(location.pathname);
  const page = pageFor(location.pathname);
  const project = projects.find((item) => item.project_id === projectId);
  const switcher = <ProjectSwitcher compact projectId={projectId} onSelect={setProjectId} onProjectsChanged={setProjects} />;
  const palette = (
    <CommandPalette
      pages={NAV.filter((item) => !item.admin || me.platform_admin).map((item) => ({ path: item.path, label: t(item.label), icon: item.icon }))}
      projects={projects}
      runs={runs}
      onNavigate={(path) => navigate(path)}
      onProject={setProjectId}
    />
  );

  const notice = (lines: string[]) => (
    <div className="flex flex-1 flex-col items-center justify-center gap-1 p-8 text-sm text-muted-foreground">
      {lines.map((line, index) => <p key={line} className={index ? "text-xs" : undefined}>{line}</p>)}
    </div>
  );
  const needsProject = notice([t(loadedProjects?.length === 0 ? "project.first" : "project.choose"), t("project.hint")]);
  const platformOnly = notice([t("page.platformOnly")]);

  return (
    <AppShell
      me={me}
      switcher={switcher}
      palette={palette}
      chrome={!inStudio}
      onSignOut={(forget) => void authClient.logout(forget).finally(() => window.location.assign("/login"))}
    >
      <main id="workspace" tabIndex={-1} className={`dashboard-main min-w-0 flex-1 ${inStudio ? "dashboard-page-studio" : ""}`}>
        {!inStudio && (
          <header className="mb-6 flex flex-wrap items-start justify-between gap-4">
            <div>
              <h1 className="text-2xl leading-tight font-semibold text-ink">{t(page.title)}</h1>
              {page.project && project && <p className="mt-1 text-sm text-muted-ink">{t("project.current", { name: project.name })}</p>}
            </div>
            <div id="dashboard-page-actions" className="pen-page-actions" />
          </header>
        )}
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
    </AppShell>
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
