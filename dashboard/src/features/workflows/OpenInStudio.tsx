import { Dialog } from "@base-ui/react/dialog";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type StudioSourceInspection,
  type WorkflowSummary,
} from "@/api/control-plane";
import { StageStepper } from "@/components/RunProgress";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { useNow } from "@/lib/use-now";

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

/** The server's fixed reasons in the chosen language; another reason shows as it came (after its label, unless the row already shows it). */
export function reasonText(t: ReturnType<typeof useLocale>["t"], label: string, reason: string, named = false): string {
  if (reason === "Figures are context, not scenes") return t("studio.reason.figures");
  if (reason === "Not placed: no room in the reaction beat") return t("studio.reason.notPlaced");
  if (reason === "Not captured: post card") return t("studio.reason.postCard");
  if (reason === "Not captured: profile page") return t("studio.reason.profilePage");
  const long = /^Longer than (\d+) characters$/.exec(reason);
  if (long) return t("studio.reason.tooLong", { label, limit: long[1] });
  return named ? reason : `${label}: ${reason}`;
}

const leftOut = (found: StudioSourceInspection) => found.items.filter((item) => item.media_kind === "none" && item.reason);

type Busy = "opening" | "importing" | null;

/**
 * Opens a finished run's Content Set in Studio: import it, or resume a draft made from it.
 * `dialog` asks first when the run already has drafts or Studio leaves fields out; the run
 * list's "Open in Studio" and the documents page's "New from a run" share it.
 */
