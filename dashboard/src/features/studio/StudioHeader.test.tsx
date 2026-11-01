/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, fireEvent, screen, within } from "@testing-library/react";

import { render } from "@/test-render";

import { StudioHeader } from "./StudioHeader";
import type { StudioViewport } from "./studio_viewport";

afterEach(cleanup);

function mount(viewport: StudioViewport = "full_desktop", locale: "en" | "id" = "en", menuAttention = false) {
  const onBack = mock(() => {});
  render(
    <StudioHeader
      title="Kabut asap Kalteng dan evakuasi warga Palangka Raya"
      viewport={viewport}
      onBack={onBack}
      backDisabled={false}
      jobs={<nav aria-label="Studio jobs"><button type="button">Edit</button></nav>}
      mode={<div role="group" aria-label="Editor mode"><button type="button">Story</button></div>}
      history={<button type="button">Undo</button>}
      save={<span>Saved</span>}
      primary={<button type="button">Request review</button>}
      narration={<button type="button">Narrated · 4 beats</button>}
      menu={<button type="button">Assist</button>}
      menuAttention={menuAttention}
    />,
    { locale },
  );
  return { onBack, header: screen.getByRole("banner") };
}

test("tier 1 controls are always in the header", () => {
  const { header } = mount("compact_desktop");

  for (const name of ["Edit", "Story", "Undo", "Request review"]) expect(within(header).getByRole("button", { name })).toBeDefined();
  expect(within(header).getByText("Saved")).toBeDefined();
  expect(within(header).getByLabelText("Studio workspace menu")).toBeDefined();
});

test("the header row never wraps from 1024 up", () => {
  for (const viewport of ["compact_desktop", "full_desktop"] as const) {
    const { header } = mount(viewport);
    expect(header.className).toContain("h-14");
    expect(header.className).toContain("flex-nowrap");
    expect(header.className).not.toContain("flex-wrap ");
    cleanup();
  }
});

test("the narration chip is inline at full desktop and in the menu below it", () => {
  const wide = mount("full_desktop").header;
  expect(within(wide).getByRole("button", { name: "Narrated · 4 beats" }).closest("details")).toBeNull();
  cleanup();

  const narrow = mount("compact_desktop").header;
  expect(within(narrow).getByRole("button", { name: "Narrated · 4 beats" }).closest("details")).not.toBeNull();
});

test("the header stays one row in Indonesian at 1024, with the full title on hover", () => {
  const { header } = mount("compact_desktop", "id");

  const title = within(header).getByText("Kabut asap Kalteng dan evakuasi warga Palangka Raya");
  expect(title.getAttribute("title")).toBe("Kabut asap Kalteng dan evakuasi warga Palangka Raya");
  expect(title.className).toContain("truncate");
  expect(within(header).getByRole("navigation", { name: "Studio jobs" }).parentElement).toBe(header);
});

test("back is an icon with a name at 1024 and a word at 1440", () => {
  const narrow = mount("compact_desktop").header;
  const icon = within(narrow).getByRole("button", { name: "Back to Studio" });
  expect(icon.textContent?.trim()).toBe("");
  cleanup();

  const wide = mount("full_desktop").header;
  expect(within(wide).getByRole("button", { name: "Back to Studio" }).textContent).toContain("Studio");
});

test("the menu button carries a dot when a beat needs re-voice", () => {
  const { header } = mount("compact_desktop", "en", true);

  const button = within(header).getByLabelText("Studio workspace menu");
  expect(within(button).getByTestId("menu-attention")).toBeDefined();
  fireEvent.click(button);
  expect(within(header).getByRole("button", { name: "Assist" })).toBeDefined();
});

test("Request review keeps to one line", () => {
  const { header } = mount("compact_desktop");
  expect(within(header).getByRole("button", { name: "Request review" }).parentElement!.className).toContain("whitespace-nowrap");
});

test("the title is the one thing that shrinks, so the menu stays on screen", () => {
  // At 1024 a title that could not shrink pushed the menu button off the right edge (walk, 2026-11-01).
  const { header } = mount("compact_desktop");
  const title = within(header).getByText("Kabut asap Kalteng dan evakuasi warga Palangka Raya");
  expect(title.className.split(" ")).not.toContain("md:flex-none");
  expect(title.className.split(" ")).toContain("min-w-0");
});
