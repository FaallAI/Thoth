// The workspace asset library (spec 2026-11-13): SFX, clips, backsound and images every draft of
// this workspace can use. Many files upload at once; one refused file never stops the others.
import { useEffect, useMemo, useState } from "react";

import {
  controlPlaneClient,
  StudioImportRequestError,
  type ControlPlaneClient,
  type LibraryKind,
  type WorkspaceAsset,
} from "@/api/control-plane";
import { ConfirmDialog, EmptyState, Skeleton } from "@/components/Feedback";
import { Button } from "@/components/ui/button";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

type LibraryClient = Pick<
  ControlPlaneClient,
  "listLibrary" | "uploadLibraryItem" | "updateLibraryItem" | "deleteLibraryItem" | "libraryMediaUrl"
>;

const KINDS: { kind: LibraryKind | "all"; label: MessageKey }[] = [
  { kind: "all", label: "library.kind.all" },
  { kind: "sfx", label: "library.kind.sfx" },
  { kind: "clip", label: "library.kind.clip" },
  { kind: "backsound", label: "library.kind.backsound" },
  { kind: "image", label: "library.kind.image" },
];
const ACCEPT = "audio/mpeg,audio/wav,video/mp4,video/webm,image/png,image/jpeg,image/webp";
/** Uploads in flight at once. */
const PARALLEL = 3;

type Upload = { key: number; name: string; state: "busy" | "done" | MessageKey };

function failure(error: unknown): MessageKey {
  const code = error instanceof StudioImportRequestError ? error.code : null;
  if (code === "unsupported_media_type") return "library.error.type";
  if (code === "media_type_mismatch" || code === "invalid_media") return "library.error.mismatch";
  if (code === "upload_too_large") return "library.error.large";
  return "library.error.upload";
}

function tags(asset: WorkspaceAsset): string[] {
  const raw = asset.labels?.tags;
  return Array.isArray(raw) ? raw.map(String) : [];
}

/** The kinds an item may take, as the server allows them: only short audio may be an SFX. */
function kindsFor(asset: WorkspaceAsset): LibraryKind[] {
  if (asset.media_type.startsWith("image/")) return ["image"];
  if (asset.media_type.startsWith("video/")) return ["clip"];
  return (asset.duration_seconds ?? 0) <= 15 ? ["sfx", "backsound"] : ["backsound"];
}

function searchable(asset: WorkspaceAsset): string {
  const values = Object.values(asset.labels ?? {}).flatMap((value) => (Array.isArray(value) ? value : [value]));
  return [asset.name, ...values.filter((value) => typeof value === "string")].join(" ").toLowerCase();
}

function Preview({ asset, url }: { asset: WorkspaceAsset; url: string }) {
  if (asset.kind === "image") return <img src={url} alt="" className="h-16 w-16 rounded object-cover" />;
  if (asset.kind === "clip") return <video src={url} controls muted preload="metadata" className="h-24 max-w-full rounded" />;
  return <audio src={url} controls preload="none" className="h-8 w-full" />;
}

