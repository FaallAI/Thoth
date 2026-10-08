/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SourceAccounts } from "./SourceAccounts";
import {
  SourceAccountsRequestError,
  type SourceAccount,
  type SourceAccountsClient,
  type SourceAccountsOverview,
} from "@/api/source-accounts";

const DAY = 86_400_000;
const NOW = Date.now();

function account(overrides: Partial<SourceAccount>): SourceAccount {
  return {
    id: "00000000-0000-0000-0000-000000000001",
    platform: "tiktok",
    label: "Cedar · primary",
    status: "healthy",
    cooldown_until: null,
    last_used_at: null,
    last_outcome: null,
    success_count: 0,
    failure_count: 0,
    cookie_names: ["sessionid", "tt_csrf_token"],
    cookies_earliest_expiry: new Date(NOW + 12 * DAY).toISOString(),
    proxy_id: null,
    proxy_display: null,
    created_at: new Date(NOW).toISOString(),
    updated_at: new Date(NOW).toISOString(),
    ...overrides,
  };
}

const ROWS = [
  account({}),
  account({ id: "00000000-0000-0000-0000-000000000002", label: "Cedar · backup", status: "cooldown",
    cooldown_until: new Date(NOW + 3_600_000).toISOString(), proxy_id: "p1", proxy_display: "proxy.thoth.local:8080" }),
  account({ id: "00000000-0000-0000-0000-000000000003", label: "Archive login", status: "expired" }),
];

function overview(available = true, accounts = ROWS, mode: "anonymous" | "fallback" | "always" = "fallback"): SourceAccountsOverview {
  return {
    available,
    platforms: ["tiktok", "threads", "instagram", "x", "youtube"].map((platform) => {
      const mine = accounts.filter((row) => row.platform === platform);
      const count = (status: string) => mine.filter((row) => row.status === status).length;
      return {
        platform: platform as SourceAccount["platform"],
        mode,
        min_spacing_seconds: 60,
        counts: { healthy: count("healthy"), cooldown: count("cooldown"), expired: count("expired"), disabled: count("disabled") },
        accounts: mine,
      };
    }),
  };
}

function fakeClient(state: SourceAccountsOverview = overview()): SourceAccountsClient & Record<string, ReturnType<typeof mock>> {
  return {
    overview: mock(async () => state),
    setPolicy: mock(async (_platform, policy) => policy),
    validate: mock(async (_platform, cookies: string) => cookies.includes("sessionid")
      ? { valid: true, count: 1, names: ["sessionid"], earliest_expiry: "2030-01-01T00:00:00Z", error: null, missing: [] }
      : { valid: false, count: 0, names: [], earliest_expiry: null, error: "missing_required_cookie", missing: ["sessionid"] }),
    create: mock(async (request) => account({ label: request.label })),
    reimport: mock(async (id: string) => account({ id })),
    update: mock(async (id: string, update) => account({ id, ...(update.label ? { label: update.label } : {}),
      ...(update.disabled ? { status: "disabled" } : {}) })),
    remove: mock(async () => undefined),
    test: mock(async (id: string) => ({ result: "valid", account: account({ id }) })),
    proxies: mock(async () => []),
    importProxies: mock(async () => ({ added: 0, duplicates: 0, invalid_lines: [] })),
    removeProxy: mock(async () => undefined),
  } as never;
}

afterEach(cleanup);

test("shows the platform's access, counts, and accounts without any cookie value", async () => {
  render(<SourceAccounts client={fakeClient()} onManageProxies={() => {}} />);
  expect(await screen.findByText("Cedar · primary")).toBeDefined();
  expect(screen.getByRole("tab", { name: "TikTok", selected: true })).toBeDefined();
  expect(screen.getByRole("radio", { name: "fallback", checked: true })).toBeDefined();
  const table = screen.getByRole("table");
  expect(within(table).getByText("cooldown")).toBeDefined();
  expect(within(table).getByText("re-import needed")).toBeDefined();
  expect(within(table).getByText("proxy.thoth.local:8080")).toBeDefined();
  expect(within(table).getAllByText("Direct").length).toBe(2);
  expect(within(table).getAllByText("in 12 days").length).toBe(3);
  expect(screen.getByText("03 accounts")).toBeDefined();
});

test("changing the access mode saves the platform's policy", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await userEvent.click(await screen.findByRole("radio", { name: "always" }));
  expect(client.setPolicy).toHaveBeenCalledWith("tiktok", { mode: "always", min_spacing_seconds: 60 });
});

