// The sentence a run-progress step reads as (run-progress spec §5, restyle R1).
import type { components } from "@/api/generated/control-plane";

import { messages, translate, type Locale, type MessageKey } from "./i18n";

type Step = Pick<components["schemas"]["WorkflowStep"], "code" | "stage" | "total" | "params">;

/** Platform names are proper nouns, the same in both languages. */
const PLATFORMS: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  x: "X",
  youtube: "YouTube",
  threads: "Threads",
};

function known(key: string): key is MessageKey {
  return key in messages.en;
}

/**
 * The step's sentence in this language. The verdict picks its own sentence; a code this
 * dashboard does not know yet reads as its stage's label, so a newer backend never breaks it.
 */
export function stepText(locale: Locale, step: Step): string {
  const params = step.params ?? {};
  const verdict = step.code === "attribution.verdict" ? `.${params.verdict}` : "";
  const key = `step.${step.code}${verdict}`;
  if (known(key)) {
    const platform = String(params.platform ?? "");
    return translate(locale, key, {
      ...params,
      platform: PLATFORMS[platform] ?? platform,
      total: step.total ?? "",
    });
  }
  const stage = `stage.${step.stage}`;
  return known(stage) ? translate(locale, stage) : step.stage;
}
