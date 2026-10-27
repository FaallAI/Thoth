import { Dialog } from "@base-ui/react/dialog";
import { useEffect, useRef, useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type StudioSourceInspection,
  type WorkflowSummary,
} from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

export type OpenInStudioClient = Pick<
  ControlPlaneClient,
  "inspectWorkflowStudioImport" | "openWorkflowInStudio" | "getStudioImportInventory"
>;

type Props = {
  client: OpenInStudioClient;
  projectId: string | null;
  workflowId: string;
  summary: WorkflowSummary | null;
  /** `resolve` is true when an item still waits for a decision in the import gate. */
  onOpen: (projectId: string, documentId: string, resolve: boolean) => void;
};

// Fixed words per known refusal; the server's own text never reaches the page.
const CODES = new Set(["content_set_unavailable", "content_set_invalid", "workflow_in_other_project"]);

function failure(error: unknown): MessageKey {
  if (!(error instanceof StudioImportRequestError)) return "studio.error.failed";
  if (error.status === null) return "studio.error.offline";
  if (error.status === 404) return "studio.error.not_found";
  if (error.status === 503) return "studio.error.unavailable";
  return error.code && CODES.has(error.code) ? (`studio.error.${error.code}` as MessageKey) : "studio.error.failed";
}

// Inventory entries with no media and a reason are the fields Studio leaves out.
type Unfinished = { key: string; leftOut: boolean };
const KEY_SHAPE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const storageKey = (project: string, workflow: string) => `thoth.studioImport.${project}.${workflow}`;

// The key of an import the server never confirmed, kept per project and run so a reload or a
// return to the page still replays it. Storage may be absent or full; memory then carries it.
function recall(project: string, workflow: string): Unfinished | null {
  try {
    const value = JSON.parse(localStorage.getItem(storageKey(project, workflow)) ?? "null") as unknown;
    const { key, leftOut } = (value ?? {}) as Partial<Unfinished>;
    return typeof key === "string" && KEY_SHAPE.test(key) && typeof leftOut === "boolean" ? { key, leftOut } : null;
  } catch {
    return null;
  }
}

function keep(project: string, workflow: string, value: Unfinished | null) {
  try {
    if (value) localStorage.setItem(storageKey(project, workflow), JSON.stringify(value));
    else localStorage.removeItem(storageKey(project, workflow));
  } catch {
    // memory still holds it for this page
  }
}

/** The server's fixed reasons in the chosen language; another reason shows as it came. */
function reasonText(t: ReturnType<typeof useLocale>["t"], label: string, reason: string): string {
  if (reason === "Figures are context, not scenes") return t("studio.reason.figures");
  if (reason === "Not captured: post card") return t("studio.reason.postCard");
  if (reason === "Not captured: profile page") return t("studio.reason.profilePage");
  const long = /^Longer than (\d+) characters$/.exec(reason);
  if (long) return t("studio.reason.tooLong", { label, limit: long[1] });
  return `${label}: ${reason}`;
}

const leftOut = (found: StudioSourceInspection) => found.items.filter((item) => item.media_kind === "none" && item.reason);

