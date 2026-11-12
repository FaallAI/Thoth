// The workspace asset library inside Studio (spec 2026-11-13): adding an item copies it into this
// draft's own assets, so deleting it from the library later never breaks the draft.
import { useEffect, useState } from "react";

import type { ControlPlaneClient, EditorAsset, LibraryKind, WorkspaceAsset } from "@/api/control-plane";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

const KINDS: { kind: LibraryKind | "all"; label: MessageKey }[] = [
  { kind: "all", label: "library.kind.all" },
  { kind: "sfx", label: "library.kind.sfx" },
  { kind: "clip", label: "library.kind.clip" },
  { kind: "backsound", label: "library.kind.backsound" },
  { kind: "image", label: "library.kind.image" },
];

export function LibraryPanel({
  client,
  projectId,
  onAdd,
}: {
  client: Pick<ControlPlaneClient, "listLibrary" | "addLibraryItemToProject">;
  projectId: string;
  /** Places the draft's copy on the timeline; absent, the list is read-only. */
  onAdd?: (asset: EditorAsset) => void;
}) {
  const { t } = useLocale();
  const [items, setItems] = useState<WorkspaceAsset[] | null>(null);
  const [kind, setKind] = useState<LibraryKind | "all">("all");
  // The function, not the wrapper object, is stable across renders.
  const { listLibrary } = client;
  useEffect(() => {
    void listLibrary().then(setItems, () => setItems([]));
  }, [listLibrary]);
  if (!items) return null;
  const shown = items.filter((asset) => kind === "all" || asset.kind === kind);
  return (
    <section aria-label={t("library.title")} className="flex flex-col gap-2 rounded-[10px] bg-surface p-4">
      <h2 className="text-sm font-semibold text-ink">{t("library.title")}</h2>
      {items.length === 0 ? (
        <p className="text-xs text-muted-ink">
          {t("library.panelEmpty")}{" "}
          <a href="/assets" className="underline">
            {t("library.panelLink")}
          </a>
          .
        </p>
      ) : (
        <>
          <div className="flex flex-wrap gap-1">
            {KINDS.map((entry) => (
              <button
                key={entry.kind}
                type="button"
                aria-pressed={kind === entry.kind}
                className={`rounded px-2 py-0.5 text-xs ${kind === entry.kind ? "bg-raised text-ink" : "text-muted-ink"}`}
                onClick={() => setKind(entry.kind)}
              >
                {t(entry.label)}
              </button>
            ))}
          </div>
          <ul className="flex flex-col gap-1 text-sm">
            {shown.map((asset) => (
              <li key={asset.asset_id} className="flex flex-wrap items-baseline gap-2">
                <span className="text-ink">{asset.name}</span>
                <span className="text-xs text-muted-ink">{t(KINDS.find((entry) => entry.kind === asset.kind)!.label)}</span>
                {asset.duration_seconds != null ? (
                  <span className="text-xs text-muted-ink">{asset.duration_seconds.toFixed(1)} s</span>
                ) : null}
                {onAdd ? (
                  <button
                    type="button"
                    aria-label={t("library.addToDraft", { name: asset.name })}
                    className="rounded bg-raised px-2 py-0.5 text-xs text-ink"
                    onClick={() => void client.addLibraryItemToProject(projectId, asset.asset_id).then(onAdd, () => {})}
                  >
                    +
                  </button>
                ) : null}
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}