export function useStudioOpener(
  client: OpenInStudioClient,
  onOpen: (projectId: string, documentId: string, resolve: boolean) => void,
) {
  const { t, locale } = useLocale();
  // The run being opened, and what opening it would import when that needs a question first.
  const [target, setTarget] = useState<{ project: string; workflow: string; title?: string | null } | null>(null);
  // When the import POST started: the progress dialog counts from it.
  const [importing, setImporting] = useState<Date | null>(null);
  const now = useNow(1_000, importing !== null);
  const [inspection, setInspection] = useState<StudioSourceInspection | null>(null);
  // What the opener is doing: reading the run (or a draft), or importing its media.
  const [busy, setBusy] = useState<Busy>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  // The import a POST started but never confirmed: the next attempt (also after a reload, via
  // `recall`) replays its key, so the server finishes that draft instead of leaving it half done.
  const pending = useRef<Unfinished | null>(null);

  // Choices and a pending import belong to one project and one run.
  const reset = useCallback(() => {
    setTarget(null);
    setInspection(null);
    setError(null);
    pending.current = null;
  }, []);

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
  const create = async (project: string, workflow: string, key: string, shownLeftOut: boolean) => {
    setBusy("importing");
    setImporting(new Date());
    pending.current = { key, leftOut: shownLeftOut };
    keep(project, workflow, pending.current);
    let result: Awaited<ReturnType<typeof client.openWorkflowInStudio>>;
    try {
      result = await client.openWorkflowInStudio(project, workflow, key);
    } finally {
      setImporting(null);
    }
    pending.current = null;
    keep(project, workflow, null);
    onOpen(project, result.draft.document_id, shownLeftOut || result.items.some((item) => item.outcome === "unresolved"));
  };
  // A resumed draft opens with the gate while any of its items still waits for a decision.
  const resume = (project: string, documentId: string) =>
    attempt(async () => {
      const draft = await client.getStudioImportInventory(project, documentId);
      onOpen(project, documentId, draft.items.some((item) => item.disposition === "unresolved"));
    });
  const start = (project: string, workflow: string, title?: string | null) => {
    if (target && (target.project !== project || target.workflow !== workflow)) pending.current = null;
    setTarget({ project, workflow, title });
    return attempt(async () => {
      const unfinished = pending.current ?? recall(project, workflow);
      if (unfinished) return create(project, workflow, unfinished.key, unfinished.leftOut);
      const found = await client.inspectWorkflowStudioImport(project, workflow);
      if (found.drafts?.length || leftOut(found).length) setInspection(found);
      else await create(project, workflow, crypto.randomUUID(), false);
    });
  };

  const dialog = (
    <Dialog.Root open={Boolean(inspection && target)} onOpenChange={(open) => !open && setInspection(null)}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(520px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-[10px] bg-raised p-6 shadow-xl">
          <Dialog.Title className="text-base font-semibold text-ink">{t("studio.open")}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-muted-ink">{t("studio.dialogIntro")}</Dialog.Description>
          {inspection && target && (
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
                    <Button key={draft.document_id} variant="secondary" disabled={busy !== null} onClick={() => void resume(target.project, draft.document_id)}>
                      {t("studio.resume", { date: new Date(draft.created_at).toLocaleString(locale === "id" ? "id-ID" : "en-US") })}
                    </Button>
                  ))}
                </div>
              )}
              {error && <p role="alert" className="text-status-failed">{t(error)}</p>}
              <div className="flex justify-end gap-2 border-t border-hairline pt-4">
                <Dialog.Close render={<Button variant="ghost" />}>{t("common.cancel")}</Dialog.Close>
                <Button
                  disabled={busy !== null}
                  onClick={() =>
                    void attempt(() => create(target.project, target.workflow, crypto.randomUUID(), leftOut(inspection).length > 0))
                  }
                >
                  {t(busy === "importing" ? "studio.importing" : "studio.newDraft")}
                </Button>
              </div>
            </div>
          )}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );

  // The import is one request that copies, probes and places every media item: the server
  // reports no per-file progress, so the dialog shows that step running and its elapsed time.
  const progress = (
    <Dialog.Root open={importing !== null}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 w-[min(520px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 rounded-[10px] bg-raised p-6 shadow-xl">
          <Dialog.Title className="text-lg font-semibold text-ink">{t("studio.progress.title")}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-muted-ink">
            {target?.title ? t("studio.progress.intro", { title: target.title }) : t("studio.progress.introUntitled")}
          </Dialog.Description>
          {importing && (
            <div className="mt-5">
              <StageStepper
                label={t("studio.progress.label")}
                now={now}
                stages={[
                  { id: "import_media", label: t("studio.progress.media"), status: "running", started_at: importing.toISOString(), finished_at: null },
                  { id: "import_ready", label: t("studio.progress.ready"), status: "queued", started_at: null, finished_at: null },
                ]}
              />
            </div>
          )}
          <p className="mt-6 border-t border-hairline pt-4 text-sm text-muted-ink">{t("studio.progress.note")}</p>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );

  // The error outside the dialog: shown only while the dialog is not.
  return {
    start,
    reset,
    busy,
    error: inspection ? null : error,
    dialog: (
      <>
        {dialog}
        {progress}
      </>
    ),
  };
}

/** "Open in Studio" for a finished run: import its Content Set, or resume a draft made from it. */
export function OpenInStudio({ client, projectId, workflowId, summary, onOpen }: Props) {
  const { t } = useLocale();
  const opener = useStudioOpener(client, onOpen);
  const { reset } = opener;
  useEffect(() => reset(), [projectId, workflowId, reset]);
  if (summary?.status !== "succeeded" || !summary.artifacts?.some((artifact) => artifact.kind === "content_set")) {
    return null;
  }
  const { busy, error } = opener;

  return (
    <section className="open-in-studio" aria-label={t("studio.open")}>
      <Button disabled={!projectId || busy !== null} onClick={() => projectId && void opener.start(projectId, workflowId, summary.title)}>
        {t(busy === "importing" ? "studio.importing" : busy ? "studio.opening" : "studio.open")}
      </Button>
      {!projectId && <p className="text-sm text-muted-foreground">{t("studio.chooseProject")}</p>}
      {opener.dialog}
      {error && <p role="alert" className="text-sm text-destructive">{t(error)}</p>}
    </section>
  );
}
