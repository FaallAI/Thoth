// The Studio documents list (DESIGN §13.5, screen 1): one card per draft, by state.
import { Dialog } from "@base-ui/react/dialog";
import { Clapperboard, Info, Search } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router";

import type { ControlPlaneClient, EditDocumentListItem, WorkflowRun } from "@/api/control-plane";
import { EmptyState, Skeleton } from "@/components/Feedback";
import { PageActions } from "@/components/PageActions";
import { PlatformIcon } from "@/components/PlatformIcon";
import { Button } from "@/components/ui/button";
import { useStudioOpener, type OpenInStudioClient } from "@/features/workflows/OpenInStudio";
import { formatDay, type MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { PLATFORM_NAMES } from "@/lib/platforms";
import { cn } from "@/lib/utils";

export type DocumentsClient = OpenInStudioClient &
  Pick<ControlPlaneClient, "listEditDocuments" | "createBlankDocument" | "listRuns" | "cardUrl">;

type State = EditDocumentListItem["state"];
const STATES: State[] = ["draft", "in_review", "approved", "rendering", "rendered"];

const DOT: Record<State, string> = {
  draft: "bg-status-idle",
  in_review: "bg-status-waiting",
  approved: "bg-status-done",
  rendering: "bg-status-running animate-pulse",
  rendered: "bg-status-done",
};

/** An older API sends no state: such a draft reads as a draft. */
const stateOf = (item: EditDocumentListItem): State => (STATES.includes(item.state) ? item.state : "draft");

function StatePill({ item }: { item: EditDocumentListItem }) {
  const { t } = useLocale();
  const state = stateOf(item);
  const label =
    state === "rendering" && item.render_percent != null
      ? t("studio.docs.state.renderingPercent", { percent: item.render_percent })
      : t(`studio.docs.state.${state}` as MessageKey);
  return (
    <span className="inline-flex h-6 items-center gap-1.5 rounded-full bg-raised px-2.5 text-[13px] font-medium whitespace-nowrap text-ink">
      <span aria-hidden="true" className={cn("size-2 rounded-full", DOT[state])} />
      {label}
    </span>
  );
}

/** The run's post card when it has one; a plain panel otherwise (or when the card is not ours to see). */
function Thumbnail({ src, platform }: { src: string | null; platform: string | null | undefined }) {
  const [broken, setBroken] = useState(false);
  return (
    <div className="flex aspect-[9/16] w-[88px] shrink-0 items-center justify-center overflow-hidden rounded-md bg-well md:w-full md:rounded-[10px] md:bg-surface">
      {src && !broken ? (
        <img src={src} alt="" loading="lazy" onError={() => setBroken(true)} className="size-full object-cover object-top" />
      ) : platform ? (
        <PlatformIcon platform={platform} className="size-8 text-faint" />
      ) : (
        <Clapperboard aria-hidden="true" className="size-8 text-faint" />
      )}
    </div>
  );
}

function DocumentCard({ item, projectId, client }: { item: EditDocumentListItem; projectId: string; client: DocumentsClient }) {
  const { t, locale } = useLocale();
  const platform = item.source_platform ? (PLATFORM_NAMES[item.source_platform] ?? item.source_platform) : null;
  const card = item.source_has_post_card && item.source_workflow_id ? client.cardUrl(item.source_workflow_id, "post") : null;
  return (
    <Link
      to={`/studio/${encodeURIComponent(projectId)}/${encodeURIComponent(item.document_id)}`}
      aria-label={item.label}
      // A row with a small picture on a phone (DESIGN §13.5), a 9:16 card on wider screens.
      className="group flex min-w-0 gap-3 rounded-[10px] bg-surface p-3 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-accent md:flex-col md:gap-2 md:bg-transparent md:p-0"
    >
      <Thumbnail src={card} platform={item.source_platform} />
      <div className="flex min-w-0 flex-col gap-2">
        <p className="truncate text-[15px] font-medium text-ink group-hover:underline md:mt-1">{item.label}</p>
        {platform && (
          <p className="flex min-w-0 items-center gap-1.5 text-[13px] text-muted-ink">
            <PlatformIcon platform={item.source_platform ?? ""} className="size-3.5 shrink-0" />
            <span className="truncate">
              {item.source_owner_handle
                ? t("studio.docs.source", { platform, owner: item.source_owner_handle })
                : t("studio.docs.sourceNoOwner", { platform })}
            </span>
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          <StatePill item={item} />
          <span className="text-[13px] text-faint">
            {Number.isNaN(Date.parse(item.updated_at))
              ? t("studio.docs.revisionOnly", { revision: item.revision })
              : t("studio.docs.revision", { revision: item.revision, when: formatDay(locale, item.updated_at) })}
          </span>
        </div>
      </div>
    </Link>
  );
}

/** Pick one finished run of the project; Studio then imports it as `useStudioOpener` does. */
function NewFromRunDialog({
  client,
  projectId,
  open,
  onOpenChange,
  onPick,
}: {
  client: DocumentsClient;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (workflowId: string, title: string | null) => void;
}) {
  const { t, locale } = useLocale();
  const [query, setQuery] = useState("");
  const [runs, setRuns] = useState<WorkflowRun[] | null>(null);
  const [chosen, setChosen] = useState<string | null>(null);
  useEffect(() => {
    if (!open) return;
    let live = true;
    const q = query.trim() || undefined;
    client.listRuns({ projectId, status: ["succeeded"], q }).then(
      (page) => live && setRuns(page.items),
      () => live && setRuns([]),
    );
    return () => {
      live = false;
    };
  }, [client, projectId, open, query]);

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
        <Dialog.Popup className="fixed top-1/2 left-1/2 flex max-h-[calc(100vh-64px)] w-[min(560px,calc(100vw-32px))] -translate-x-1/2 -translate-y-1/2 flex-col rounded-[10px] bg-raised p-6 shadow-xl">
          <Dialog.Title className="text-lg font-semibold text-ink">{t("studio.docs.fromRun")}</Dialog.Title>
          <Dialog.Description className="mt-1 text-sm text-muted-ink">{t("studio.fromRun.intro")}</Dialog.Description>
          <div className="relative mt-4">
            <Search aria-hidden="true" className="absolute top-3 left-3 size-4 text-faint" />
            <input
              type="search"
              aria-label={t("studio.fromRun.search")}
              placeholder={t("studio.fromRun.search")}
              value={query}
              maxLength={100}
              onChange={(event) => setQuery(event.target.value)}
              className="h-10 w-full rounded-md border border-hairline bg-well pr-3 pl-9 text-sm text-ink"
            />
          </div>
          <div role="radiogroup" aria-label={t("studio.docs.fromRun")} className="mt-3 flex min-h-0 flex-col gap-1 overflow-y-auto">
            {runs === null && <Skeleton rows={4} />}
            {runs?.length === 0 && <p className="py-6 text-center text-sm text-muted-ink">{t("studio.fromRun.none")}</p>}
            {runs?.map((run) => (
              <label
                key={run.workflow_id}
                className={cn(
                  "flex cursor-pointer items-center gap-3 rounded-md px-3 py-2.5 hover:bg-surface",
                  chosen === run.workflow_id && "bg-surface",
                )}
              >
                <input
                  type="radio"
                  name="run"
                  value={run.workflow_id}
                  checked={chosen === run.workflow_id}
                  onChange={() => setChosen(run.workflow_id)}
                  className="size-4 accent-[var(--accent)]"
                />
                {run.has_post_card ? (
                  <img src={client.cardUrl(run.workflow_id, "post")} alt="" className="size-12 shrink-0 rounded-md bg-well object-cover object-top" />
                ) : (
                  <span className="flex size-12 shrink-0 items-center justify-center rounded-md bg-well">
                    <PlatformIcon platform={run.source.platform} className="size-5 text-faint" />
                  </span>
                )}
                <span className="flex min-w-0 flex-col">
                  <span className="truncate text-sm text-ink">{run.title || t("studio.fromRun.untitled")}</span>
                  <span className="flex items-center gap-1.5 text-[13px] text-muted-ink">
                    <PlatformIcon platform={run.source.platform} className="size-3.5" />
                    {!Number.isNaN(Date.parse(run.updated_at)) &&
                      t("studio.fromRun.finished", { when: formatDay(locale, run.updated_at) })}
                  </span>
                </span>
              </label>
            ))}
          </div>
          <div className="mt-4 flex justify-end gap-2 border-t border-hairline pt-4">
            <Dialog.Close render={<Button variant="ghost" />}>{t("common.cancel")}</Dialog.Close>
            <Button disabled={!chosen} onClick={() => chosen && onPick(chosen, runs?.find((run) => run.workflow_id === chosen)?.title ?? null)}>
              {t("studio.open")}
            </Button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/** Every Studio draft of the active project, newest first; each opens by URL. */
export function StudioDocumentsPage({ client, projectId }: { client: DocumentsClient; projectId: string }) {
  const { t } = useLocale();
  const navigate = useNavigate();
  const [items, setItems] = useState<EditDocumentListItem[]>();
  const [next, setNext] = useState<string | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const [reload, setReload] = useState(0);
  const [tab, setTab] = useState<State | "all">("all");
  const [query, setQuery] = useState("");
  // Whether the project has any finished run to start from; null while unknown.
  const [hasFinished, setHasFinished] = useState<boolean | null>(null);
  const [picking, setPicking] = useState(false);
  const [blankBusy, setBlankBusy] = useState(false);
  const open = (project: string, documentId: string, resolve = false) =>
    navigate(`/studio/${encodeURIComponent(project)}/${encodeURIComponent(documentId)}${resolve ? "?resolve=1" : ""}`);
  const opener = useStudioOpener(client, open);

  useEffect(() => {
    let live = true;
    setItems(undefined);
    setError(null);
    client.listEditDocuments(projectId).then(
      (page) => {
        if (!live) return;
        setItems(page.items);
        setNext(page.next_cursor ?? null);
      },
      () => live && setError("studio.docs.error"),
    );
    return () => {
      live = false;
    };
  }, [client, projectId, reload]);

  useEffect(() => {
    let live = true;
    setHasFinished(null);
    client.listRuns({ projectId, status: ["succeeded"], q: undefined }).then(
      (page) => live && setHasFinished(page.items.length > 0),
      // Unknown is not "none": the dialog says so itself if the list fails again.
      () => live && setHasFinished(true),
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
      setError("studio.docs.error");
    }
  };

  const blank = async () => {
    setBlankBusy(true);
    setError(null);
    try {
      const created = await client.createBlankDocument(projectId);
      open(projectId, created.document_id);
    } catch {
      setError("studio.docs.blankFailed");
      setBlankBusy(false);
    }
  };

  // ponytail: filters the loaded pages only; a server-side state filter when projects grow past a few pages.
  const shown = useMemo(() => {
    const words = query.trim().toLowerCase();
    return (items ?? []).filter(
      (item) =>
        (tab === "all" || stateOf(item) === tab) &&
        (!words ||
          [item.label, item.source_title, item.source_owner_handle].some((text) => text?.toLowerCase().includes(words))),
    );
  }, [items, tab, query]);

  return (
    <section className="flex flex-col gap-6">
      <PageActions>
        <div className="flex flex-wrap items-center justify-end gap-3">
          {hasFinished === false && (
            <span className="inline-flex items-center gap-1.5 text-[13px] text-muted-ink">
              <Info aria-hidden="true" className="size-3.5" />
              {t("studio.docs.noFinished")}
            </span>
          )}
          {/* A phone watches and makes light edits; a blank draft starts on a wider screen (§13.5). */}
          <Button variant="ghost" size="lg" className="max-md:hidden" disabled={blankBusy} onClick={() => void blank()}>
            {t("studio.docs.blank")}
          </Button>
          <Button size="lg" disabled={!hasFinished || opener.busy !== null} onClick={() => setPicking(true)}>
            {t("studio.docs.fromRun")}
          </Button>
        </div>
      </PageActions>
      <NewFromRunDialog
        client={client}
        projectId={projectId}
        open={picking}
        onOpenChange={setPicking}
        onPick={(workflowId, title) => {
          setPicking(false);
          void opener.start(projectId, workflowId, title);
        }}
      />
      {opener.dialog}
      {opener.error && (
        <p role="alert" className="text-sm text-status-failed">
          {t(opener.error)}
        </p>
      )}

      {items && items.length > 0 && (
        <div className="flex flex-wrap items-center gap-3">
          <select
            aria-label={t("studio.docs.filter")}
            value={tab}
            onChange={(event) => setTab(event.target.value as State | "all")}
            className="h-10 min-w-0 flex-1 rounded-md border border-hairline bg-bg px-3 text-sm text-ink md:hidden"
          >
            {(["all", ...STATES] as const).map((key) => (
              <option key={key} value={key}>
                {t(`studio.docs.state.${key}` as MessageKey)}
              </option>
            ))}
          </select>
          <div role="group" aria-label={t("studio.docs.filter")} className="flex rounded-md bg-surface p-1 max-md:hidden">
            {(["all", ...STATES] as const).map((key) => (
              <button
                key={key}
                type="button"
                aria-pressed={tab === key}
                onClick={() => setTab(key)}
                className={cn("rounded px-3 py-1.5 text-sm whitespace-nowrap text-muted-ink", tab === key && "bg-raised text-ink")}
              >
                {t(`studio.docs.state.${key}` as MessageKey)}
              </button>
            ))}
          </div>
          <div className="relative ml-auto w-full sm:w-72" role="search">
            <Search aria-hidden="true" className="absolute top-3 left-3 size-4 text-faint" />
            <input
              type="search"
              aria-label={t("studio.docs.search")}
              placeholder={t("studio.docs.search")}
              value={query}
              maxLength={100}
              onChange={(event) => setQuery(event.target.value)}
              className="h-10 w-full rounded-md border border-hairline bg-well pr-3 pl-9 text-sm text-ink"
            />
          </div>
        </div>
      )}

      {error && (
        <p role="alert" className="text-sm text-status-failed">
          {t(error)}
        </p>
      )}
      {error === "studio.docs.error" && !items && (
        <Button variant="secondary" className="self-start" onClick={() => setReload((n) => n + 1)}>
          {t("common.retry")}
        </Button>
      )}
      {!items && !error && <Skeleton rows={4} />}
      {items?.length === 0 && (
        <EmptyState action={<Button variant="secondary" onClick={() => navigate("/workflows")}>{t("studio.docs.goRuns")}</Button>}>
          {t("studio.docs.empty")}
        </EmptyState>
      )}
      {items && items.length > 0 && shown.length === 0 && <EmptyState>{t("studio.docs.emptyFiltered")}</EmptyState>}
      {shown.length > 0 && (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3 md:gap-x-6 md:gap-y-8 xl:grid-cols-4">
          {shown.map((item) => (
            <DocumentCard key={item.document_id} item={item} projectId={projectId} client={client} />
          ))}
        </div>
      )}
      {next && (
        <Button variant="secondary" className="self-center" onClick={() => void more()}>
          {t("runs.more")}
        </Button>
      )}
    </section>
  );
}
