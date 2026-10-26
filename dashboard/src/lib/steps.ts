// The sentence a run-progress step reads as (run-progress spec §5, restyle R1).
import type { components } from "@/api/generated/control-plane";

import { messages, translate, type Locale, type MessageKey } from "./i18n";
import { PLATFORM_NAMES } from "./platforms";

type Step = Pick<components["schemas"]["WorkflowStep"], "code" | "stage" | "total" | "params">;

function known(key: string): key is MessageKey {
  return key in messages.en;
}

/**
 * The step's sentence in this language: ongoing for the step a stage is on, or `done` in the
 * past tense once the log has moved past it. The verdict picks its own sentence; a code this
 * dashboard does not know yet reads as its stage's label, so a newer backend never breaks it.
 */
export function stepText(locale: Locale, step: Step, done = false): string {
  const params = step.params ?? {};
  const verdict = step.code === "attribution.verdict" ? `.${params.verdict}` : "";
  const base = `step.${step.code}${verdict}`;
  const key = done && known(`${base}.done`) ? `${base}.done` : base;
  if (known(key)) {
    const platform = String(params.platform ?? "");
    return translate(locale, key, {
      ...params,
      platform: PLATFORM_NAMES[platform] ?? platform,
      total: step.total ?? "",
    });
  }
  const stage = `stage.${step.stage}`;
  return known(stage) ? translate(locale, stage) : step.stage;
}
