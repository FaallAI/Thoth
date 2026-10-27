// The source inventory of a Studio draft (DESIGN §13.3): every item a run collected, as it
// arrives in Studio, each attached, excluded or still waiting for that decision.
import { Dialog } from "@base-ui/react/dialog";
import { CircleAlert, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import {
  StudioImportRequestError,
  type ControlPlaneClient,
  type EditorAsset,
  type ResolveStudioImportItem,
  type StudioImportInventory,
  type StudioImportItem,
} from "@/api/control-plane";
import { Button } from "@/components/ui/button";
import { reasonText } from "@/features/workflows/OpenInStudio";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";

export type StudioImportClient = Pick<
  ControlPlaneClient,
  "getStudioImportInventory" | "resolveStudioImportItem" | "uploadEditorAsset" | "listEditorAssets"
>;

type StudioImportGateProps = {
  client: StudioImportClient;
  projectId: string;
  documentId: string;
  onOpen: (documentId: string) => void;
  onClose: () => void;
};

const ASSET_PAGE = 50;
// Pages may overlap: one asset keeps its first position.
const uniqueAssets = (list: EditorAsset[]) => [...new Map(list.map((asset) => [asset.asset_id, asset])).values()];
const UPLOAD_TYPES = { video: "video/mp4,video/webm", image: "image/jpeg,image/png,image/webp" } as const;

// Fixed words for each known refusal; the server's own text never reaches the page.
const CODES = new Set([
  "upload_too_large",
  "unsupported_media_type",
  "asset_unavailable",
  "asset_kind_mismatch",
  "attach_rejected",
  "item_not_attachable",
  "trim_exceeds_asset",
  "asset_duration_unknown",
  "main_not_attached",
  "no_room_in_reaction_beat",
]);
const known = (error: StudioImportRequestError): MessageKey | null =>
  error.code && CODES.has(error.code) ? (`studio.inventory.error.${error.code}` as MessageKey) : null;

function failure(error: unknown, fallback: MessageKey): MessageKey {
  if (!(error instanceof StudioImportRequestError)) return fallback;
  if (error.status === null) return "studio.error.offline";
  return known(error) ?? fallback;
}

const DOT = { attached: "bg-status-done", excluded: "bg-status-idle", unresolved: "bg-status-failed" } as const;

/**
 * Attach or exclude each source item the draft cannot play yet. Every decision is saved on the
 * draft at its revision; a stale revision refreshes the list instead of guessing.
 */
export function StudioImportGate({ client, projectId, documentId, onOpen, onClose }: StudioImportGateProps) {
  const { t, plural } = useLocale();
  const id = useId();
  const alertRef = useRef<HTMLParagraphElement>(null);
  const [inventory, setInventory] = useState<StudioImportInventory>();
  const [openFailed, setOpenFailed] = useState(false);
  // Ready assets load one bounded page at a time; `next` is the cursor for the page after.
  const [assets, setAssets] = useState<{ list: EditorAsset[]; next: string | null }>();
  const [assetLoad, setAssetLoad] = useState<"loading" | "failed">();
  const [attaching, setAttaching] = useState<string>();
  const [choice, setChoice] = useState<string>();
  const [alert, setAlert] = useState<MessageKey>();
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (alert) alertRef.current?.focus();
  }, [alert]);

  const open = async () => {
    setBusy(true);
    setAlert(undefined);
    setOpenFailed(false);
    try {
      setInventory(await client.getStudioImportInventory(projectId, documentId));
    } catch (error) {
      if (error instanceof StudioImportRequestError && error.status === 404) {
        setAlert("studio.inventory.gone");
        return;
      }
      setAlert(failure(error, "studio.inventory.openFailed"));
      setOpenFailed(true);
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    void open();
    // eslint-disable-next-line react-hooks/exhaustive-deps -- once, for the draft the dialog opened with.
  }, []);

  const resolve = async (item: StudioImportItem, decision: ResolveStudioImportItem["decision"]) => {
    if (!inventory) return;
    setBusy(true);
    setAlert(undefined);
    try {
      setInventory(
        await client.resolveStudioImportItem(projectId, inventory.document_id, item.item_id, {
          base_revision: inventory.revision,
          decision,
        }),
      );
      setAttaching(undefined);
    } catch (error) {
      if (!(error instanceof StudioImportRequestError && error.status === 409)) {
        setAlert(failure(error, "studio.inventory.decideFailed"));
        return;
      }
      setAlert(known(error) ?? "studio.inventory.conflict");
      try {
        setInventory(await client.getStudioImportInventory(projectId, inventory.document_id));
      } catch {
        // Keep the inventory on screen; the next decision reports its own conflict.
      }
    } finally {
      setBusy(false);
    }
  };

  const upload = async (item: StudioImportItem, file: File) => {
    setBusy(true);
    setAlert(undefined);
    let uploaded: EditorAsset;
    try {
      uploaded = await client.uploadEditorAsset(projectId, file);
    } catch (error) {
      setAlert(failure(error, "studio.inventory.uploadFailed"));
      setBusy(false);
      return;
    }
    setAssets((current) => current && { ...current, list: uniqueAssets([uploaded, ...current.list]) });
    await resolve(item, { kind: "attach_asset", asset_id: uploaded.asset_id });
  };

  const loadAssets = (cursor?: string) => {
    setAssetLoad("loading");
    client.listEditorAssets(projectId, cursor, ASSET_PAGE).then(
      (page) => {
        setAssets((current) => ({
          list: cursor && current ? uniqueAssets([...current.list, ...page.assets]) : page.assets,
          next: page.next_cursor ?? null,
        }));
        setAssetLoad(undefined);
      },
      () => setAssetLoad("failed"),
    );
  };

  const toggleAttach = (itemId: string) => {
    setAttaching((current) => (current === itemId ? undefined : itemId));
    setChoice(undefined);
    if (!assets && assetLoad === undefined) loadAssets();
  };

  const attachPanel = (item: StudioImportItem) => {
    const kind = item.media_kind === "image" ? "image" : "video";
    const kindWord = t(`studio.inventory.kind.${kind}`);
    const ready = (assets?.list ?? []).filter((asset) => asset.validation_state === "ready" && asset.kind === kind);
    const chosen = choice ?? ready[0]?.asset_id;
    return (
      <div className="col-span-full mt-2 flex flex-col gap-3 rounded-md bg-well p-3 text-sm">
        <label className="inline-flex h-9 w-fit cursor-pointer items-center rounded-md bg-raised px-3 text-ink focus-within:outline-2 focus-within:outline-copper">
          {t("studio.inventory.upload")}
          <input
            type="file"
            className="sr-only"
            accept={UPLOAD_TYPES[kind]}
            disabled={busy}
            onChange={(event) => {
              const file = event.currentTarget.files?.[0];
              event.currentTarget.value = "";
              if (file) void upload(item, file);
            }}
          />
        </label>
        {chosen ? (
          <div className="flex flex-wrap items-end gap-2">
            <div className="min-w-48 flex-1">
              <label htmlFor={`${id}-${item.item_id}-asset`} className="block text-xs text-muted-ink">
                {t("studio.inventory.readyAsset")}
              </label>
              <select
                id={`${id}-${item.item_id}-asset`}
                className="mt-1 h-9 w-full rounded-md border border-hairline bg-bg px-3 text-sm text-ink"
                value={chosen}
                disabled={busy}
                onChange={(event) => setChoice(event.target.value)}
              >
                {ready.map((asset) => (
                  <option key={asset.asset_id} value={asset.asset_id}>
                    {asset.asset_id}
                  </option>
                ))}
              </select>
            </div>
            <Button variant="secondary" disabled={busy} onClick={() => void resolve(item, { kind: "attach_asset", asset_id: chosen })}>
              {t("studio.inventory.attachSelected")}
            </Button>
          </div>
        ) : assets ? (
          <p className="text-xs text-muted-ink">
            {t(assets.next ? "studio.inventory.noneLoaded" : "studio.inventory.noneYet", { kind: kindWord })}
          </p>
        ) : null}
        {assetLoad === "loading" ? (
          <p role="status" className="text-xs text-muted-ink">
            {t("studio.inventory.assetsLoading")}
          </p>
        ) : assetLoad === "failed" ? (
          <div role="alert" className="flex flex-col items-start gap-2 text-xs text-status-failed">
            <p>{t("studio.inventory.assetsFailed")}</p>
            <Button variant="secondary" size="sm" onClick={() => loadAssets(assets?.next ?? undefined)}>
              {t("studio.inventory.assetsRetry")}
            </Button>
          </div>
        ) : assets?.next ? (
          <Button variant="ghost" size="sm" className="w-fit" onClick={() => loadAssets(assets.next ?? undefined)}>
            {t("studio.inventory.moreAssets")}
          </Button>
        ) : null}
      </div>
    );
  };

  const remaining = inventory?.items.filter((item) => item.disposition === "unresolved").length ?? 0;
  // Columns on a wide screen: number, role, item, status, actions; a phone stacks them.
  const columns = "sm:grid-cols-[2rem_9rem_minmax(0,1fr)_9rem_12rem]";

  return (
    <Dialog.Root open onOpenChange={(next) => !next && onClose()}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 z-50 bg-black/60" />
        <Dialog.Popup className="fixed inset-0 z-50 flex flex-col bg-raised text-ink outline-none sm:inset-auto sm:top-1/2 sm:left-1/2 sm:max-h-[90vh] sm:w-[min(920px,calc(100vw-48px))] sm:-translate-x-1/2 sm:-translate-y-1/2 sm:rounded-[10px] sm:shadow-xl">
          <header className="flex items-start gap-3 px-6 pt-6">
            <div className="min-w-0 flex-1">
              <Dialog.Title className="text-lg font-semibold text-ink">{t("studio.inventory.title")}</Dialog.Title>
              <Dialog.Description className="mt-1 text-sm text-muted-ink">{t("studio.inventory.intro")}</Dialog.Description>
            </div>
            <Dialog.Close render={<Button variant="ghost" size="icon" aria-label={t("common.close")} />}>
              <X aria-hidden="true" className="size-4" />
            </Dialog.Close>
          </header>
          {alert ? (
            <p
              ref={alertRef}
              role="alert"
              tabIndex={-1}
              className="mx-6 mt-4 rounded-md bg-status-failed/10 px-3 py-2 text-sm text-status-failed outline-none"
            >
              {t(alert)}
            </p>
          ) : null}
          <div className="min-h-0 flex-1 overflow-y-auto px-6 pt-4 pb-2">
            {inventory ? (
              <>
                <div aria-hidden="true" className={cn("hidden gap-x-4 border-b border-hairline pb-2 text-[13px] text-muted-ink sm:grid", columns)}>
                  <span>#</span>
                  <span>{t("studio.inventory.col.role")}</span>
                  <span>{t("studio.inventory.col.item")}</span>
                  <span>{t("studio.inventory.col.status")}</span>
                  <span />
                </div>
                <ol aria-label={t("studio.inventory.title")}>
                  {inventory.items.map((item, index) => {
                    const unresolved = item.disposition === "unresolved";
                    return (
                      <li
                        key={item.item_id}
                        aria-label={item.label}
                        className={cn(
                          "grid grid-cols-[2rem_minmax(0,1fr)] items-center gap-x-4 gap-y-1 border-b border-hairline py-3",
                          columns,
                          unresolved && item.reason && "bg-status-failed/5",
                        )}
                      >
                        <span className="font-mono text-[13px] text-faint">{index + 1}</span>
                        <span className="text-sm text-muted-ink">
                          {t(`studio.inventory.role.${item.role ?? "source"}` as MessageKey)}
                        </span>
                        <span className="col-start-2 min-w-0 sm:col-start-auto">
                          <span className="block truncate text-sm text-ink">{item.label}</span>
                          {item.reason ? (
                            <span className={cn("block text-[13px]", unresolved ? "text-status-failed" : "text-muted-ink")}>
                              {reasonText(t, item.label, item.reason, true)}
                            </span>
                          ) : null}
                        </span>
                        <span className="col-start-2 flex items-center gap-1.5 text-sm sm:col-start-auto">
                          <span aria-hidden="true" className={cn("size-2 rounded-full", DOT[item.disposition])} />
                          {t(`studio.inventory.status.${item.disposition}`)}
                        </span>
                        <span className="col-start-2 flex flex-wrap justify-end gap-2 sm:col-start-auto">
                          {unresolved ? (
                            <>
                              {item.media_kind !== "none" ? (
                                <Button
                                  variant="secondary"
                                  size="sm"
                                  aria-expanded={attaching === item.item_id}
                                  disabled={busy}
                                  onClick={() => toggleAttach(item.item_id)}
                                >
                                  {t("studio.inventory.attach")}
                                </Button>
                              ) : null}
                              <Button variant="ghost" size="sm" disabled={busy} onClick={() => void resolve(item, { kind: "exclude" })}>
                                {t("studio.inventory.exclude")}
                              </Button>
                            </>
                          ) : null}
                        </span>
                        {attaching === item.item_id && unresolved ? attachPanel(item) : null}
                      </li>
                    );
                  })}
                </ol>
              </>
            ) : openFailed ? (
              <Button variant="secondary" onClick={() => void open()}>
                {t("common.retry")}
              </Button>
            ) : alert ? null : (
              <p role="status" className="text-sm text-muted-ink">
                {t("studio.inventory.loading")}
              </p>
            )}
          </div>
          {inventory ? (
            <footer className="flex flex-wrap items-center justify-end gap-3 border-t border-hairline px-6 py-4">
              <p className={cn("mr-auto flex items-center gap-2 text-sm", remaining ? "text-ink" : "text-muted-ink")}>
                {remaining ? <CircleAlert aria-hidden="true" className="size-4 text-status-failed" /> : null}
                {remaining
                  ? plural("studio.inventory.remaining", remaining, { total: inventory.items.length })
                  : t("studio.inventory.done")}
              </p>
              <Button onClick={() => onOpen(inventory.document_id)}>{t("studio.inventory.continue")}</Button>
            </footer>
          ) : null}
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
