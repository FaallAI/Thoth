// New run (DESIGN §8.2): the link with its platform detected live, then the options.
import { Dialog } from "@base-ui/react/dialog";
import { X } from "lucide-react";
import { useEffect, useRef, useState, type SyntheticEvent } from "react";

import { PlanLimitError, type ControlPlaneClient, type Project, type StylePreset, type WorkflowRequest } from "@/api/control-plane";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Button } from "@/components/ui/button";
import { ALL_PROJECTS } from "@/lib/active-project";
import { LOCALES } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { detectPlatform, PLATFORM_NAMES } from "@/lib/platforms";

export type NewRunClient = Pick<ControlPlaneClient, "listStylePresets" | "startProjectWorkflow">;

const FIELD = "h-11 w-full rounded-md border border-hairline bg-well px-3 text-sm text-ink";

/**
 * Starts a run in the active project, or in a project chosen here when the list shows all of
 * them. A failed start may still have started the run (a 503 can come after it), so a retry
 * of the same request reuses its idempotency key and the server returns that run, not a twin.
 */
export function NewRunDialog({
  client,
  open,
  onOpenChange,
  projectId,
  projects,
  initialUrl = "",
  onStarted,
}: {
  client: NewRunClient;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  projectId: string | null;
  projects: Project[];
  initialUrl?: string;
  onStarted: (workflowId: string) => void;
}) {
  const { t } = useLocale();
  const [url, setUrl] = useState(initialUrl);
  const [styles, setStyles] = useState<StylePreset[]>([]);
  const [style, setStyle] = useState("");
  const [review, setReview] = useState(true);
  const [language, setLanguage] = useState("id");
  const chosen = projectId && projectId !== ALL_PROJECTS ? projectId : "";
  const [target, setTarget] = useState(chosen);
  const [error, setError] = useState<"failed" | "limit" | "styles" | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const attempt = useRef<{ body: string; key: string } | null>(null);

  useEffect(() => {
    if (open) {
      setUrl(initialUrl);
      setTarget(chosen);
      setError(null);
    }
  }, [open, initialUrl, chosen]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    client.listStylePresets().then(
      (presets) => {
        if (!live) return;
        setStyles(presets);
        setStyle((current) => current || presets[0]?.preset_id || "");
      },
      () => live && setError("styles"),
    );
    return () => {
      live = false;
    };
  }, [client, open]);

  const platform = detectPlatform(url);
  const refused = url.trim() !== "" && platform === null;

  async function submit(event: SyntheticEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!platform || !target || !style) return;
    setError(null);
    setSubmitting(true);
    const request: WorkflowRequest = {
      source: { url: url.trim(), intent: "produce_video" },
      style: { preset_id: style },
      output: { format: "mp4", language },
      review: { require_publish_approval: review },
    };
    const body = JSON.stringify([target, request]);
    const key = attempt.current?.body === body ? attempt.current.key : crypto.randomUUID();
    attempt.current = { body, key };
    try {
      const { workflow_id } = await client.startProjectWorkflow(target, request, key);
      attempt.current = null;
      onOpenChange(false);
      onStarted(workflow_id);
    } catch (failure) {
      setError(failure instanceof PlanLimitError ? "limit" : "failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 max-h-[90dvh] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-[10px] bg-raised p-6 shadow-xl">
          <div className="mb-5 flex items-center justify-between">
            <Dialog.Title className="text-base font-semibold text-ink">{t("newRun.title")}</Dialog.Title>
            <Dialog.Close aria-label={t("common.close")} className="grid size-8 place-items-center rounded-md text-muted-ink hover:bg-surface">
              <X className="size-4" />
            </Dialog.Close>
          </div>
          <form className="flex flex-col gap-5" onSubmit={submit}>
            <div className="flex flex-col gap-2 text-sm text-ink">
              <label htmlFor="new-run-link">{t("newRun.link")}</label>
              <span className="relative flex items-center">
                {platform && (
                  <span className="absolute left-2 inline-flex items-center gap-1.5 rounded bg-surface px-2 py-1 text-xs text-ink">
                    <PlatformIcon platform={platform} className="size-3.5" />
                    {PLATFORM_NAMES[platform]}
                  </span>
                )}
                <input
                  id="new-run-link"
                  autoFocus
                  type="url"
                  required
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                  placeholder={t("newRun.placeholder")}
                  aria-invalid={refused || undefined}
                  aria-describedby={refused ? "new-run-refused" : undefined}
                  className={`${FIELD} ${platform ? "pl-28" : ""}`}
                />
              </span>
              {refused && (
                <span id="new-run-refused" className="text-sm text-status-failed">
                  {t("newRun.unsupported")}
                </span>
              )}
            </div>
            {!chosen && (
              <label className="flex flex-col gap-2 text-sm text-ink">
                {t("newRun.project")}
                <select required value={target} onChange={(event) => setTarget(event.target.value)} className={FIELD}>
                  <option value="">{t("newRun.chooseProject")}</option>
                  {projects.map((project) => (
                    <option key={project.project_id} value={project.project_id}>
                      {project.name}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <div className="grid gap-5 sm:grid-cols-2">
              <label className="flex flex-col gap-2 text-sm text-ink">
                {t("newRun.style")}
                <select required value={style} onChange={(event) => setStyle(event.target.value)} className={FIELD}>
                  {styles.map((preset) => (
                    <option key={preset.preset_id} value={preset.preset_id}>
                      {preset.label}
                    </option>
                  ))}
                </select>
              </label>
              <label className="flex flex-col gap-2 text-sm text-ink">
                {t("newRun.language")}
                <select value={language} onChange={(event) => setLanguage(event.target.value)} className={FIELD}>
                  {[...LOCALES].reverse().map((option) => (
                    <option key={option} value={option}>
                      {t(`language.${option}`)}
                    </option>
                  ))}
                </select>
              </label>
            </div>
            <label className="flex items-start gap-3 text-sm text-ink">
              <input type="checkbox" checked={review} onChange={(event) => setReview(event.target.checked)} className="mt-0.5 size-4 accent-copper" />
              <span>
                {t("newRun.review")}
                <span className="block text-muted-ink">{t("newRun.reviewHint")}</span>
              </span>
            </label>
            {error && (
              <p role="alert" className="text-sm text-status-failed">
                {t(error === "limit" ? "newRun.limit" : error === "styles" ? "newRun.stylesFailed" : "newRun.failed")}
                {error === "limit" && (
                  <a className="ml-2 underline" href="/billing">
                    {t("newRun.billing")}
                  </a>
                )}
              </p>
            )}
            <div className="flex justify-end">
              <Button type="submit" size="lg" disabled={submitting || !platform || !target || !style}>
                {t(submitting ? "newRun.starting" : "newRun.start")}
              </Button>
            </div>
          </form>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
