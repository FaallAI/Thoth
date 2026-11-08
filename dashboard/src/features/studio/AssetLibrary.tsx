import { useLocale } from "@/lib/locale";
import { useEffect, useRef, useState, type RefObject } from "react";

import type { ControlPlaneClient, EditorAsset } from "@/api/control-plane";
import type { MessageKey } from "@/lib/i18n";

import { failure } from "./StudioImportGate";
import { Thumbnail } from "./story/MaterialsPanel";
import { numberRepeats, type AssetKind } from "./studio_labels";
import { ASSET_DRAG_TYPE } from "./timeline_domain";

const FILTERS = ["all", "video", "image", "audio"] as const;
type Filter = (typeof FILTERS)[number];

/** One page at a time: the library never pulls a whole project into memory. */
export const ASSET_PAGE_LIMIT = 20;

type Props = {
  client: Pick<ControlPlaneClient, "listEditorAssets" | "createEditorPreviewCapability">;
  projectId: string;
  /**
   * The editor's document generation. Every response compares against it, so a
   * page or capability that arrives after a document switch is dropped.
   */
  generationRef: RefObject<number>;
  onAssets: (assets: EditorAsset[], replace: boolean) => void;
  /** Absent on a view-only Timeline (below 1024): rows offer preview only. */
  onAdd?: (asset: EditorAsset) => void;
  onPreviewSource: (assetId: string, previewUrl: string) => void;
  /** A row's human name and detail line (spec 2026-11-01); absent, a row falls back to its id. */
  describe?: (asset: EditorAsset) => { label: string; detail: string; kind?: AssetKind };
  /** Preview URLs by asset id, the same the player draws from. */
  previews?: Record<string, string>;
  /** What the draft uses: pages keep loading until these are in, so they can list first. */
  wanted?: string[];
  /** Absent, or on a view-only Timeline, nothing can be uploaded from here. */
  upload?: (file: File) => Promise<EditorAsset>;
};

const UPLOAD_TYPES = "video/mp4,video/webm,image/jpeg,image/png,image/webp,audio/mpeg,audio/wav";

/** Pages may overlap, so one asset keeps one row: first seen, newest projection. */
function mergeById(current: EditorAsset[], page: EditorAsset[]): EditorAsset[] {
  const merged = new Map(current.map((asset) => [asset.asset_id, asset]));
  for (const asset of page) merged.set(asset.asset_id, asset);
  return [...merged.values()];
}

const action =
  "rounded border border-border px-2 py-0.5 text-[0.7rem] transition-colors hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-40";

