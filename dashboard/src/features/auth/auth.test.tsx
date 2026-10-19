/// <reference types="bun-types" />

import { afterEach, expect, mock, test } from "bun:test";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router";

import { AuthRequestError, type Me } from "@/api/auth";
import { notifyForbidden } from "@/lib/auth-events";

import { AuthGate } from "./AuthGate";
import { useAuth } from "./auth-context";
import { LoginPage } from "./LoginPage";
import { VerifyPage } from "./VerifyPage";

afterEach(cleanup);

const ME: Me = { user_id: "usr_1", email: "alice@acme.test", display_name: "Alice", workspace_id: "ws_bootstrap", scopes: ["admin", "read", "write"] };

function Who() {
  return <p>{`signed in as ${useAuth().me.email}`}</p>;
}

function gate(me: () => Promise<Me | null>, path = "/studio") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/login" element={<p>login page</p>} />
        <Route path="*" element={<AuthGate client={{ me: mock(me) }}><Who /></AuthGate>} />
      </Routes>
    </MemoryRouter>,
  );
}

test("a signed-in person sees the app", async () => {
  gate(async () => ME);
  expect(await screen.findByText("signed in as alice@acme.test")).toBeDefined();
});

test("nobody signed in goes to the login page", async () => {
  gate(async () => null);
  expect(await screen.findByText("login page")).toBeDefined();
});

test("a 403 from any API call re-checks the session and signs out when it ended", async () => {
  let current: Me | null = ME;
  gate(async () => current);
  await screen.findByText("signed in as alice@acme.test");
  current = null;
  notifyForbidden();
  expect(await screen.findByText("login page")).toBeDefined();
});

test("an unreachable control plane offers a retry instead of the login page", async () => {
  let calls = 0;
  gate(async () => {
    calls += 1;
    if (calls === 1) throw new AuthRequestError(503, null);
    return ME;
  });
  await userEvent.setup().click(await screen.findByRole("button", { name: "Try again" }));
  expect(await screen.findByText("signed in as alice@acme.test")).toBeDefined();
});

test("the login page offers the configured providers and carries next", async () => {
  render(
    <MemoryRouter initialEntries={["/login?next=%2Fstudio%2Fp%2Fd&error=not_allowed"]}>
      <LoginPage client={{ providers: mock(async () => ["github", "google"]) }} />
    </MemoryRouter>,
  );
  expect(await screen.findByText("This account is not allowed to sign in to this workspace.")).toBeDefined();
  const google = await screen.findByRole("link", { name: "Continue with Google" });
  expect(google.getAttribute("href")).toBe("/auth/login/google?next=%2Fstudio%2Fp%2Fd");
  expect(screen.getByRole("link", { name: "Continue with GitHub" })).toBeDefined();
});

test("with no provider configured the login page says so", async () => {
  render(<MemoryRouter initialEntries={["/login"]}><LoginPage client={{ providers: mock(async () => []) }} /></MemoryRouter>);
  expect(await screen.findByText("Sign-in is not configured on this server.")).toBeDefined();
});

test("the verify page signs in with the code and reports a wrong one", async () => {
  const verify = mock(async (code: string) => {
    if (code === "000000") throw new AuthRequestError(400, "wrong_code");
    return "/studio";
  });
  const onSignedIn = mock((_target: string) => {});
  render(
    <MemoryRouter initialEntries={["/login/verify?next=%2Fstudio"]}>
      <VerifyPage client={{ verify, resend: mock(async () => {}) }} onSignedIn={onSignedIn} />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  const input = screen.getByLabelText("Code from your email");
  expect(input.getAttribute("autocomplete")).toBe("one-time-code");
  await user.type(input, "000000");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByText("That code is not right. Check the email and try again.")).toBeDefined();
  await user.clear(input);
  await user.type(input, "123456");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith("/studio"));
  expect(verify).toHaveBeenLastCalledWith("123456", true, "/studio");
  expect((screen.getByRole("button", { name: /Resend in/ }) as HTMLButtonElement).disabled).toBe(true);
});

test("the verify page never leaves the site, whatever the server echoes", async () => {
  const onSignedIn = mock((_target: string) => {});
  render(
    <MemoryRouter initialEntries={["/login/verify"]}>
      <VerifyPage client={{ verify: mock(async () => "/\t/evil.example"), resend: mock(async () => {}) }} onSignedIn={onSignedIn} />
    </MemoryRouter>,
  );
  const user = userEvent.setup();
  await user.type(screen.getByLabelText("Code from your email"), "123456");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await waitFor(() => expect(onSignedIn).toHaveBeenCalledWith("/workflows"));
});
