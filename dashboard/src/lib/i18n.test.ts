// English and Indonesian copy (DESIGN §12.1, restyle spec D2).
import { describe, expect, test } from "bun:test";

import {
  browserLocale,
  formatClock,
  formatDay,
  formatDuration,
  formatNumber,
  messages,
  plural,
  translate,
} from "./i18n";

describe("the catalogue", () => {
  test("has every key in both languages, with the same placeholders", () => {
    const english = Object.keys(messages.en).sort();
    expect(Object.keys(messages.id).sort()).toEqual(english);
    const holes = (text: string) => [...text.matchAll(/\{(\w+)\}/g)].map((match) => match[1]).sort();
    for (const key of english) {
      const name = key as keyof typeof messages.en;
      expect({ key, holes: holes(messages.id[name]) }).toEqual({ key, holes: holes(messages.en[name]) });
      expect(messages.id[name].trim()).not.toBe("");
    }
  });

  test("fills placeholders, and never assembles a sentence from fragments", () => {
    expect(translate("en", "tray.summary", { running: 2, waiting: 1 })).toBe("2 running · 1 waiting");
    expect(translate("id", "tray.summary", { running: 2, waiting: 1 })).toBe("2 berjalan · 1 menunggu");
  });
});

describe("plurals", () => {
  test("follow each language's rules", () => {
    expect(plural("en", "inbox.count", 1)).toBe("1 decision waiting");
    expect(plural("en", "inbox.count", 3)).toBe("3 decisions waiting");
    expect(plural("id", "inbox.count", 1)).toBe("1 keputusan menunggu");
    expect(plural("id", "inbox.count", 3)).toBe("3 keputusan menunggu");
  });
});

describe("formats follow the language", () => {
  const at = "2026-10-25T07:03:00Z";
  const now = new Date("2026-10-25T09:00:00Z");

  test("numbers group by locale", () => {
    expect(formatNumber("en", 1533)).toBe("1,533");
    expect(formatNumber("id", 1533)).toBe("1.533");
  });

  test("durations stay compact in both", () => {
    expect(formatDuration("en", 144)).toBe("2m 24s");
    expect(formatDuration("id", 144)).toBe("2 mnt 24 dtk");
    expect(formatDuration("en", 3_900)).toBe("1h 5m");
    expect(formatDuration("id", 3_900)).toBe("1 jam 5 mnt");
    expect(formatDuration("en", 9)).toBe("9s");
  });

  test("a day reads as today or yesterday when it is", () => {
    const zone = "UTC";
    expect(formatDay("en", at, now, zone)).toBe("Today, 07:03");
    expect(formatDay("id", at, now, zone)).toBe("Hari ini, 07.03");
    expect(formatDay("en", "2026-10-24T18:47:00Z", now, zone)).toBe("Yesterday, 18:47");
    expect(formatDay("id", "2026-10-24T18:47:00Z", now, zone)).toBe("Kemarin, 18.47");
    expect(formatDay("en", "2026-10-20T18:47:00Z", now, zone)).toBe("Oct 20, 18:47");
    expect(formatDay("id", "2026-10-20T18:47:00Z", now, zone)).toBe("20 Okt, 18.47");
  });
});

describe("the first language", () => {
  test("comes from the browser: Indonesian browsers get Indonesian, the rest English", () => {
    expect(browserLocale(["id-ID", "en-US"])).toBe("id");
    expect(browserLocale(["id"])).toBe("id");
    expect(browserLocale(["en-GB", "id-ID"])).toBe("en");
    expect(browserLocale([])).toBe("en");
  });
});

test("the duration column is a clock", () => {
  expect(formatClock(408)).toBe("06:48");
  expect(formatClock(3_723)).toBe("1:02:03");
  expect(formatClock(-4)).toBe("00:00");
});
