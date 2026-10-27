// Settings (restyle R4): the language saves, the notification state is told as the browser has it.
import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import type { Me } from "@/api/auth";
import { LocaleProvider } from "@/lib/locale";

import { SettingsPage } from "./SettingsPage";

const ME: Me = {
  user_id: "usr_1", email: "alya@hazewatch.id", display_name: "Alya", workspace_id: "ws_1",
  scopes: ["read", "write"], workspace: { workspace_id: "ws_1", name: "Haze", role: "owner" }, platform_admin: false,
};
const tokens = { listTokens: mock(async () => []), createToken: mock(async () => ({}) as never), revokeToken: mock(async () => {}) };
let permission: NotificationPermission = "default";
const request = mock(async () => {
  permission = "granted";
  return permission;
});

beforeEach(() => {
  permission = "default";
  localStorage.clear();
  Object.assign(window, {
    Notification: class {
      static get permission() {
        return permission;
      }
      static requestPermission = request;
    },
  });
});
afterEach(cleanup);

test("choosing a language applies it and saves it", async () => {
  const save = mock(async (_locale: "en" | "id") => {});
  render(
    <LocaleProvider serverLocale="en" save={save}>
      <SettingsPage me={ME} tokens={tokens} />
    </LocaleProvider>,
  );
  await userEvent.setup().click(screen.getByRole("button", { name: "Bahasa Indonesia" }));
  expect(save).toHaveBeenCalledWith("id");
  expect(await screen.findByText("Preferensi")).toBeDefined();
  expect(screen.getByText("alya@hazewatch.id")).toBeDefined();
});

test("notifications ask the browser once, then say they are allowed", async () => {
  render(
    <LocaleProvider serverLocale="en">
      <SettingsPage me={ME} tokens={tokens} />
    </LocaleProvider>,
  );
  await act(async () => screen.getByRole("button", { name: "Allow" }).click());
  expect(request).toHaveBeenCalled();
  expect(await screen.findByText("Allowed")).toBeDefined();
});

test("a blocked browser is explained, not offered a button that cannot work", () => {
  permission = "denied";
  render(
    <LocaleProvider serverLocale="en">
      <SettingsPage me={ME} tokens={tokens} />
    </LocaleProvider>,
  );
  expect(screen.getByText(/Blocked in this browser/)).toBeDefined();
  expect(screen.queryByRole("button", { name: "Allow" })).toBeNull();
});
