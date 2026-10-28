// The project's "Presets & prompts" page (DESIGN §13.1): Prompt Lab, out of the Studio editor.
import { useLocale } from "@/lib/locale";

import { PromptLab, type PromptLabClient } from "./PromptLab";
import { useStudioViewport } from "./studio_viewport";

export function PresetsPage({ client, projectId }: { client: PromptLabClient; projectId: string }) {
  const { t } = useLocale();
  // A phone edits the saved text only; proposals, locks and providers need a wider screen.
  const phone = useStudioViewport() === "phone";
  return (
    <section className="flex min-h-0 flex-col gap-4">
      <p className="text-sm text-muted-ink">{t("studio.presets.intro")}</p>
      <div className="flex min-h-[32rem] flex-col overflow-hidden rounded-[10px] bg-surface">
        <PromptLab client={client} projectId={projectId} compactTextOnly={phone} />
      </div>
    </section>
  );
}
