// The dashboard language, and the copy and formats that follow it (DESIGN §12.1, restyle D1).
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import {
  browserLocale,
  formatDay,
  formatDuration,
  formatNumber,
  LOCALES,
  plural,
  translate,
  type Locale,
  type MessageKey,
  type PluralKey,
  type Values,
} from "./i18n";

/** This browser's last choice, for callers without a user and when the server is away. */
export const STORAGE_KEY = "thoth.locale";

export type LocaleState = {
  locale: Locale;
  setLocale: (locale: Locale) => Promise<void>;
  t: (key: MessageKey, values?: Values) => string;
  plural: (key: PluralKey, count: number, values?: Values) => string;
  day: (iso: string) => string;
  duration: (seconds: number) => string;
  number: (value: number) => string;
};

const LocaleContext = createContext<LocaleState | null>(null);

function stored(): Locale | null {
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return LOCALES.includes(value as Locale) ? (value as Locale) : null;
  } catch {
    return null;
  }
}

function remember(locale: Locale): void {
  try {
    localStorage.setItem(STORAGE_KEY, locale);
  } catch {
    // Storage can be blocked; the choice still holds for this page.
  }
}

/**
 * The language comes from the user's saved choice, else this browser's, else its language.
 * A change applies at once; `save` stores it for the user, and a failed save keeps it local.
 */
export function LocaleProvider({
  serverLocale = null,
  save,
  children,
}: {
  serverLocale?: Locale | null;
  save?: (locale: Locale) => Promise<void>;
  children: ReactNode;
}) {
  // A choice made here wins; until then the saved one, then this browser's.
  const [chosen, setChosen] = useState<Locale | null>(null);
  const [fallback] = useState<Locale>(() => stored() ?? browserLocale(navigator.languages ?? []));
  const locale = chosen ?? serverLocale ?? fallback;

  useEffect(() => {
    document.documentElement.lang = locale;
  }, [locale]);

  const setLocale = useCallback(
    async (next: Locale) => {
      setChosen(next);
      remember(next);
      if (!save) return;
      try {
        await save(next);
      } catch {
        // The server is away or the caller has no user: this browser keeps the choice.
      }
    },
    [save],
  );

  const value = useMemo<LocaleState>(
    () => ({
      locale,
      setLocale,
      t: (key, values) => translate(locale, key, values),
      plural: (key, count, values) => plural(locale, key, count, values),
      day: (iso) => formatDay(locale, iso),
      duration: (seconds) => formatDuration(locale, seconds),
      number: (value) => formatNumber(locale, value),
    }),
    [locale, setLocale],
  );

  return <LocaleContext.Provider value={value}>{children}</LocaleContext.Provider>;
}

export function useLocale(): LocaleState {
  const state = useContext(LocaleContext);
  if (!state) throw new Error("useLocale must be used inside <LocaleProvider>");
  return state;
}