export function AssetLibrary({
  client,
  projectId,
  generationRef,
  onAssets,
  onAdd,
  onPreviewSource,
  describe,
  previews,
  wanted,
  upload,
}: Props) {
  const { t } = useLocale();
  const [uploading, setUploading] = useState(false);
  const [uploadFailure, setUploadFailure] = useState<MessageKey>();
  const [assets, setAssets] = useState<EditorAsset[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [loading, setLoading] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<Filter>("all");
  // Callbacks are read through a ref so a fresh inline handler never re-runs the load.
  const callbacks = useRef({ onAssets, onPreviewSource });
  callbacks.current = { onAssets, onPreviewSource };

  const load = (from?: string) => {
    const generation = generationRef.current;
    setLoading(true);
    void client
      .listEditorAssets(projectId, from, ASSET_PAGE_LIMIT)
      .then((page) => {
        if (generation !== generationRef.current) return;
        setAssets((current) => (from ? mergeById(current, page.assets) : page.assets));
        setCursor(page.next_cursor ?? null);
        setFailed(false);
        callbacks.current.onAssets(page.assets, !from);
      })
      .catch(() => generation === generationRef.current && setFailed(true))
      .finally(() => generation === generationRef.current && setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- one load per project or retry.
  }, [attempt, client, projectId]);

  const stillMissing = wanted?.some((assetId) => !assets.some((asset) => asset.asset_id === assetId));
  useEffect(() => {
    if (stillMissing && cursor && !loading && !failed) load(cursor);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- load reads the same state.
  }, [stillMissing, cursor, loading, failed]);

  const send = (file: File) => {
    if (!upload) return;
    const generation = generationRef.current;
    setUploading(true);
    setUploadFailure(undefined);
    void upload(file)
      .then((added) => {
        if (generation !== generationRef.current) return;
        setAssets((current) => mergeById([added], current));
        callbacks.current.onAssets([added], false);
      })
      .catch((error: unknown) => setUploadFailure(failure(error, "studio.inventory.uploadFailed")))
      .finally(() => setUploading(false));
  };

  const preview = (assetId: string) => {
    const generation = generationRef.current;
    void client
      .createEditorPreviewCapability(projectId, assetId)
      .then((capability) => {
        if (generation !== generationRef.current) return;
        // The locator goes straight to the player; it is never rendered or stored.
        callbacks.current.onPreviewSource(assetId, capability.preview_url);
      })
      .catch(() => undefined);
  };

  const rows = assets
    .filter((asset) => asset.validation_state === "ready")
    .map((asset): { asset: EditorAsset; label: string; detail: string; kind?: AssetKind } => ({
      asset,
      ...(describe?.(asset) ?? {
        label: asset.asset_id,
        detail: `${asset.kind}${asset.duration_in_frames ? ` · ${asset.duration_in_frames}f` : ""}`,
      }),
    }))
    // What this draft uses comes first; what nothing names (another draft's upload) comes last.
    .sort((a, b) => Number(a.kind === "upload") - Number(b.kind === "upload"));
  const labels = numberRepeats(rows.map((row) => row.label));
  // Search and the type filter narrow what shows, never what loads (spec 2026-11-08 §6).
  const needle = query.trim().toLowerCase();
  const shown = rows
    .map((row, index) => ({ ...row, name: labels[index]! }))
    .filter((row) => (filter === "all" || row.asset.kind === filter) && (!needle || row.name.toLowerCase().includes(needle)));

  return (
    <section className="min-h-0 overflow-auto border-r border-border bg-card/60 p-3" aria-label="Asset library">
      <h2 className="mb-2 font-mono text-xs font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        {t("studio.assets.title")}
      </h2>
      {upload && onAdd ? (
        <div className="mb-2 space-y-1">
          <label className={`${action} inline-block cursor-pointer focus-within:ring-2 focus-within:ring-ring`}>
            {t("studio.inventory.upload")}
            <input
              type="file"
              className="sr-only"
              accept={UPLOAD_TYPES}
              disabled={uploading}
              onChange={(event) => {
                const file = event.currentTarget.files?.[0];
                event.currentTarget.value = "";
                if (file) send(file);
              }}
            />
          </label>
          {uploadFailure ? (
            <p role="alert" className="text-xs text-destructive">
              {t(uploadFailure)}
            </p>
          ) : null}
        </div>
      ) : null}
      <div className="mb-2 space-y-1">
        <input
          type="search"
          aria-label={t("studio.assets.search")}
          placeholder={t("studio.assets.search")}
          className="w-full rounded border border-border bg-background/40 px-2 py-1 text-xs"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
        />
        <div role="group" aria-label={t("studio.assets.filter")} className="flex flex-wrap gap-1">
          {FILTERS.map((value) => (
            <button
              key={value}
              type="button"
              className={`${action} ${filter === value ? "bg-accent" : ""}`}
              aria-pressed={filter === value}
              onClick={() => setFilter(value)}
            >
              {t(`studio.assets.filter.${value}`)}
            </button>
          ))}
        </div>
      </div>
      {failed ? (
        <div role="alert" className="space-y-2 text-xs text-destructive">
          <p>{t("studio.assets.unavailable")}</p>
          <button
            type="button"
            className={action}
            onClick={() => setAttempt((value) => value + 1)}
          >
            {t("studio.assets.retry")}
          </button>
        </div>
      ) : (
        <>
          <ul className="space-y-2">
            {shown.map(({ asset, detail, name }) => (
              <li
                key={asset.asset_id}
                className={`flex gap-2 rounded border border-border bg-background/40 p-2 text-xs ${onAdd ? "cursor-grab" : ""}`}
                draggable={Boolean(onAdd)}
                onDragStart={(event) => {
                  event.dataTransfer.setData(ASSET_DRAG_TYPE, asset.asset_id);
                  event.dataTransfer.effectAllowed = "copy";
                }}
              >
                <Thumbnail kind={asset.kind} preview={previews?.[asset.asset_id]} />
                <div className="min-w-0 flex-1">
                <span className="block font-medium break-words text-foreground">{name}</span>
                <span className="block text-muted-foreground">{detail}</span>
                <div className="mt-1 flex flex-wrap gap-1">
                  {onAdd ? (
                    <button
                      type="button"
                      className={action}
                      aria-label={t("studio.assets.addNamed", { label: name })}
                      onClick={() => onAdd(asset)}
                    >
                      {t("studio.assets.add")}
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={action}
                    aria-label={t("studio.assets.previewNamed", { label: name })}
                    onClick={() => preview(asset.asset_id)}
                  >
                    {t("studio.assets.preview")}
                  </button>
                </div>
                </div>
              </li>
            ))}
          </ul>
          {shown.length === 0 && !loading ? (
            <p className="text-xs text-muted-foreground">{t("studio.assets.none")}</p>
          ) : null}
          {cursor ? (
            <button
              type="button"
              className={`${action} mt-2`}
              disabled={loading}
              onClick={() => load(cursor)}
            >
              {t("studio.assets.more")}
            </button>
          ) : null}
        </>
      )}
    </section>
  );
}
