import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { JobMonitor } from "./JobMonitor";

const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("operational controls keep cleanup blocked while live and cancel blocked after failure", async () => {
  const fetchRecord = mock(async (input: RequestInfo | URL) => {
    const path = String(input);
    if (path.endsWith("/manifest")) return new Response("{}", { status: 200 });
    return new Response(JSON.stringify({
      id: path.endsWith("/failed-job") ? "failed-job" : "live-job",
      status: path.endsWith("/failed-job") ? "failed" : "running",
      spec: { command: "Offline render" }, stage: "analyze", pct: .4,
      created_at: "2026-10-01T00:00:00Z", updated_at: "2026-10-01T00:00:00Z", output_dir: "",
    }), { status: 200 });
  });
  globalThis.fetch = Object.assign(fetchRecord, { preconnect: originalFetch.preconnect });
  const view = render(<JobMonitor jobId="live-job" />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(false));
  expect((screen.getByRole("button", { name: "Delete artifacts" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: /Approve stage/i }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Retry" }) as HTMLButtonElement).disabled).toBe(true);
  view.rerender(<JobMonitor jobId="failed-job" />);
  await waitFor(() => expect((screen.getByRole("button", { name: "Delete artifacts" }) as HTMLButtonElement).disabled).toBe(false));
  expect((screen.getByRole("button", { name: "Cancel" }) as HTMLButtonElement).disabled).toBe(true);
});
