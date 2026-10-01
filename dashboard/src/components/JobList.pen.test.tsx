import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { JobList } from "./JobList";

const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("job search keeps real status totals and leaves unsupported metrics unknown", async () => {
  const fetchJobs = mock(async () => new Response(JSON.stringify([
    { id: "live-1", spec: { command: "Autumn campaign" }, status: "running", pct: .4, created_at: "2026-10-01T00:00:00Z" },
    { id: "waiting-1", spec: { command: "Weekend notes" }, status: "queued", pct: 0, created_at: "2026-09-30T00:00:00Z" },
    { id: "done-1", spec: { command: "Coastal edit" }, status: "succeeded", pct: 1, created_at: "2026-09-29T00:00:00Z" },
  ]), { status: 200 }));
  globalThis.fetch = Object.assign(fetchJobs, { preconnect: originalFetch.preconnect });
  const onSelect = mock(() => {});
  const user = userEvent.setup();
  render(<JobList selectedId="live-1" onSelect={onSelect} />);
  await screen.findByRole("button", { name: /Autumn campaign/i });
  const metrics = screen.getByLabelText("Job statistics");
  expect(within(metrics).getAllByText("01")).toHaveLength(2);
  expect(within(metrics).getAllByText("—")).toHaveLength(2);
  await user.type(screen.getByLabelText("Search jobs"), "Weekend");
  expect(screen.queryByRole("button", { name: /Autumn campaign/i })).toBeNull();
  await user.click(screen.getByRole("button", { name: /Weekend notes/i }));
  expect(onSelect).toHaveBeenCalledWith("waiting-1");
  expect(within(metrics).getAllByText("01")).toHaveLength(2);
});
