/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";

import { AuthRequestError, type TokenView } from "@/api/auth";
import { LocaleProvider } from "@/lib/locale";

import { TokensPage } from "./TokensPage";

afterEach(cleanup);

const token = (name: string): TokenView => ({
  token_id: `tok_${name}`, owner_kind: "user", name, prefix: "thoth_pat_ab12cd", scope: "write",
  created_at: "2026-10-19T00:00:00Z", expires_at: "2027-01-17T00:00:00Z", last_used_at: null,
});

function client(listed: TokenView[] = [token("laptop")]) {
  return {
    listTokens: mock(async () => listed),
    createToken: mock(async () => ({ token: token("ci"), secret: "thoth_pat_secretvalue" })),
    revokeToken: mock(async () => {}),
  };
}

const inLocale = (children: ReactNode) => render(<LocaleProvider serverLocale="en">{children}</LocaleProvider>);

test("lists tokens without secrets", async () => {
  inLocale(<TokensPage client={client()} />);
  const row = (await screen.findByText("laptop")).closest("tr")!;
  expect(within(row).getByText("thoth_pat_ab12cd…")).toBeDefined();
  expect(within(row).getByText("Never")).toBeDefined();
  expect(within(row).getByText("Read and write")).toBeDefined();
});

test("a new token is shown once with what it can do", async () => {
  const c = client([]);
  inLocale(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Create token" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Token name"), "ci");
  await user.selectOptions(within(dialog).getByLabelText("Access"), "read");
  await user.click(within(dialog).getByRole("button", { name: "Create token" }));
  expect(c.createToken).toHaveBeenCalledWith({ name: "ci", scope: "read", days: 90 });
  expect(((await screen.findByRole("textbox", { name: "New token" })) as HTMLInputElement).value).toBe("thoth_pat_secretvalue");
  expect(screen.getByText("Copy it now. It is not shown again.")).toBeDefined();
});

test("revoking asks first", async () => {
  const c = client();
  inLocale(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
  const confirm = await screen.findByRole("alertdialog");
  expect(c.revokeToken).not.toHaveBeenCalled();
  await user.click(within(confirm).getByRole("button", { name: "Revoke" }));
  expect(c.revokeToken).toHaveBeenCalledWith("tok_laptop");
});

test("the limit and a missing account are explained", async () => {
  const c = client([]);
  c.createToken.mockImplementation(async () => { throw new AuthRequestError(409, "token_limit"); });
  inLocale(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Create token" }));
  const dialog = await screen.findByRole("dialog");
  await user.type(within(dialog).getByLabelText("Token name"), "x");
  await user.click(within(dialog).getByRole("button", { name: "Create token" }));
  expect(await screen.findByText("You have 20 active tokens. Revoke one to create another.")).toBeDefined();
  cleanup();
  const service = client();
  service.listTokens.mockImplementation(async () => { throw new AuthRequestError(403, "user_required"); });
  inLocale(<TokensPage client={service} />);
  expect(await screen.findByText("Developer tokens belong to a signed-in account.")).toBeDefined();
});
