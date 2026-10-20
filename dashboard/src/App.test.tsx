/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { EditDocument } from "./api/control-plane";

const document = {
  schema_version: 1, document_id: "document_001", project_id: "project_001", revision: 1,
  canvas: { width: 1080, height: 1920, fps: 30, duration_in_frames: 150 },
  template: { template_id: "vertical_text_story", version: 1 },
  tracks: [{ track_id: "track_visual", kind: "visual", clip_ids: ["clip_001"] }],
  scenes: [{ scene_id: "scene_001", role: "title", start_frame: 0, duration_in_frames: 150, clip_ids: ["clip_001"] }],
  clips: [{ kind: "text", clip_id: "clip_001", scene_id: "scene_001", track_id: "track_visual", start_frame: 0, duration_in_frames: 150, heading: "Heading", body: "Body", ownership: "ai_managed", style_slot: "title" }],
} satisfies EditDocument;
const sourceKey = "c".repeat(64);
const draft = { document_id: "document_001", source_key: sourceKey, revision: 1, created_at: "2026-09-24T18:02:00Z" };
let inspectBodies: string[] = [];
let createCalls = 0;
let apiWrites: string[] = [];
let requested: string[] = [];
let revision = 1;
let inventoryItems: unknown[] = [];
let projectsPending = false;
let projects: unknown[] = [{ project_id: "project_001", name: "Project", created_at: "", updated_at: "" }];
const ADMIN_ME = { user_id: "usr_1", email: "alice@acme.test", display_name: "Alice", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"], workspace: { workspace_id: "ws_bootstrap", name: "Thoth", role: "owner" }, platform_admin: true };
let me: unknown = ADMIN_ME;
const originalFetch = globalThis.fetch;
const response = (value: unknown) => new Response(JSON.stringify(value), { status: 200, headers: { "Content-Type": "application/json" } });

function stubFetch() {
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    requested.push(path);
    if (path === "/auth/me") return response(me);
    if (init?.method && init.method !== "GET") apiWrites.push(path);
    if (path === "/api/v1/projects" && init?.method === "POST") {
      return response({ project_id: "project_002", name: "Other", created_at: "", updated_at: "" });
    }
    if (path === "/api/v1/projects" && projectsPending) return new Promise<Response>(() => {});
    if (path === "/api/v1/projects") return response({ items: projects });
    if (path.includes("/workflows?") || path.endsWith("/workflows")) return response({ items: [], next_cursor: null });
    if (path.includes("/edit-documents?")) {
      return response({ items: [{ document_id: "document_001", revision: 1, updated_at: "", label: "Heading", imported: true }], next_cursor: null });
    }
    if (path.endsWith("/studio-imports/inspect")) {
      inspectBodies.push(String(init?.body));
      return response({ project_id: "project_001", source_key: sourceKey, items: [], drafts: [draft], more_drafts: false });
    }
    if (path.endsWith("/studio-imports")) { createCalls += 1; return response(draft); }
    if (path.endsWith("/items/footage_000/resolve")) {
      revision += 1;
      inventoryItems = [{ ...(inventoryItems[0] as object), disposition: "excluded" }];
    }
    if (path.includes("/studio-imports/documents/document_001")) {
      return response({ document_id: "document_001", source_key: sourceKey, revision, items: inventoryItems });
    }
    if (path.includes("/edit-documents/document_001")) return response({ ...document, revision });
    if (path.endsWith("/render-capability")) return response({ available: true, preset_id: "p", renderer_version: "r" });
    if (path.includes("/render-jobs")) return response({ jobs: [], next_cursor: null });
    if (path === "/api/v1/billing") return response({ workspace_id: "ws_bootstrap", unlimited: true, plan: null, period_start: null, period_end: null, workflows_used: 0, workflows_allowed: null, videos_used: 0, videos_allowed: null, plans: [], invoices: [] });
    if (path === "/api/v1/usage") return response({ workspace_id: "ws_bootstrap", month: "2026-10", workflows: 0, videos: 0, rendered_seconds: 0, stored_bytes: 0, leases: {}, quotas: [] });
    return response([]);
  }) as unknown as typeof fetch;
}

