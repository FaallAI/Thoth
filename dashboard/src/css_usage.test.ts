// Every class a stylesheet styles is used by a screen (restyle R7: the dead `pen*.css` rules go).
import { expect, test } from "bun:test";
import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

const SHEETS = ["pen.css", "pen-studio.css", "pen-source-accounts.css", "dashboard.css", "features/studio/studio.css"];

function sources(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) return sources(path);
    return /\.tsx?$/.test(entry.name) && !/\.test\.tsx?$/.test(entry.name) ? [path] : [];
  });
}

const code = [
  ...sources(import.meta.dir).map((path) => readFileSync(path, "utf8")),
  readFileSync(join(import.meta.dir, "..", "index.html"), "utf8"),
].join("\n");
// A class built from a template, such as `sa-dot--${status}`, is used through its prefix.
const prefixes = [...code.matchAll(/([a-zA-Z][\w-]*-)\$\{/g)].map((match) => match[1]!);

test.each(SHEETS)("%s styles only classes a screen uses", (sheet) => {
  const css = readFileSync(join(import.meta.dir, sheet), "utf8").replace(/\/\*[\s\S]*?\*\//g, "").replace(/url\([^)]*\)/g, "")
    // A class inside :not() excludes elements; an unused one there does not make the rule dead.
    .replace(/:not\([^)]*\)/g, "");
  const classes = new Set([...css.matchAll(/\.([a-zA-Z][\w-]*)/g)].map((match) => match[1]!));
  const unused = [...classes].filter(
    (name) => !code.includes(name) && !prefixes.some((prefix) => name.startsWith(prefix)),
  );
  expect(unused).toEqual([]);
});

test("a dialog form keeps its padding (a rule whose only unused class sat inside :not)", () => {
  const css = readFileSync(join(import.meta.dir, "pen.css"), "utf8");
  expect(css).toMatch(/\.pen-dialog > form\s*\{[^}]*padding:\s*24px 30px/);
});
