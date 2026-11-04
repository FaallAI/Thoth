// The project's "Presets & prompts" page (DESIGN §13.1): Prompt Lab, out of the Studio editor.
import { useLocale } from "@/lib/locale";

import type { ControlPlaneClient } from "@/api/control-plane";

import { PromptLab, type PromptLabClient } from "./PromptLab";
import { NarrationPresetForm } from "./script/NarrationPresetForm";
import { useStudioViewport } from "./studio_viewport";

export function PresetsPage({
  client,
  projectId,
  narration,
}: {
  client: PromptLabClient;
  projectId: string;
  /** The narration preset (spec 2026-10-31); absent, the page shows Prompt Lab only. */
  narration?: Pick<ControlPlaneClient, "getNarrationPreset" | "saveNarrationPreset">;
}) {
  const { t } = useLocale();
  // A phone edits the saved text only; proposals, locks and providers need a wider screen.
  const phone = useStudioViewport() === "phone";
  return (
    <section className="flex min-h-0 flex-col gap-4">
      <p className="text-sm text-muted-ink">{t("studio.presets.intro")}</p>
      {narration ? <NarrationPresetForm client={narration} projectId={projectId} /> : null}
      <div className="flex min-h-[32rem] flex-col overflow-hidden rounded-[10px] bg-surface">
        <PromptLab client={client} projectId={projectId} compactTextOnly={phone} />
      </div>
    </section>
  );
}
