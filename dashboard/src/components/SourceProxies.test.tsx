/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceProxies } from "./SourceProxies";
import type { SourceAccountsClient, SourceProxy } from "@/api/source-accounts";

const POOL: SourceProxy[] = [
  { id: "p1", scheme: "http", display: "proxy.thoth.local:8080", account_platform: "tiktok", account_label: "Cedar · backup" },
  { id: "p2", scheme: "https", display: "eu-west.proxy.local:3128", account_platform: null, account_label: null },
];

function fakeClient(pool: SourceProxy[] = POOL) {
  return {
    proxies: mock(async () => pool),
    importProxies: mock(async () => ({ added: 12, duplicates: 2, invalid_lines: [7] })),
    removeProxy: mock(async () => undefined),
  } as unknown as SourceAccountsClient & Record<string, ReturnType<typeof mock>>;
}

afterEach(cleanup);

test("lists the pool by host and port and blocks deleting an assigned proxy", async () => {
  const client = fakeClient();
  render(<SourceProxies client={client} onBack={() => {}} />);
  const table = await screen.findByRole("table");
  expect(within(table).getByText("TikTok · Cedar · backup")).toBeDefined();
  expect(within(table).getByText("Unassigned")).toBeDefined();
  const held = within(table).getByRole("button", { name: "Delete proxy 1, proxy.thoth.local:8080" }) as HTMLButtonElement;
  expect(held.title).toBe("Assigned to an account");
  expect(held.disabled).toBe(true);
  await userEvent.click(within(table).getByRole("button", { name: "Delete proxy 2, eu-west.proxy.local:3128" }));
  expect(client.removeProxy).not.toHaveBeenCalled();
  await userEvent.click(within(table).getByRole("button", { name: "Confirm delete proxy 2, eu-west.proxy.local:3128" }));
  expect(client.removeProxy).toHaveBeenCalledWith("p2");
  expect(screen.getByText("02 proxies")).toBeDefined();
});

test("importing shows the summary by line number only", async () => {
  const client = fakeClient();
  render(<SourceProxies client={client} onBack={() => {}} />);
  await screen.findByRole("table");
  await userEvent.click(screen.getAllByRole("button", { name: /import proxies/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Proxy lines"), "http://u:secret@1.2.3.4:8080");
  await userEvent.click(within(dialog).getByRole("button", { name: "Import proxies" }));
  expect(await within(dialog).findByText("12 added, 2 duplicates skipped, 1 invalid line (line 7)")).toBeDefined();
  expect(client.importProxies).toHaveBeenCalledWith("http://u:secret@1.2.3.4:8080");
  expect(within(dialog).getByRole("button", { name: "Done" })).toBeDefined();
});

test("an empty pool invites an import", async () => {
  render(<SourceProxies client={fakeClient([])} onBack={() => {}} />);
  expect(await screen.findByText("No proxies yet")).toBeDefined();
});

test("two proxies on the same host and port keep distinct delete labels", async () => {
  const twin = { ...POOL[1], id: "p3" };
  render(<SourceProxies client={fakeClient([POOL[1], twin])} onBack={() => {}} />);
  const table = await screen.findByRole("table");
  const names = within(table).getAllByRole("button").map((button) => button.getAttribute("aria-label"));
  expect(new Set(names).size).toBe(2);
});
