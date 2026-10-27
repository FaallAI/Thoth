// Metric tile, empty state, skeleton and confirm dialog (DESIGN §6; restyle R1).
import { afterEach, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen } from "@testing-library/react";

import { LocaleProvider } from "@/lib/locale";

import { ConfirmDialog, EmptyState, MetricTile, Skeleton } from "./Feedback";

afterEach(cleanup);

test("a metric tile appears only with a real number", () => {
  const { container } = render(<MetricTile value={null} label="Success rate" />);
  expect(container.textContent).toBe("");
  render(<MetricTile value="92%" label="Success rate" />);
  expect(screen.getByText("92%")).toBeDefined();
});

test("an empty state is one sentence and one action", () => {
  render(<EmptyState action={<button type="button">New run</button>}>No runs yet.</EmptyState>);
  expect(screen.getByText("No runs yet.")).toBeDefined();
  expect(screen.getByRole("button", { name: "New run" })).toBeDefined();
});

test("a skeleton announces loading in the chosen language", () => {
  render(<LocaleProvider serverLocale="id"><Skeleton /></LocaleProvider>);
  expect(screen.getByRole("status", { name: "Memuat…" })).toBeDefined();
});

test("the confirm dialog runs the action only on confirm, then closes", async () => {
  const onConfirm = mock(() => {});
  const onOpenChange = mock((_open: boolean) => {});
  render(
    <LocaleProvider serverLocale="en">
      <ConfirmDialog
        open
        onOpenChange={onOpenChange}
        title="Cancel this run?"
        description="The source report is kept."
        confirmLabel="Cancel run"
        onConfirm={onConfirm}
        danger
      />
    </LocaleProvider>,
  );

  expect(screen.getByRole("alertdialog")).toBeDefined();
  await act(async () => screen.getByRole("button", { name: "Cancel" }).click());
  expect(onConfirm).not.toHaveBeenCalled();
  expect(onOpenChange).toHaveBeenCalledWith(false, expect.anything());

  await act(async () => screen.getByRole("button", { name: "Cancel run" }).click());
  expect(onConfirm).toHaveBeenCalledTimes(1);
  expect(onOpenChange).toHaveBeenLastCalledWith(false);
});
