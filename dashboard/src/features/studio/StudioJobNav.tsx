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
          className="min-h-11 rounded-md px-3 text-sm transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring aria-[current=page]:bg-accent aria-[current=page]:font-semibold"
        >
          {t(`studio.job.${id}`)}
        </button>
      ))}
    </nav>
  );
}
