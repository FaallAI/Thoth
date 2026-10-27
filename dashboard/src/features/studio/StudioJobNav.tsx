import { useLocale } from "@/lib/locale";

import type { StudioJob } from "./studio_viewport";

// Studio's destinations (DESIGN §13.1); Prompt Lab lives on the project's Presets & prompts page.
const jobs: readonly StudioJob[] = ["edit", "review", "render"];

export function StudioJobNav({ selected, onSelect }: { selected: StudioJob; onSelect: (job: StudioJob) => void }) {
  const { t } = useLocale();
  return (
    <nav aria-label={t("studio.job.nav")} className="flex flex-wrap gap-1">
      {jobs.map((id) => (
        <button
          key={id}
          type="button"
          aria-current={selected === id ? "page" : undefined}
          onClick={() => onSelect(id)}
          className="min-h-11 px-3 text-sm text-muted-ink transition-colors hover:text-ink focus-visible:outline-2 focus-visible:outline-copper aria-[current=page]:font-semibold aria-[current=page]:text-ink aria-[current=page]:shadow-[inset_0_-2px_0_var(--copper)]"
        >
          {t(`studio.job.${id}`)}
        </button>
      ))}
    </nav>
  );
}