function Row({
  asset,
  client,
  selected,
  onSelect,
  onChange,
}: {
  asset: WorkspaceAsset;
  client: LibraryClient;
  selected: boolean;
  onSelect: (selected: boolean) => void;
  onChange: (asset: WorkspaceAsset) => void;
}) {
  const { t } = useLocale();
  const [name, setName] = useState(asset.name);
  const [labels, setLabels] = useState(tags(asset).join(", "));
  const [unsaved, setUnsaved] = useState(false);
  const save = (patch: Parameters<LibraryClient["updateLibraryItem"]>[1]) =>
    void client.updateLibraryItem(asset.asset_id, patch).then(
      (changed) => {
        setUnsaved(false);
        onChange(changed);
      },
      () => setUnsaved(true),
    );
  const kinds = kindsFor(asset);
  return (
    <li data-name={asset.name} className="flex flex-wrap items-center gap-3 rounded-[10px] bg-surface p-3">
      <input
        type="checkbox"
        aria-label={t("library.select", { name: asset.name })}
        checked={selected}
        onChange={(event) => onSelect(event.target.checked)}
      />
      {/* A fixed preview column, so every row's name and kind line up whatever the media. */}
      <div className="flex w-[260px] max-w-[calc(100%-2.5rem)] shrink-0 justify-center">
        <Preview asset={asset} url={client.libraryMediaUrl(asset.asset_id)} />
      </div>
      <div className="flex min-w-[200px] flex-1 basis-full flex-col gap-1 sm:basis-0">
        <input
          aria-label={t("library.name", { name: asset.name })}
          className="rounded bg-raised px-2 py-1 text-sm text-ink"
          value={name}
          onChange={(event) => setName(event.target.value)}
          onBlur={() => {
            const trimmed = name.trim();
            if (trimmed && trimmed !== asset.name) save({ name: trimmed });
          }}
        />
        <input
          aria-label={t("library.labels", { name: asset.name })}
          placeholder={t("library.labelsHint")}
          className="rounded bg-raised px-2 py-1 text-xs text-muted-ink"
          value={labels}
          onChange={(event) => setLabels(event.target.value)}
          onBlur={() => {
            const next = labels.split(",").map((tag) => tag.trim()).filter(Boolean);
            if (next.join(",") !== tags(asset).join(",")) save({ labels: { ...(asset.labels ?? {}), tags: next } });
          }}
        />
      </div>
      <div className="ml-auto flex items-center gap-2">
      <select
        aria-label={t("library.kindOf", { name: asset.name })}
        className="rounded bg-raised px-2 py-1 text-sm text-ink"
        value={asset.kind}
        disabled={kinds.length < 2}
        onChange={(event) => save({ kind: event.target.value as LibraryKind })}
      >
        {KINDS.filter((entry) => kinds.includes(entry.kind as LibraryKind)).map((entry) => (
          <option key={entry.kind} value={entry.kind}>
            {t(entry.label)}
          </option>
        ))}
      </select>
      <span className="w-12 text-right font-mono text-xs text-muted-ink">
        {asset.duration_seconds != null ? `${asset.duration_seconds.toFixed(1)} s` : ""}
      </span>
      </div>
      {unsaved ? <p className="w-full text-xs text-danger">{t("library.error.save")}</p> : null}
    </li>
  );
}

