/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Me } from "@/api/auth";

import { WorkspaceMenu } from "./WorkspaceMenu";

afterEach(cleanup);

const ME: Me = { user_id: "usr_1", email: "alice.walker@acme.test", display_name: "Alice Walker", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"] };

test("the menu names the signed-in person and signs out", async () => {
  const onSignOut = mock((_forget: boolean) => {});
  const onTokens = mock(() => {});
  render(<WorkspaceMenu me={ME} onHelp={() => {}} onTokens={onTokens} onSignOut={onSignOut} />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Workspace menu" }));
  expect(screen.getAllByText("AW").length).toBeGreaterThan(0);
  expect(screen.getByText("alice.walker@acme.test")).toBeDefined();
  await user.click(screen.getByRole("button", { name: /Developer tokens/ }));
  expect(onTokens).toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: "Workspace menu" }));
  await user.click(screen.getByRole("button", { name: "Sign out and forget this browser" }));
  expect(onSignOut).toHaveBeenCalledWith(true);
});
