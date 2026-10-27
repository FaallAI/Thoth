// Testing Library's render inside the language provider every translated page needs.
import { render as rawRender, type RenderOptions } from "@testing-library/react";
import type { ReactElement } from "react";

import type { Locale } from "@/lib/i18n";
import { LocaleProvider } from "@/lib/locale";

/** Renders (and re-renders) `ui` in `locale`, English unless a test asks for Indonesian. */
export function render(ui: ReactElement, { locale = "en", ...options }: RenderOptions & { locale?: Locale } = {}) {
  const wrap = (element: ReactElement) => <LocaleProvider serverLocale={locale}>{element}</LocaleProvider>;
  const result = rawRender(wrap(ui), options);
  return { ...result, rerender: (next: ReactElement) => result.rerender(wrap(next)) };
}