test("an unavailable server explains itself and disables adding", async () => {
  render(<SourceAccounts client={fakeClient(overview(false, []))} onManageProxies={() => {}} />);
  expect(await screen.findByText(/not configured on this server/)).toBeDefined();
  expect((screen.getAllByRole("button", { name: /add account/i })[0] as HTMLButtonElement).disabled).toBe(true);
});

test("an empty platform invites an import, and no healthy account warns", async () => {
  render(<SourceAccounts client={fakeClient()} onManageProxies={() => {}} />);
  await userEvent.click(await screen.findByRole("tab", { name: "Threads" }));
  expect(screen.getByText("No Threads accounts yet")).toBeDefined();
  expect(screen.getByText(/No healthy account. Acquisition on Threads runs anonymously/)).toBeDefined();
});

test("testing a session reports the verdict", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getByRole("button", { name: "Test session for Cedar · primary" }));
  expect(await screen.findByText("Cedar · primary: Session valid")).toBeDefined();
  expect(client.test).toHaveBeenCalledWith(ROWS[0].id);
});

test("adding an account validates the export before it can be imported", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: /add account/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Account label"), "Cedar · new");
  await userEvent.click(within(dialog).getByRole("button", { name: "Paste" }));
  const importButton = within(dialog).getByRole("button", { name: "Import account" }) as HTMLButtonElement;
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), "no login here");
  expect(await within(dialog).findByText(/Missing sessionid/)).toBeDefined();
  expect(importButton.disabled).toBe(true);
  await userEvent.clear(within(dialog).getByLabelText("Cookie export"));
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), ".tiktok.com sessionid secret");
  expect(await within(dialog).findByText(/Found 1 cookies; sessionid/)).toBeDefined();
  await waitFor(() => expect(importButton.disabled).toBe(false));
  await userEvent.click(importButton);
  expect(client.create).toHaveBeenCalledWith({
    platform: "tiktok", label: "Cedar · new", cookies: ".tiktok.com sessionid secret", proxy_id: null,
  });
});

test("a refused import names what is missing, never the server's words", async () => {
  const client = fakeClient();
  (client.create as unknown as ReturnType<typeof mock>).mockImplementation(async () => {
    throw new SourceAccountsRequestError(409, "label_taken");
  });
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getAllByRole("button", { name: /add account/i })[0]);
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(within(dialog).getByLabelText("Account label"), "Cedar · primary");
  await userEvent.click(within(dialog).getByRole("button", { name: "Paste" }));
  await userEvent.type(within(dialog).getByLabelText("Cookie export"), "sessionid");
  await waitFor(() => expect((within(dialog).getByRole("button", { name: "Import account" }) as HTMLButtonElement).disabled).toBe(false));
  await userEvent.click(within(dialog).getByRole("button", { name: "Import account" }));
  expect(await within(dialog).findByText("Another account on this platform already uses that label.")).toBeDefined();
});

test("editing renames, disables, and deletes with a confirmation", async () => {
  const client = fakeClient();
  render(<SourceAccounts client={client} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · primary");
  await userEvent.click(screen.getByRole("button", { name: "Edit Cedar · primary" }));
  let dialog = await screen.findByRole("dialog");
  const label = within(dialog).getByLabelText("Account label");
  await userEvent.clear(label);
  await userEvent.type(label, "Renamed");
  await userEvent.click(within(dialog).getByRole("button", { name: "Save changes" }));
  expect(client.update).toHaveBeenCalledWith(ROWS[0].id, { label: "Renamed", proxy_id: null });

  await userEvent.click(screen.getByRole("button", { name: "Edit Cedar · primary" }));
  dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Disable account" }));
  expect(client.update).toHaveBeenCalledWith(ROWS[0].id, { disabled: true });

  await userEvent.click(screen.getByRole("button", { name: "Edit Cedar · primary" }));
  dialog = await screen.findByRole("dialog");
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
  expect(client.remove).not.toHaveBeenCalled();
  await userEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));
  expect(client.remove).toHaveBeenCalledWith(ROWS[0].id);
});

test("manage proxies hands over to the proxy view", async () => {
  const onManage = mock(() => {});
  render(<SourceAccounts client={fakeClient()} onManageProxies={onManage} />);
  await userEvent.click(await screen.findByRole("button", { name: /manage proxies/i }));
  expect(onManage).toHaveBeenCalled();
});

test("every row action names its account", async () => {
  render(<SourceAccounts client={fakeClient()} onManageProxies={() => {}} />);
  await screen.findByText("Cedar · backup");
  for (const name of ["Test session for", "Re-import cookies for", "Edit"]) {
    expect(screen.getByRole("button", { name: `${name} Cedar · backup` })).toBeDefined();
  }
});
