import { useEffect, useState } from "react";
import { useNavigate } from "react-router";

import type { ControlPlaneClient, EditDocumentListItem } from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { formatWhen } from "@/lib/format-time";

/** Every Studio draft of the active project, newest first; each opens by URL. */
export function StudioDocumentsPage({
  client,
  projectId,
}: {
  client: Pick<ControlPlaneClient, "listEditDocuments">;
  projectId: string;
}) {
  const navigate = useNavigate();
  const [items, setItems] = useState<EditDocumentListItem[]>();
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let live = true;
    setItems(undefined);
    setError("");
    client.listEditDocuments(projectId).then(
      (page) => {
        if (!live) return;
        setItems(page.items);
        setNext(page.next_cursor ?? null);
      },
      () => {
        if (live) setError("Drafts could not be loaded. Try again.");
      },
    );
    return () => {
      live = false;
    };
  }, [client, projectId]);

  const more = async () => {
    if (!next) return;
    try {
      const page = await client.listEditDocuments(projectId, next);
      setItems((current) => [...(current ?? []), ...page.items]);
      setNext(page.next_cursor ?? null);
    } catch {
      setError("Drafts could not be loaded. Try again.");
    }
  };

  return (
    <section className="pen-recent-runs">
      <header><h2>Studio drafts</h2></header>
      {items?.length === 0 && (
        <p className="pen-empty-runs">No Studio drafts in this project yet. Open a Content Set in Studio to start one.</p>
      )}
      <ul className="pen-managed-projects">
        {items?.map((item) => (
          <li key={item.document_id}>
            <button
              type="button"
              onClick={() => navigate(`/studio/${encodeURIComponent(projectId)}/${encodeURIComponent(item.document_id)}`)}
            >
              <span>{item.label}</span>
              <small>{`Revision ${item.revision} · ${formatWhen(item.updated_at)}`}</small>
            </button>
          </li>
        ))}
      </ul>
      {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
      {next && <Button variant="outline" onClick={() => void more()}>Load more</Button>}
    </section>
  );
}
