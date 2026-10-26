// The app shell and ⌘K navigation (DESIGN §4; restyle R1, D5).
import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes, useLocation } from "react-router";

import type { Me } from "@/api/auth";
import { LocaleProvider } from "@/lib/locale";

import { AppShell, NAV } from "./AppShell";
import { CommandPalette } from "./CommandPalette";

afterEach(() => {
  cleanup();
  localStorage.clear();
});

const ME: Me = {
  user_id: "usr_1",
  email: "alya@hazewatch.id",
  display_name: "Alya Putri",
  workspace_id: "ws_1",
  scopes: ["read", "write"],
  workspace: { workspace_id: "ws_1", name: "Haze watch", role: "owner" },
  platform_admin: false,
};

function Where() {
  return <p data-testid="where">{useLocation().pathname}</p>;
}

function shell(save?: (locale: "en" | "id") => Promise<void>, onSignOut = (_forget: boolean) => {}) {
  return render(
    <MemoryRouter initialEntries={["/workflows"]}>
      <LocaleProvider serverLocale="en" save={save}>
        <AppShell
          me={ME}
          switcher={<span>Haze watch</span>}
          palette={
            <CommandPalette
              pages={NAV.map((item) => ({ path: item.path, label: item.path, icon: item.icon }))}
              projects={[]}
              runs={[]}
              onNavigate={() => {}}
              onProject={() => {}}
            />
          }
          onSignOut={onSignOut}
        >
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </AppShell>
      </LocaleProvider>
    </MemoryRouter>,
  );
}

test("the language switch in the avatar menu relabels the shell and saves the choice", async () => {
  const save = mock(async () => {});
  shell(save);
  const user = userEvent.setup();
  const nav = screen.getByRole("navigation", { name: "Main navigation" });
  expect(within(nav).getByRole("link", { name: "Usage" })).toBeDefined();

  await user.click(screen.getByRole("button", { name: "Account menu" }));
  expect(screen.getByText("alya@hazewatch.id")).toBeDefined();
  await user.click(screen.getByRole("button", { name: "Bahasa Indonesia" }));

  expect(save).toHaveBeenCalledWith("id");
  const navigasi = screen.getByRole("navigation", { name: "Navigasi utama" });
  expect(within(navigasi).getByRole("link", { name: "Pemakaian" })).toBeDefined();
  expect(screen.getByRole("button", { name: "Bahasa Indonesia" }).getAttribute("aria-pressed")).toBe("true");
});

test("admins only see Accounts, and signing out can forget the browser", async () => {
  const onSignOut = mock((_forget: boolean) => {});
  shell(undefined, onSignOut);
  expect(screen.queryByRole("link", { name: /Accounts/ })).toBeNull();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Account menu" }));
  await user.click(screen.getByRole("button", { name: "Sign out and forget this browser" }));
  expect(onSignOut).toHaveBeenCalledWith(true);
});

test("the collapsed sidebar keeps every page reachable by name, and remembers itself", async () => {
  shell();
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Collapse the sidebar" }));
  const nav = screen.getByRole("navigation", { name: "Main navigation" });
  expect(within(nav).getByText("Billing").className).toContain("sr-only");
  expect(localStorage.getItem("thoth.sidebarCollapsed")).toBe("1");
  expect(screen.getByRole("button", { name: "Expand the sidebar" })).toBeDefined();
});

test("⌘K opens the palette; arrows and Enter go to a page", async () => {
  const onNavigate = mock((_path: string) => {});
  render(
    <LocaleProvider serverLocale="en">
      <CommandPalette
        pages={[
          { path: "/workflows", label: "Runs", icon: () => null },
          { path: "/usage", label: "Usage", icon: () => null },
        ]}
        projects={[{ project_id: "p1", name: "Haze watch", created_at: "", updated_at: "" }]}
        runs={[]}
        onNavigate={onNavigate}
        onProject={() => {}}
      />
    </LocaleProvider>,
  );
  await act(async () => {
    window.dispatchEvent(new KeyboardEvent("keydown", { key: "k", metaKey: true }));
  });
  const input = screen.getByRole("textbox", { name: "Go to" });
  const user = userEvent.setup();
  await user.type(input, "{ArrowDown}{Enter}");
  expect(onNavigate).toHaveBeenCalledWith("/usage");
  expect(screen.queryByRole("dialog")).toBeNull();
});

test("the palette filters, and says so when nothing matches", async () => {
  render(
    <LocaleProvider serverLocale="en">
      <CommandPalette pages={[]} projects={[]} runs={[]} onNavigate={() => {}} onProject={() => {}} />
    </LocaleProvider>,
  );
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: /Search runs, documents/ }));
  await user.type(screen.getByRole("textbox", { name: "Go to" }), "zzz");
  expect(screen.getByText("Nothing matches “zzz”.")).toBeDefined();
  await user.clear(screen.getByRole("textbox", { name: "Go to" }));
  await user.type(screen.getByRole("textbox", { name: "Go to" }), "language");
  expect(screen.getByRole("option", { name: "Switch language" })).toBeDefined();
});