afterEach(() => { cleanup(); projectsPending = false; me = ADMIN_ME; globalThis.fetch = originalFetch; inspectBodies = []; createCalls = 0; apiWrites = []; requested = []; revision = 1; inventoryItems = []; projects = [{ project_id: "project_001", name: "Project", created_at: "", updated_at: "" }]; window.history.replaceState(null, "", "/"); localStorage.clear(); });

test("search navigates to the selected workspace page and closes its dialog", async () => {
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Search projects, workflows…" }));
  const dialog = await screen.findByRole("dialog");
  await user.click(within(dialog).getByRole("button", { name: /Creator Studio/ }));
  expect(await screen.findByRole("heading", { level: 1, name: "Creator Studio" })).toBeDefined();
  expect(Boolean(screen.queryByRole("dialog"))).toBe(false);
  expect(apiWrites).toHaveLength(0);
});

async function openDraft() {
  stubFetch();
  window.history.replaceState(null, "", "/studio/project_001/document_001");
  const { default: App } = await import("./App");
  render(<App />);
  await screen.findByLabelText("Heading");
}

test("workspace navigation identifies the active page and Creator Studio lists the project's drafts", async () => {
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  const nav = await screen.findByRole("navigation", { name: "Workspace" });
  // The gate renders the shell at "/" first; its redirect to /workflows lands a tick later.
  await waitFor(() => expect(within(nav).getByRole("link", { name: "Workflows" }).getAttribute("aria-current")).toBe("page"));
  await userEvent.setup().click(within(nav).getByRole("link", { name: "Creator Studio" }));
  expect(await screen.findByRole("button", { name: /Heading/ })).toBeDefined();
  expect(window.location.pathname).toBe("/studio");
  expect(within(nav).getByRole("link", { name: "Creator Studio" }).getAttribute("aria-current")).toBe("page");
  expect(createCalls).toBe(0);
  expect(inspectBodies).toHaveLength(0);
});

test("keeps naming the Studio document's project after the global project changes", async () => {
  await openDraft();
  const user = userEvent.setup();
  const header = globalThis.document.querySelector<HTMLElement>('section[aria-label="Guided Studio"] > header')!;
  expect(within(header).getAllByText("Project Project").length).toBeGreaterThan(0);

  await user.click(screen.getByLabelText("Studio workspace menu"));
  await user.click(screen.getByRole("combobox", { name: "Project" }));
  await user.click(await screen.findByRole("button", { name: /new project/i }));
  await user.type(screen.getByLabelText("New project name"), "Other");
  await user.click(screen.getByRole("button", { name: /^create$/i }));

  // The switcher selects the new project once its form closes.
  await waitFor(() => expect(Boolean(screen.queryByLabelText("New project name"))).toBe(false));
  expect(within(header).getAllByText("Project Project").length).toBeGreaterThan(0);
  expect(within(header).getByText("Saved revision 1")).toBeDefined();
});

test("Resolve source items in Studio reopens the draft's inventory and reloads the decided revision", async () => {
  inventoryItems = [{
    item_id: "footage_000", role: "footage", order: 0, label: "Crowd reaction", platform: "tiktok",
    media_kind: "video", scene_id: "scene_001", reason: null, disposition: "unresolved", asset_id: null,
  }];
  await openDraft();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Render" }));

  const blocked = await screen.findByRole("status", { name: "Source import" });
  expect(blocked.textContent).toContain("Crowd reaction · Scene 1");
  await user.click(within(blocked).getByRole("button", { name: "Resolve source items" }));
  const dialog = await screen.findByRole("dialog", { name: "Resolve source items" });
  await user.click(await within(dialog).findByRole("button", { name: "Exclude from Studio edit" }));
  await user.click(within(dialog).getByRole("button", { name: "Continue in Studio" }));

  expect(await screen.findByText("Saved revision 2")).toBeDefined();
  expect(createCalls).toBe(0);
  await user.click(screen.getByRole("button", { name: "Render" }));
  await waitFor(() => expect(screen.queryByRole("status", { name: "Source import" })).toBeNull());
});

test("a reloaded Studio deep link renders without Content Set state", async () => {
  stubFetch();
  window.history.replaceState(null, "", "/studio/project_001/document_001");
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByLabelText("Heading")).toBeDefined();
  expect(inspectBodies).toHaveLength(0);
});

