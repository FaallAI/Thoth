// The canonical tokens of docs/DESIGN.md §5.1, measured against the contrast table of §10,
// and the F3 names that now point at them (restyle spec R1).
import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

const css = readFileSync(join(import.meta.dir, "index.css"), "utf8");
const root = css.slice(css.indexOf(":root {"), css.indexOf("}", css.indexOf(":root {")));

function token(name: string): string {
  const match = root.match(new RegExp(`--${name}:\\s*([^;]+);`));
  if (!match) throw new Error(`--${name} is not defined in :root`);
  return match[1].trim();
}

function hex(name: string): string {
  const value = token(name);
  const alias = value.match(/^var\(--([a-z0-9-]+)\)$/);
  return alias ? hex(alias[1]) : value;
}

function luminance(color: string): number {
  const channels = [1, 3, 5].map((start) => Number.parseInt(color.slice(start, start + 2), 16) / 255);
  const [r, g, b] = channels.map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(foreground: string, background: string): number {
  const [light, dark] = [luminance(hex(foreground)), luminance(hex(background))].sort((a, b) => b - a);
  return (light + 0.05) / (dark + 0.05);
}

describe("canonical tokens (DESIGN §5.1)", () => {
  test("hold the approved values", () => {
    expect([hex("bg"), hex("well"), hex("surface"), hex("raised"), hex("hairline")]).toEqual([
      "#18191b",
      "#101113",
      "#242628",
      "#2a2c2e",
      "#47494a",
    ]);
    expect([hex("ink"), hex("muted-ink"), hex("faint"), hex("copper")]).toEqual([
      "#f5f3ee",
      "#c5c6c7",
      "#8e9092",
      "#d49a79",
    ]);
    expect([
      hex("status-running"),
      hex("status-waiting"),
      hex("status-done"),
      hex("status-failed"),
      hex("status-idle"),
    ]).toEqual(["#22d3ee", "#d7af5f", "#78c69b", "#e8918f", "#6b6e70"]);
  });

  test("meet the measured contrast of §10", () => {
    expect(contrast("ink", "bg")).toBeGreaterThanOrEqual(15.8);
    expect(contrast("ink", "surface")).toBeGreaterThanOrEqual(13.6);
    expect(contrast("muted-ink", "bg")).toBeGreaterThanOrEqual(10.2);
    expect(contrast("faint", "bg")).toBeGreaterThanOrEqual(5.4);
    expect(contrast("faint", "surface")).toBeGreaterThanOrEqual(4.5);
    expect(contrast("copper", "bg")).toBeGreaterThanOrEqual(7.2);
    for (const status of ["status-running", "status-waiting", "status-done", "status-failed"]) {
      expect(contrast(status, "bg")).toBeGreaterThanOrEqual(7.4);
    }
    // Idle is for dots and bars only, never text.
    expect(contrast("status-idle", "bg")).toBeGreaterThanOrEqual(3);
  });
});

describe("F3 names migrate to the canonical meaning", () => {
  test("succeeded is done (green), never gold", () => {
    expect(token("status-succeeded")).toBe("var(--status-done)");
    expect(hex("status-succeeded")).not.toBe(hex("status-waiting"));
  });

  test("failure, idle and the shadcn roles point at the canonical tokens", () => {
    expect(token("destructive")).toBe("var(--status-failed)");
    expect(token("status-queued")).toBe("var(--status-idle)");
    expect(token("status-cancelled")).toBe("var(--status-idle)");
    expect(token("ring")).toBe("var(--copper)");
    expect(token("primary")).toBe("var(--copper)");
    expect(token("background")).toBe("var(--bg)");
    expect(token("card")).toBe("var(--surface)");
    expect(token("accent")).toBe("var(--raised)");
  });
});
