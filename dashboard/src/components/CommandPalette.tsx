// ⌘K: go to a page, project or recent run, or switch the language (DESIGN §4; restyle D5).
// Navigation only: full-text search is out of scope (D5).
import { Dialog } from "@base-ui/react/dialog";
import { FolderOpen, Languages, Search } from "lucide-react";
import { useEffect, useMemo, useState, type ComponentType, type ReactNode } from "react";

import type { Project, WorkflowRun } from "@/api/control-plane";
import { StatusPill } from "@/components/RunProgress";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";

export type PaletteLink = { path: string; label: string; icon: ComponentType<{ className?: string }> };

type Item = { id: string; group: string; label: string; lead: ReactNode; run: () => void };

export function CommandPalette({
  pages,
  projects,
  runs,
  onNavigate,
  onProject,
}: {
  pages: PaletteLink[];
  projects: Project[];
  runs: WorkflowRun[];
  onNavigate: (path: string) => void;
  onProject: (id: string) => void;
}) {
  const { locale, setLocale, t } = useLocale();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const items = useMemo(() => {
    const all: Item[] = [
      ...runs.slice(0, 5).map((run) => ({
        id: `run:${run.workflow_id}`,
        group: t("palette.runs"),
        label: run.source.display_url,
        lead: <StatusPill status={run.status} />,
        run: () => onNavigate(`/workflows/${encodeURIComponent(run.workflow_id)}`),
      })),
      ...pages.map(({ path, label, icon: Icon }) => ({
        id: `page:${path}`,
        group: t("palette.pages"),
        label,
        lead: <Icon className="size-4 text-muted-ink" />,
        run: () => onNavigate(path),
      })),
      ...projects.map((project) => ({
        id: `project:${project.project_id}`,
        group: t("palette.projects"),
        label: project.name,
        lead: <FolderOpen className="size-4 text-muted-ink" />,
        run: () => onProject(project.project_id),
      })),
      {
        id: "language",
        group: t("palette.actions"),
        label: t("palette.switchLanguage"),
        lead: <Languages className="size-4 text-muted-ink" />,
        run: () => void setLocale(locale === "en" ? "id" : "en"),
      },
    ];
    const wanted = query.trim().toLowerCase();
    return wanted ? all.filter((item) => item.label.toLowerCase().includes(wanted)) : all;
  }, [runs, pages, projects, query, locale, setLocale, onNavigate, onProject, t]);

  const close = (next: boolean) => {
    setOpen(next);
    if (!next) {
      setQuery("");
      setActive(0);
    }
  };
  const choose = (item: Item | undefined) => {
    if (!item) return;
    close(false);
    item.run();
  };

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="flex h-11 w-full max-w-[584px] items-center gap-3 rounded-md border border-hairline bg-well px-4 text-sm text-faint hover:bg-surface"
      >
        <Search aria-hidden="true" className="size-4" />
        <span className="flex-1 truncate text-left">{t("topbar.search")}</span>
        <kbd className="rounded border border-hairline px-1.5 font-mono text-[11px]">⌘K</kbd>
      </button>
      <Dialog.Root open={open} onOpenChange={close}>
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 bg-black/50" />
          <Dialog.Popup className="fixed top-[12vh] left-1/2 w-[min(640px,calc(100vw-32px))] -translate-x-1/2 overflow-hidden rounded-[10px] border border-hairline bg-raised shadow-xl">
            <Dialog.Title className="sr-only">{t("palette.title")}</Dialog.Title>
            <div className="flex items-center gap-3 border-b border-hairline px-5 py-4">
              <Search aria-hidden="true" className="size-4 text-muted-ink" />
              <input
                autoFocus
                aria-label={t("palette.title")}
                placeholder={t("palette.placeholder")}
                value={query}
                onChange={(event) => {
                  setQuery(event.target.value);
                  setActive(0);
                }}
                onKeyDown={(event) => {
                  if (event.key === "ArrowDown") setActive((index) => Math.min(index + 1, items.length - 1));
                  else if (event.key === "ArrowUp") setActive((index) => Math.max(index - 1, 0));
                  else if (event.key === "Enter") choose(items[active]);
                  else return;
                  event.preventDefault();
                }}
                className="flex-1 bg-transparent text-[15px] text-ink outline-none placeholder:text-faint"
              />
            </div>
            <ul role="listbox" aria-label={t("palette.title")} className="max-h-[60vh] overflow-y-auto py-2">
              {items.length === 0 && (
                <li className="px-5 py-6 text-sm text-muted-ink">{t("palette.empty", { query: query.trim() })}</li>
              )}
              {items.map((item, index) => (
                <li key={item.id} role="presentation">
                  {(index === 0 || items[index - 1].group !== item.group) && (
                    <p className="px-5 pt-3 pb-1 text-xs text-faint">{item.group}</p>
                  )}
                  <button
                    type="button"
                    role="option"
                    aria-selected={index === active}
                    onMouseEnter={() => setActive(index)}
                    onClick={() => choose(item)}
                    className={cn(
                      "flex w-full items-center gap-3 px-5 py-2.5 text-left text-sm text-ink",
                      index === active && "bg-surface",
                    )}
                  >
                    {item.lead}
                    <span className="truncate">{item.label}</span>
                  </button>
                </li>
              ))}
            </ul>
            <p className="border-t border-hairline px-5 py-2.5 text-xs text-faint">{t("palette.footer")}</p>
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
    </>
  );
}
