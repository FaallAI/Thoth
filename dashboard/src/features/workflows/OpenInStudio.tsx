import { useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type StudioSourceInspection,
  type WorkflowSummary,
} from "@/api/control-plane";
import { Button } from "@/components/ui/button";

export type OpenInStudioClient = Pick<ControlPlaneClient, "inspectWorkflowStudioImport" | "openWorkflowInStudio">;

type Props = {
  client: OpenInStudioClient;
  projectId: string | null;
  workflowId: string;
  summary: WorkflowSummary | null;
  /** `resolve` is true when an item still waits for a decision in the import gate. */
  onOpen: (projectId: string, documentId: string, resolve: boolean) => void;
};

// Fixed words per known refusal; the server's own text never reaches the page.
const MESSAGES: Record<string, string> = {
  content_set_unavailable: "This run has no Content Set to open yet.",
  content_set_invalid: "Studio cannot read this run's Content Set.",
  workflow_in_other_project: "This run belongs to another project. Switch to that project to open it.",
};
const FALLBACK = "Studio could not open this run. Try again.";

function failure(error: unknown): string {
  if (!(error instanceof StudioImportRequestError)) return FALLBACK;
  if (error.status === null) return "Offline — reconnect and try again.";
  if (error.status === 404) return "This run was not found in this workspace.";
  if (error.status === 503) return "Studio is not available right now. Try again later.";
  return (error.code && MESSAGES[error.code]) || FALLBACK;
}

// Inventory entries with no media and a reason are the fields Studio leaves out.
const leftOut = (found: StudioSourceInspection) => found.items.filter((item) => item.media_kind === "none" && item.reason);

/** "Open in Studio" for a finished run: import its Content Set, or resume a draft made from it. */
export function OpenInStudio({ client, projectId, workflowId, summary, onOpen }: Props) {
  const [inspection, setInspection] = useState<StudioSourceInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if (summary?.status !== "succeeded" || !summary.artifacts?.some((artifact) => artifact.kind === "content_set")) {
    return null;
  }

  const attempt = async (step: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await step();
    } catch (caught) {
      setError(failure(caught));
    } finally {
      setBusy(false);
    }
  };
  // A fresh key per Create: a deliberate second draft must not replay the first.
  const create = async (project: string) => {
    const result = await client.openWorkflowInStudio(project, workflowId, crypto.randomUUID());
    onOpen(project, result.draft.document_id, result.items.some((item) => item.outcome === "unresolved"));
  };
  const start = (project: string) =>
    attempt(async () => {
      const found = await client.inspectWorkflowStudioImport(project, workflowId);
      if (found.drafts?.length || leftOut(found).length) setInspection(found);
      else await create(project);
    });

  return (
    <section className="open-in-studio" aria-label="Open in Studio">
      <Button disabled={!projectId || busy} onClick={() => projectId && void start(projectId)}>
        {busy ? "Importing media…" : "Open in Studio"}
      </Button>
      {!projectId && <p className="text-sm text-muted-foreground">Choose a project first.</p>}
      {inspection && projectId && (
        <div className="open-in-studio-choice">
          {leftOut(inspection).length > 0 && (
            <>
              <p className="text-sm">Studio will not include:</p>
              <ul className="text-sm">
                {leftOut(inspection).map((item) => (
                  <li key={item.item_id}>{`${item.label}: ${item.reason}`}</li>
                ))}
              </ul>
            </>
          )}
          {(inspection.drafts ?? []).map((draft) => (
            <Button key={draft.document_id} variant="outline" disabled={busy} onClick={() => onOpen(projectId, draft.document_id, false)}>
              {`Resume draft from ${new Date(draft.created_at).toLocaleString()}`}
            </Button>
          ))}
          <Button disabled={busy} onClick={() => void attempt(() => create(projectId))}>Create new draft</Button>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