/** "Open in Studio" for a finished run: import its Content Set, or resume a draft made from it. */
export function OpenInStudio({ client, projectId, workflowId, summary, onOpen }: Props) {
  const { t, locale } = useLocale();
  const [inspection, setInspection] = useState<StudioSourceInspection | null>(null);
  // What the button is doing: reading the run (or a draft), or importing its media.
  const [busy, setBusy] = useState<"opening" | "importing" | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  // The import a POST started but never confirmed: the next click (also after a reload, via
  // `recall`) replays its key, so the server finishes that draft instead of leaving it half done.
  const pending = useRef<Unfinished | null>(null);
  // Choices and a pending import belong to one project and one run.
  useEffect(() => {
    setInspection(null);
    setError(null);
    pending.current = null;
  }, [projectId, workflowId]);
  if (summary?.status !== "succeeded" || !summary.artifacts?.some((artifact) => artifact.kind === "content_set")) {
    return null;
  }

  const attempt = async (step: () => Promise<void>) => {
    setBusy("opening");
    setError(null);
    try {
      await step();
    } catch (caught) {
      setError(failure(caught));
    } finally {
      setBusy(null);
    }
  };
  // `shownLeftOut`: the person saw fields Studio leaves out; they wait in the gate as decisions.
  const create = async (project: string, key: string, shownLeftOut: boolean) => {
    setBusy("importing");
    pending.current = { key, leftOut: shownLeftOut };
    keep(project, workflowId, pending.current);
    const result = await client.openWorkflowInStudio(project, workflowId, key);
    pending.current = null;
    keep(project, workflowId, null);
    onOpen(project, result.draft.document_id, shownLeftOut || result.items.some((item) => item.outcome === "unresolved"));
  };
  // A resumed draft opens with the gate while any of its items still waits for a decision.
  const resume = (project: string, documentId: string) =>
    attempt(async () => {
      const draft = await client.getStudioImportInventory(project, documentId);
      onOpen(project, documentId, draft.items.some((item) => item.disposition === "unresolved"));
    });
  const start = (project: string) =>
    attempt(async () => {
      const unfinished = pending.current ?? recall(project, workflowId);
      if (unfinished) return create(project, unfinished.key, unfinished.leftOut);
      const found = await client.inspectWorkflowStudioImport(project, workflowId);
      if (found.drafts?.length || leftOut(found).length) setInspection(found);
      else await create(project, crypto.randomUUID(), false);
    });

  return (
    <section className="open-in-studio" aria-label={t("studio.open")}>
      <Button disabled={!projectId || busy !== null} onClick={() => projectId && void start(projectId)}>
        {t(busy === "importing" ? "studio.importing" : busy ? "studio.opening" : "studio.open")}
      </Button>
      {!projectId && <p className="text-sm text-muted-foreground">{t("studio.chooseProject")}</p>}
      <Dialog.Root open={Boolean(inspection && projectId)} onOpenChange={(open) => !open && setInspection(null)}>
        <Dialog.Portal>
          <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
          <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(520px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-[10px] bg-raised p-6 shadow-xl">
            <Dialog.Title className="text-base font-semibold text-ink">{t("studio.open")}</Dialog.Title>
            <Dialog.Description className="mt-1 text-sm text-muted-ink">{t("studio.dialogIntro")}</Dialog.Description>
            {inspection && projectId && (
              <div className="mt-5 flex flex-col gap-4 text-sm">
                {leftOut(inspection).length > 0 && (
                  <div>
                    <p className="text-ink">{t("studio.leftOut")}</p>
                    <ul className="mt-2 flex list-disc flex-col gap-1 pl-5 text-muted-ink">
                      {leftOut(inspection).map((item) => (
                        <li key={item.item_id}>{reasonText(t, item.label, item.reason ?? "")}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {(inspection.drafts ?? []).length > 0 && (
                  <div className="flex flex-col gap-2">
                    <p className="text-ink">{t("studio.drafts")}</p>
                    {(inspection.drafts ?? []).map((draft) => (
                      <Button key={draft.document_id} variant="secondary" disabled={busy !== null} onClick={() => void resume(projectId, draft.document_id)}>
                        {t("studio.resume", { date: new Date(draft.created_at).toLocaleString(locale === "id" ? "id-ID" : "en-US") })}
                      </Button>
                    ))}
                  </div>
                )}
                {error && <p role="alert" className="text-status-failed">{t(error)}</p>}
                <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                  <Dialog.Close render={<Button variant="ghost" />}>{t("common.cancel")}</Dialog.Close>
                  <Button disabled={busy !== null} onClick={() => void attempt(() => create(projectId, crypto.randomUUID(), leftOut(inspection).length > 0))}>
                    {t(busy === "importing" ? "studio.importing" : "studio.newDraft")}
                  </Button>
                </div>
              </div>
            )}
          </Dialog.Popup>
        </Dialog.Portal>
      </Dialog.Root>
      {error && !inspection && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
    </section>
  );
}
