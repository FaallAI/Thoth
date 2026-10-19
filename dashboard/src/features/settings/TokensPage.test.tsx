/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { AuthRequestError, type TokenView } from "@/api/auth";

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

test("lists tokens without secrets", async () => {
  render(<TokensPage client={client()} />);
  const row = (await screen.findByText("laptop")).closest("tr")!;
  expect(within(row).getByText("thoth_pat_ab12cd…")).toBeDefined();
  expect(within(row).getByText("Never")).toBeDefined();
});

test("a new token is shown once with what it can do", async () => {
  const c = client([]);
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Token name"), "ci");
  await user.selectOptions(screen.getByLabelText("Access"), "read");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  expect(c.createToken).toHaveBeenCalledWith({ name: "ci", scope: "read", days: 90 });
  expect(((await screen.findByLabelText("New token")) as HTMLInputElement).value).toBe("thoth_pat_secretvalue");
  expect(screen.getByText("Copy it now. It is not shown again.")).toBeDefined();
});

test("revoking asks first", async () => {
  const c = client();
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "Revoke laptop" }));
  expect(c.revokeToken).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Confirm revoke laptop" }));
  expect(c.revokeToken).toHaveBeenCalledWith("tok_laptop");
});

test("the limit and a missing account are explained", async () => {
  const c = client([]);
  c.createToken.mockImplementation(async () => { throw new AuthRequestError(409, "token_limit"); });
  render(<TokensPage client={c} />);
  const user = userEvent.setup();
  await user.type(await screen.findByLabelText("Token name"), "x");
  await user.click(screen.getByRole("button", { name: "Create token" }));
  expect(await screen.findByText("You have 20 active tokens. Revoke one to create another.")).toBeDefined();
  cleanup();
  const service = client();
  service.listTokens.mockImplementation(async () => { throw new AuthRequestError(403, "user_required"); });
  render(<TokensPage client={service} />);
  expect(await screen.findByText("Developer tokens belong to a signed-in account.")).toBeDefined();
});
