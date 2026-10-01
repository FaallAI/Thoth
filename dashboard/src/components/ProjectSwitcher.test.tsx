/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

const listProjects = mock(async () => [{ id: "p1", name: "Alpha" }] as unknown[]);
const createProject = mock(async (name: string) => ({ id: "p2", name }));

// Same relative-path mock gotcha as RunForm.test.tsx.
mock.module("../api", () => ({ listProjects, createProject }));

afterEach(() => {
  cleanup();
  listProjects.mockClear();
  createProject.mockClear();
});

test("shows the selected project name before the menu is opened", async () => {
  const { ProjectSwitcher } = await import("./ProjectSwitcher");
  render(<ProjectSwitcher projectId="p1" onSelect={() => {}} />);
  expect(await screen.findByText("Alpha")).toBeDefined();
});

test("the compact project picker keeps creation inside its menu", async () => {
  const { ProjectSwitcher } = await import("./ProjectSwitcher");
  const user = userEvent.setup();
  render(<ProjectSwitcher compact projectId="p1" onSelect={() => {}} />);
  expect(await screen.findByText("Alpha")).toBeDefined();
  expect(Boolean(screen.queryByRole("button", { name: /new project/i }))).toBe(false);
  await user.click(screen.getByRole("combobox", { name: "Project" }));
  await user.click(await screen.findByRole("button", { name: "New project" }));
  expect(await screen.findByRole("textbox", { name: "New project name" })).toBeDefined();
});

test("creates a project from the inline form and selects it", async () => {
  const user = userEvent.setup();
  const onSelect = mock(() => {});
  const { ProjectSwitcher } = await import("./ProjectSwitcher");
  render(<ProjectSwitcher projectId="p1" onSelect={onSelect} />);

  await user.click(await screen.findByRole("button", { name: /new project/i }));
  await user.type(screen.getByLabelText(/new project name/i), "Beta");
  await user.click(screen.getByRole("button", { name: /^create$/i }));

  expect(createProject).toHaveBeenCalledWith("Beta");
  expect(onSelect).toHaveBeenCalledWith("p2");
});

test("shows an inline error when create fails", async () => {
  createProject.mockImplementationOnce(async () => {
    throw new Error("project already exists");
  });
  const user = userEvent.setup();
  const { ProjectSwitcher } = await import("./ProjectSwitcher");
  render(<ProjectSwitcher projectId="p1" onSelect={() => {}} />);

  await user.click(await screen.findByRole("button", { name: /new project/i }));
  await user.type(screen.getByLabelText(/new project name/i), "Alpha");
  await user.click(screen.getByRole("button", { name: /^create$/i }));

  expect(await screen.findByText("project already exists")).toBeDefined();
});