export function AssetsPage({ client = controlPlaneClient }: { client?: LibraryClient }) {
  const { t } = useLocale();
  const [items, setItems] = useState<WorkspaceAsset[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [kind, setKind] = useState<LibraryKind | "all">("all");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const { listLibrary } = client;

  useEffect(() => {
    listLibrary().then(setItems, () => setFailed(true));
  }, [listLibrary]);

  const shown = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return (items ?? []).filter(
      (asset) => (kind === "all" || asset.kind === kind) && (!needle || searchable(asset).includes(needle)),
    );
  }, [items, kind, query]);
  // Only what the filter shows is deleted: a hidden selection never goes along unseen.
  const picked = shown.filter((asset) => selected.has(asset.asset_id)).map((asset) => asset.asset_id);

  async function upload(files: File[]) {
    const start = Date.now();
    const queued = files.map((file, index) => ({ key: start + index, file }));
    setUploads((current) => [...queued.map(({ key, file }) => ({ key, name: file.name, state: "busy" as const })), ...current]);
    const mark = (key: number, state: Upload["state"]) =>
      setUploads((current) => current.map((entry) => (entry.key === key ? { ...entry, state } : entry)));
    let next = 0;
    async function worker() {
      while (next < queued.length) {
        const { key, file } = queued[next++]!;
        try {
          const asset = await client.uploadLibraryItem(file);
          setItems((current) => [asset, ...(current ?? []).filter((entry) => entry.asset_id !== asset.asset_id)]);
          mark(key, "done");
        } catch (error) {
          mark(key, failure(error));
        }
      }
    }
    await Promise.all(Array.from({ length: Math.min(PARALLEL, queued.length) }, worker));
  }

  async function removeSelected() {
    const ids = picked;
    for (const id of ids) {
      try {
        await client.deleteLibraryItem(id);
        setItems((current) => (current ?? []).filter((entry) => entry.asset_id !== id));
      } catch {
        // Kept in the list: the next reload shows whether it is still there.
      }
    }
    setSelected((current) => new Set([...current].filter((id) => !ids.includes(id))));
  }

  if (failed) return <EmptyState>{t("library.unavailable")}</EmptyState>;
  if (!items) return <Skeleton rows={4} />;
  return (
    <div className="flex max-w-[1200px] flex-col gap-6">
      <p className="-mt-4 text-sm text-muted-ink">{t("library.subtitle")}</p>
      <label
        className="flex cursor-pointer flex-col items-center gap-2 rounded-[10px] border border-dashed border-hairline p-6 text-sm text-muted-ink"
        onDragOver={(event) => event.preventDefault()}
        onDrop={(event) => {
          event.preventDefault();
          void upload([...event.dataTransfer.files]);
        }}
      >
        <span className="font-semibold text-ink">{t("library.upload")}</span>
        <span>{t("library.uploadHint")}</span>
        <input
          type="file"
          multiple
          accept={ACCEPT}
          aria-label={t("library.upload")}
          className="sr-only"
          onChange={(event) => {
            const files = [...(event.target.files ?? [])];
            event.target.value = "";
            void upload(files);
          }}
        />
      </label>
      {uploads.length > 0 ? (
        <ul aria-label={t("library.uploads")} className="flex flex-col gap-1 text-sm">
          {uploads.map((entry) => (
            <li key={entry.key} className="flex flex-wrap gap-2">
              <span className="text-ink">{entry.name}</span>
              <span className={entry.state === "busy" || entry.state === "done" ? "text-muted-ink" : "text-danger"}>
                {t(entry.state === "busy" ? "library.uploading" : entry.state === "done" ? "library.uploaded" : entry.state)}
              </span>
            </li>
          ))}
        </ul>
      ) : null}
      <div className="flex flex-wrap items-center gap-2">
        {KINDS.map((entry) => (
          <Button
            key={entry.kind}
            size="sm"
            variant={kind === entry.kind ? "default" : "ghost"}
            aria-pressed={kind === entry.kind}
            onClick={() => setKind(entry.kind)}
          >
            {t(entry.label)}
          </Button>
        ))}
        <input
          type="search"
          aria-label={t("library.search")}
          placeholder={t("library.search")}
          className="w-full rounded bg-raised px-3 py-1.5 text-sm text-ink sm:ml-auto sm:w-auto sm:min-w-[200px]"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <Button variant="destructive" size="sm" disabled={picked.length === 0} onClick={() => setConfirming(true)}>
          {t("library.deleteSelected", { count: picked.length })}
        </Button>
      </div>
      {items.length === 0 ? (
        <EmptyState>{t("library.empty")}</EmptyState>
      ) : (
        <ul aria-label={t("library.title")} className="flex flex-col gap-2">
          {shown.map((asset) => (
            <Row
              key={asset.asset_id}
              asset={asset}
              client={client}
              selected={selected.has(asset.asset_id)}
              onSelect={(on) =>
                setSelected((current) => {
                  const next = new Set(current);
                  if (on) next.add(asset.asset_id);
                  else next.delete(asset.asset_id);
                  return next;
                })
              }
              onChange={(changed) =>
                setItems((current) => (current ?? []).map((entry) => (entry.asset_id === changed.asset_id ? changed : entry)))
              }
            />
          ))}
        </ul>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("library.deleteTitle", { count: picked.length })}
        description={t("library.deleteBody")}
        confirmLabel={t("library.deleteConfirm")}
        onConfirm={() => void removeSelected()}
        danger
      />
    </div>
  );
}