test("a stored project that no longer exists falls back to the first project", async () => {
  stubFetch();
  localStorage.setItem("thoth.activeProject", "deleted_project");
  const { default: App } = await import("./App");
  render(<App />);
  await waitFor(() => expect(localStorage.getItem("thoth.activeProject")).toBe("project_001"));
});

test("an unknown path lands on Workflows", async () => {
  stubFetch();
  window.history.replaceState(null, "", "/no-such-page");
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeDefined();
  expect(window.location.pathname).toBe("/workflows");
});

test("no page reaches the retired Rust server: only control-plane routes are requested", async () => {
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  const nav = await screen.findByRole("navigation", { name: "Workspace" });
  expect(within(nav).getAllByRole("link").map((link) => link.textContent)).toEqual(["Workflows", "Creator Studio", "Usage", "Billing", "Source Accounts"]);
  const user = userEvent.setup();
  await user.click(within(nav).getByRole("link", { name: "Creator Studio" }));
  await screen.findByRole("button", { name: /Heading/ });
  await user.click(within(nav).getByRole("link", { name: "Workflows" }));
  await screen.findByRole("heading", { level: 1, name: "Workflows" });
  expect(requested.length).toBeGreaterThan(0);
  expect(requested.filter((path) => !path.startsWith("/api/v1/") && path !== "/auth/me")).toEqual([]);
});

for (const retired of ["/discovery", "/content-set", "/profiles", "/legacy"]) {
  test(`the retired ${retired} page lands on Workflows`, async () => {
    stubFetch();
    window.history.replaceState(null, "", retired);
    const { default: App } = await import("./App");
    render(<App />);
    expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeDefined();
    expect(window.location.pathname).toBe("/workflows");
  });
}

test("the Studio draft list keeps the ordinary page layout; only the editor goes full screen", async () => {
  stubFetch();
  window.history.replaceState(null, "", "/studio");
  const { default: App } = await import("./App");
  render(<App />);
  await screen.findByRole("button", { name: /Heading/ });
  const main = globalThis.document.getElementById("workspace")!;
  expect(main.className).not.toContain("dashboard-page-studio");
});

test("signed out, every page goes to the login page with next", async () => {
  stubFetch();
  const signedOut = globalThis.fetch;
  globalThis.fetch = mock(async (input: RequestInfo | URL, init?: RequestInit) =>
    String(input) === "/auth/me" ? new Response("{}", { status: 401 })
      : String(input) === "/auth/providers" ? response({ providers: ["google"] })
      : (signedOut as typeof fetch)(input, init),
  ) as unknown as typeof fetch;
  window.history.replaceState(null, "", "/studio");
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("link", { name: "Continue with Google" })).toBeDefined();
  expect(window.location.pathname + window.location.search).toBe("/login?next=%2Fstudio");
});

test("Source Accounts is only in the navigation of a platform admin", async () => {
  me = { ...ADMIN_ME, workspace_id: "ws_bob", workspace: { workspace_id: "ws_bob", name: "Bob's workspace", role: "owner" }, platform_admin: false };
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("heading", { level: 1, name: "Workflows" })).toBeDefined();
  expect(Boolean(screen.queryByRole("link", { name: /Source Accounts/ }))).toBe(false);
  cleanup();
  window.history.replaceState(null, "", "/accounts");
  render(<App />);
  expect(await screen.findByText("Source accounts are managed by the platform administrators.")).toBeDefined();
  expect(requested.some((path) => path.includes("/source-accounts"))).toBe(false);
});

test("an empty workspace invites the first project", async () => {
  projects = [];
  window.history.replaceState(null, "", "/studio");
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByText("Create your first project")).toBeDefined();
});

test("the first-project invitation waits for the project list", async () => {
  projectsPending = true;
  window.history.replaceState(null, "", "/studio");
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByText("Select or create a project to begin.")).toBeDefined();
  expect(Boolean(screen.queryByText("Create your first project"))).toBe(false);
});

test("Usage is in the navigation of every user", async () => {
  me = { ...ADMIN_ME, platform_admin: false };
  stubFetch();
  const { default: App } = await import("./App");
  render(<App />);
  expect(await screen.findByRole("link", { name: /Usage/ })).toBeDefined();
});
