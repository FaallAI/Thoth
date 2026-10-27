/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render as rawRender, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactElement } from "react";
import { LocaleProvider } from "@/lib/locale";

const inLocale = (ui: ReactElement) => <LocaleProvider serverLocale="en">{ui}</LocaleProvider>;
const render = (ui: ReactElement) => {
  const result = rawRender(inLocale(ui));
  return { ...result, rerender: (next: ReactElement) => result.rerender(inLocale(next)) };
};

import { ProjectSwitcher } from "./ProjectSwitcher";

const project = (projectId: string, name: string) => ({ project_id: projectId, name, created_at: "", updated_at: "" });

function fakeClient() {
  return {
    listProjects: mock(async () => [project("p1", "Alpha")]),
    createProject: mock(async (name: string) => project("p2", name)),
  };
}

afterEach(cleanup);

test("shows the selected project name before the menu is opened", async () => {
  render(<ProjectSwitcher projectId="p1" onSelect={() => {}} client={fakeClient()} />);
  expect(await screen.findByText("Alpha")).toBeDefined();
});

test("the compact project picker keeps creation inside its menu", async () => {
  const user = userEvent.setup();
  render(<ProjectSwitcher compact projectId="p1" onSelect={() => {}} client={fakeClient()} />);
  expect(await screen.findByText("Alpha")).toBeDefined();
  expect(Boolean(screen.queryByRole("button", { name: /new project/i }))).toBe(false);
  await user.click(screen.getByRole("combobox", { name: "Project" }));
  await user.click(await screen.findByRole("button", { name: "New project" }));
  expect(await screen.findByRole("textbox", { name: "New project name" })).toBeDefined();
});

test("creates a project from the inline form and selects it", async () => {
  const user = userEvent.setup();
  const onSelect = mock(() => {});
  const client = fakeClient();
  render(<ProjectSwitcher projectId="p1" onSelect={onSelect} client={client} />);

  await user.click(await screen.findByRole("button", { name: /new project/i }));
  await user.type(screen.getByLabelText(/new project name/i), "Beta");
  await user.click(screen.getByRole("button", { name: /^create$/i }));

  expect(client.createProject).toHaveBeenCalledWith("Beta");
  expect(onSelect).toHaveBeenCalledWith("p2");
});

test("shows an inline error when create fails", async () => {
  const client = fakeClient();
  client.createProject.mockImplementationOnce(async () => {
    throw new Error("project already exists");
  });
  const user = userEvent.setup();
  render(<ProjectSwitcher projectId="p1" onSelect={() => {}} client={client} />);

  await user.click(await screen.findByRole("button", { name: /new project/i }));
  await user.type(screen.getByLabelText(/new project name/i), "Alpha");
  await user.click(screen.getByRole("button", { name: /^create$/i }));

  expect(await screen.findByText("The project could not be created. Its name may already be in use.")).toBeDefined();
});

test("a remembered project that no longer exists falls back to the first one", async () => {
  const onSelect = mock(() => {});
  render(<ProjectSwitcher projectId="deleted" onSelect={onSelect} client={fakeClient()} />);
  await waitFor(() => expect(onSelect).toHaveBeenCalledWith("p1"));
});

test("with no projects at all, a remembered project is cleared", async () => {
  const onSelect = mock((_id: string | null) => {});
  const client = { ...fakeClient(), listProjects: mock(async () => []) };
  render(<ProjectSwitcher projectId="deleted" onSelect={onSelect} client={client} />);
  await waitFor(() => expect(onSelect).toHaveBeenCalledWith(null));
});

test("All projects is offered first and survives the project list", async () => {
  const onSelect = mock((_id: string | null) => {});
  const user = userEvent.setup();
  render(<ProjectSwitcher compact projectId="all" allLabel="All projects" onSelect={onSelect} client={fakeClient()} />);
  expect(await screen.findByText("All projects")).toBeDefined();
  await waitFor(() => expect(onSelect).not.toHaveBeenCalled());
  await user.click(screen.getByRole("combobox", { name: "Project" }));
  const options = await screen.findAllByRole("option");
  expect(options[0].textContent).toContain("All projects");
  await user.click(options[1]);
  expect(onSelect).toHaveBeenCalledWith("p1");
});
