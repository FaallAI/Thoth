// Run progress pieces (DESIGN §6, §7; restyle R1).
import { afterEach, expect, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import type { ReactNode } from "react";

import type { components } from "@/api/generated/control-plane";
import { LocaleProvider } from "@/lib/locale";

import { SegmentedStageBar, StageStepper, StatusPill, StepRow } from "./RunProgress";

type Stage = components["schemas"]["StageSummary"];
type Step = components["schemas"]["WorkflowStep"];

afterEach(cleanup);

function inLocale(locale: "en" | "id", children: ReactNode) {
  return render(<LocaleProvider serverLocale={locale}>{children}</LocaleProvider>);
}

const step = (over: Partial<Step>): Step => ({
  at: "2026-10-25T14:05:10Z",
  attempt: 1,
  code: "footage.screen_clips",
  kind: "progress",
  seq: 1,
  stage: "footage",
  ...over,
});

const stages: Stage[] = [
  { id: "source", label: "Fetch the source", status: "completed", started_at: "2026-10-25T14:01:00Z", finished_at: "2026-10-25T14:03:24Z" },
  { id: "approval", label: "Your review", status: "skipped", skip_reason: "not_in_this_version" },
  {
    id: "footage",
    label: "Collect footage",
    status: "running",
    started_at: "2026-10-25T14:04:00Z",
    current_step: step({ n: 6, total: 12 }),
  },
  { id: "assembly", label: "Build the content set", status: "queued" },
  { id: "render", label: "Render", status: "queued" },
];

const now = new Date("2026-10-25T14:05:12Z");

test("a status pill names the state in the chosen language, for runs and stages alike", () => {
  inLocale("id", <><StatusPill status="awaiting_approval" /><StatusPill status="completed" /></>);
  expect(screen.getByText("Menunggu Anda")).toBeDefined();
  expect(screen.getByText("Selesai")).toBeDefined();
});

test("the vertical stepper shows each stage's duration, the elapsed time, and its line", () => {
  inLocale("en", <StageStepper stages={stages} now={now} />);
  const items = within(screen.getByRole("list", { name: "Run progress" })).getAllByRole("listitem");
  expect(items[0].textContent).toContain("2m 24s");
  expect(items[1].textContent).toContain("Not part of this run's version");
  expect(items[2].textContent).toContain("1m 12s elapsed");
  expect(items[2].textContent).toContain("Screening the clips");
  expect(items[3].textContent).toContain("Not started");
  // A stage this dashboard does not know reads with the server's label.
  expect(items[4].textContent).toContain("Render");
});

test("the compact stepper names the current stage and step, and the bar describes every stage", () => {
  inLocale("en", <StageStepper stages={stages} variant="compact" now={now} />);
  expect(screen.getByText("Collect footage · Screening the clips")).toBeDefined();
  expect(screen.getByRole("img").getAttribute("aria-label")).toBe(
    "Fetch the source: Done, Your review: Skipped, Collect footage: Running, Build the content set: Queued, Render: Queued",
  );
});

test("a step row shows its count, and a wait counts down", () => {
  inLocale("en", <ul><StepRow step={step({ n: 6, total: 12 })} current now={now} /></ul>);
  expect(screen.getByText("6 / 12")).toBeDefined();
  cleanup();

  inLocale(
    "en",
    <ul>
      <StepRow
        step={step({ code: "source.page_gap", stage: "source", kind: "wait", wait_until: "2026-10-25T14:05:42Z" })}
        now={now}
      />
    </ul>,
  );
  expect(screen.getByText("Pausing between pages")).toBeDefined();
  expect(screen.getByText("next in 30s")).toBeDefined();
});

test("a finished wait shows no countdown", () => {
  inLocale(
    "en",
    <ul>
      <StepRow step={step({ kind: "wait", wait_until: "2026-10-25T14:05:00Z" })} now={now} />
    </ul>,
  );
  expect(screen.queryByText(/next in/)).toBeNull();
});

test("a skipped stage stays in the bar, dimmed", () => {
  inLocale("en", <SegmentedStageBar stages={stages} />);
  const segments = screen.getByRole("img").children;
  expect(segments).toHaveLength(5);
  expect(segments[1].className).toContain("opacity-40");
});
