// The language switch: server choice first, then this browser's, then its language (DESIGN §12.1).
import { afterEach, beforeEach, expect, mock, test } from "bun:test";
import { act, cleanup, render, screen } from "@testing-library/react";

import { LocaleProvider, STORAGE_KEY, useLocale } from "./locale";

function Probe() {
  const { locale, setLocale, t } = useLocale();
  return (
    <div>
      <p>{t("nav.inbox")}</p>
      <p data-testid="locale">{locale}</p>
      <button type="button" onClick={() => void setLocale("id")}>id</button>
      <button type="button" onClick={() => void setLocale("en")}>en</button>
    </div>
  );
}

const original = Object.getOwnPropertyDescriptor(window.navigator, "languages");

function browserLanguages(languages: string[]) {
  Object.defineProperty(window.navigator, "languages", { configurable: true, get: () => languages });
}

beforeEach(() => {
  localStorage.clear();
  browserLanguages(["en-US"]);
});

afterEach(() => {
  cleanup();
  if (original) Object.defineProperty(window.navigator, "languages", original);
});

test("the language the user saved wins over this browser's", () => {
  localStorage.setItem(STORAGE_KEY, "en");
  browserLanguages(["en-US"]);
  render(
    <LocaleProvider serverLocale="id">
      <Probe />
    </LocaleProvider>,
  );

  expect(screen.getByText("Kotak masuk")).toBeDefined();
  expect(document.documentElement.lang).toBe("id");
});

test("without a saved choice, this browser's choice, then its language, decides", () => {
  browserLanguages(["id-ID"]);
  const first = render(
    <LocaleProvider>
      <Probe />
    </LocaleProvider>,
  );
  expect(screen.getByTestId("locale").textContent).toBe("id");
  first.unmount();

  localStorage.setItem(STORAGE_KEY, "en");
  render(
    <LocaleProvider>
      <Probe />
    </LocaleProvider>,
  );
  expect(screen.getByTestId("locale").textContent).toBe("en");
});

test("a signed-in user's choice is saved on the server and applies at once", async () => {
  const save = mock(async () => {});
  render(
    <LocaleProvider serverLocale={null} save={save}>
      <Probe />
    </LocaleProvider>,
  );

  await act(async () => screen.getByText("id").click());

  expect(save).toHaveBeenCalledWith("id");
  expect(screen.getByText("Kotak masuk")).toBeDefined();
  expect(localStorage.getItem(STORAGE_KEY)).toBe("id");
});

test("without a server, or when saving fails, the choice still holds in this browser", async () => {
  const save = mock(async () => {
    throw new Error("unavailable");
  });
  render(
    <LocaleProvider save={save}>
      <Probe />
    </LocaleProvider>,
  );

  await act(async () => screen.getByText("id").click());

  expect(screen.getByTestId("locale").textContent).toBe("id");
  expect(localStorage.getItem(STORAGE_KEY)).toBe("id");
});
