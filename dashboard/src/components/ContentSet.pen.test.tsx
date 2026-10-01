import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ContentSet } from "./ContentSet";

const originalFetch = globalThis.fetch;
afterEach(() => { cleanup(); globalThis.fetch = originalFetch; });

test("a missing content set retains story and evidence surfaces without allowing handoff", async () => {
  globalThis.fetch = Object.assign(mock(async (input: RequestInfo | URL) => Response.json(
    String(input).endsWith("/status") ? { run: null } : { exists: false, path: "", content: null, output_root: "", error: null },
  )), { preconnect: originalFetch.preconnect });
  render(<ContentSet projectId="project" onSendToRender={() => {}} />);
  expect(await screen.findByRole("heading", { name: "The story we are telling" })).toBeTruthy();
  expect(screen.getByRole("heading", { name: "What supports this story" })).toBeTruthy();
  expect((screen.getByRole("button", { name: "Send to render" }) as HTMLButtonElement).disabled).toBe(true);
  expect((screen.getByRole("button", { name: "Open in Studio" }) as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/No content-set yet/)).toBeTruthy();
});

test("send to render saves the edited source without dropping unknown fields", async () => {
  let content = { main: { title: "Original", description: "Context" }, footage: [], opaque: { retained: true } };
  const requests: { path: string; method: string }[] = [];
  globalThis.fetch = Object.assign(mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    const path = String(input);
    requests.push({ path, method: init?.method ?? "GET" });
    if (init?.method === "PUT") {
      content = JSON.parse(String(init.body));
      return Response.json({ ok: true, path: "C:/source/content-set.json" });
    }
    return Response.json(path.endsWith("/status") ? { run: null } : path.endsWith("/validate") ? {} : { exists: true, path: "C:/source/content-set.json", content, output_root: "", error: null });
  }), { preconnect: originalFetch.preconnect });
  const handoff = mock(() => {});
  const user = userEvent.setup();
  render(<ContentSet projectId="project" onSendToRender={handoff} />);
  await screen.findByDisplayValue("Original");
  await user.clear(screen.getByLabelText("Story title"));
  await user.type(screen.getByLabelText("Story title"), "Edited");
  await user.click(screen.getByRole("button", { name: "Send to render" }));
  expect(content.main.title).toBe("Edited");
  expect(content.opaque).toEqual({ retained: true });
  expect(requests).toContainEqual({ path: "/api/scout/content-set", method: "PUT" });
  expect(requests).toContainEqual({ path: "/api/scout/validate", method: "POST" });
  expect(handoff).toHaveBeenCalledWith("C:/source/content-set.json", false);
});

test("a failed save stops render handoff", async () => {
  globalThis.fetch = Object.assign(mock(async (input: RequestInfo | URL, init?: RequestInit) => {
    if (init?.method === "PUT") return Response.json({ error: "Disk unavailable" }, { status: 500 });
    return Response.json(String(input).endsWith("/status") ? { run: null } : { exists: true, path: "source.json", content: { main: { title: "Original" } }, output_root: "", error: null });
  }), { preconnect: originalFetch.preconnect });
  const handoff = mock(() => {});
  const user = userEvent.setup();
  render(<ContentSet projectId="project" onSendToRender={handoff} />);
  await screen.findByDisplayValue("Original");
  await user.type(screen.getByLabelText("Story title"), " edit");
  await user.click(screen.getByRole("button", { name: "Send to render" }));
  expect(await screen.findByText("Disk unavailable")).toBeTruthy();
  expect(handoff).not.toHaveBeenCalled();
});
