/// <reference types="bun-types" />

import { afterEach, expect, test } from "bun:test";
import { act, cleanup, fireEvent, screen } from "@testing-library/react";

import { render } from "@/test-render";

import { PresetsPage } from "./PresetsPage";
import { createC2ClientFixtureBase } from "./prompt-proposal-test-fixtures";

const initialWidth = window.innerWidth;

function resize(width: number) {
  act(() => {
    Object.defineProperty(window, "innerWidth", { configurable: true, value: width });
    window.dispatchEvent(new Event("resize"));
  });
}

afterEach(() => {
  cleanup();
  resize(initialWidth);
});

test("Prompt Lab lives on the project page", async () => {
  render(<PresetsPage client={createC2ClientFixtureBase()} projectId="project_001" />);

  expect(await screen.findByRole("region", { name: "Prompt Lab" })).toBeDefined();
  expect(screen.getByText("The prompts and presets every draft in this project starts from.")).toBeDefined();
});

test("a phone edits saved prompt text only and keeps the draft when the screen widens", async () => {
  resize(375);
  render(<PresetsPage client={createC2ClientFixtureBase()} projectId="project_001" />);

  const override = (await screen.findByLabelText("Project override")) as HTMLTextAreaElement;
  fireEvent.change(override, { target: { value: "Phone draft" } });
  expect(screen.queryByRole("button", { name: "Improve with AI" }) === null).toBe(true);
  expect(screen.getByText(/AI proposals, locks, and provider settings need a wider screen/)).toBeDefined();

  resize(900);
  expect(screen.getByRole("button", { name: "Improve with AI" })).toBeDefined();
  expect((screen.getByLabelText("Project override") as HTMLTextAreaElement).value).toBe("Phone draft");
});

test("the page reads in Indonesian", async () => {
  render(<PresetsPage client={createC2ClientFixtureBase()} projectId="project_001" />, { locale: "id" });

  expect(await screen.findByRole("region", { name: "Prompt Lab" })).toBeDefined();
  expect(screen.getByLabelText("Override proyek")).toBeDefined();
  expect(screen.getByRole("navigation", { name: "Tahap prompt" })).toBeDefined();
});
