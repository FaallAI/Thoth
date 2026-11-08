import { useContextMenu, type MenuEntry } from "@/components/ContextMenu";
import { useState } from "react";
import { AudioLines, ChevronDown, Film, ImageIcon, Info, Quote } from "lucide-react";

import type { EditDocumentV2, EditorAsset, StudioMaterial, StudioMaterials } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

import { assetLabel, clipLabel, materialRowLabel, numberRepeats } from "../studio_labels";
import type { Beat } from "./story_beats";

/** What a dragged material carries: its item id, or `upload:<asset_id>` for a project upload. */
export const MATERIAL_DRAG_TYPE = "application/x-thoth-material";
const PAGE = 6;

type GroupId = "main" | "cards" | "footage" | "photos" | "comments" | "uploads";
const GROUP_OF: Record<NonNullable<StudioMaterial["role"]>, GroupId> = {
  main: "main",
  main_footage: "main",
  slide: "main",
  post_card: "cards",
  profile_card: "cards",
  profile_page: "cards",
  comment_card: "cards",
  footage: "footage",
  creator_footage: "footage",
  creator_photo: "photos",
  comment: "comments",
};

type Props = {
  materials: StudioMaterials | null;
  uploads: EditorAsset[];
  beats: Beat[];
  document: EditDocumentV2;
  /** Preview URLs by asset id, the same the player draws from. */
  previews: Record<string, string>;
  /** Right-click menu (spec 2026-11-08 §5.2): the beat open in the Inspector, and what the menu does. */
  openBeat?: Beat;
  onAddToOpenBeat?: (itemId: string) => void;
  onShowUse?: (frame: number) => void;
};

/** Spec 2026-10-27 §9: everything the run collected, grouped, with where it came from. */
export function MaterialsPanel({ materials, uploads, beats, document, previews, openBeat, onAddToOpenBeat, onShowUse }: Props) {
  const { t } = useLocale();
  const [query, setQuery] = useState("");
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [shown, setShown] = useState<Record<string, number>>({});
  const needle = query.trim().toLowerCase();
  const matches = (...texts: (string | null | undefined)[]) =>
    !needle || texts.some((text) => text?.toLowerCase().includes(needle));

  // A material is "used" where any visible clip of a beat draws its asset.
  const assetOf = new Map((document.clips ?? []).map((clip) => [clip.clip_id, "asset_id" in clip ? clip.asset_id : null]));
  const usedIn = (assetId: string | null | undefined) =>
    assetId ? beats.filter((beat) => beat.clipIds.some((id) => assetOf.get(id) === assetId)) : [];
  /** Where the material first shows in the draft, for "Show where it is used". */
  const shownAt = (assetId: string | null | undefined): number | null => {
    const inBeats = new Set(beats.flatMap((beat) => beat.clipIds));
    const frames = (document.clips ?? [])
      .filter((clip) => inBeats.has(clip.clip_id) && "asset_id" in clip && clip.asset_id === assetId)
      .map((clip) => clip.from_frame);
    return assetId && frames.length ? Math.min(...frames) : null;
  };
  const rowMenu = { openBeat, onAddToOpenBeat, onShowUse, shownAt };

  const known = new Set((materials?.items ?? []).map((item) => item.asset_id).filter(Boolean));
  const groups: { id: GroupId | "figures" | "narration"; rows: React.ReactNode[] }[] = [];
  const items = (id: GroupId) =>
    (materials?.items ?? []).filter(
      (item) => item.role && GROUP_OF[item.role] === id && matches(item.label, item.owner_handle, item.query, item.author),
    );
  for (const id of ["main", "cards", "footage", "photos"] as const) {
    const rows = items(id);
    const labels = numberRepeats(rows.map((item) => materialRowLabel(item, t)));
    groups.push({ id, rows: rows.map((item, index) => <MaterialRow menu={rowMenu} key={item.item_id} item={item} label={labels[index]!} provenance={Boolean(materials?.provenance_available)} usedIn={usedIn(item.asset_id)} preview={item.asset_id ? previews[item.asset_id] : undefined} />) });
  }
  const voices = (document.clips ?? []).filter((clip) => clip.clip_id.startsWith("clip_narration_"));
  if (voices.length) {
    groups.push({
      id: "narration",
      rows: voices
        .map((clip) => ({ clip, label: clipLabel(clip, { document, materials, t }) }))
        .filter(({ label }) => matches(label))
        .map(({ clip, label }) => (
          <li key={clip.clip_id} className="flex items-center gap-2 rounded-md px-2 py-1.5 hover:bg-surface">
            <Thumbnail kind="audio" />
            <div className="flex min-w-0 flex-col">
              <span className="break-words text-sm text-ink">{label}</span>
              <span className="text-xs text-muted-ink">
                {t("studio.label.kind.audio")} · {t("studio.story.seconds", { seconds: (clip.duration_in_frames / document.canvas.fps).toFixed(1) })}
              </span>
            </div>
          </li>
        )),
    });
  }
  groups.push({
    id: "figures",
    rows: (materials?.figures ?? [])
      .filter((figure) => matches(figure.name, figure.role))
      .map((figure) => (
        <li key={figure.name} className="px-2 py-1.5 text-sm text-ink">
          {figure.name} <span className="text-muted-ink">· {figure.type}{figure.role ? ` · ${figure.role}` : ""}</span>
        </li>
      )),
  });
  groups.push({ id: "comments", rows: items("comments").map((item) => <MaterialRow menu={rowMenu} key={item.item_id} item={item} label={item.label} provenance={Boolean(materials?.provenance_available)} usedIn={[]} />) });
  const uploadRows = uploads.filter((asset) => !known.has(asset.asset_id) && asset.kind !== "audio");
  const uploadLabels = numberRepeats(uploadRows.map((asset) => assetLabel(asset.asset_id, { document, materials, t }, asset).label));
  groups.push({
    id: "uploads",
    rows: uploadRows
      .map((asset, index) => ({ asset, label: uploadLabels[index]! }))
      .filter(({ label }) => matches(label))
      .map(({ asset, label }) => (
        <li
          key={asset.asset_id}
          draggable
          onDragStart={(event) => event.dataTransfer.setData(MATERIAL_DRAG_TYPE, `upload:${asset.asset_id}`)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink hover:bg-surface"
        >
          <Thumbnail kind={asset.kind} preview={previews[asset.asset_id]} />
          <span className="min-w-0 break-words">{label}</span>
        </li>
      )),
  });

  return (
    <aside aria-label={t("studio.materials.title")} className="flex min-h-0 min-w-0 flex-col gap-3 overflow-auto border-r border-hairline bg-bg p-3">
      <h2 className="text-[15px] font-semibold text-ink">{t("studio.materials.title")}</h2>
      <input
        type="search"
        aria-label={t("studio.materials.search")}
        placeholder={t("studio.materials.search")}
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className="h-9 rounded-md border border-hairline bg-well px-3 text-sm text-ink placeholder:text-faint focus-visible:outline-2 focus-visible:outline-copper"
      />
      {materials && !materials.provenance_available ? (
        <p className="text-xs text-muted-ink">{t("studio.materials.noProvenance")}</p>
      ) : null}
      {groups.map(({ id, rows }) => {
        const open = !collapsed.has(id);
        const limit = shown[id] ?? PAGE;
        const title = t(`studio.materials.group.${id}`);
        return (
          <section key={id} aria-label={title} className="flex flex-col gap-1">
            <button
              type="button"
              aria-expanded={open}
              onClick={() =>
                setCollapsed((current) => {
                  const next = new Set(current);
                  if (open) next.add(id);
                  else next.delete(id);
                  return next;
                })
              }
              className="flex items-center justify-between rounded px-1 py-1 text-xs font-medium tracking-wide text-muted-ink uppercase hover:text-ink focus-visible:outline-2 focus-visible:outline-copper"
            >
              <span>{title}</span> <span className="font-mono">{rows.length}</span>
              <ChevronDown aria-hidden="true" size={14} className={open ? "" : "-rotate-90"} />
            </button>
            {open ? (
              <>
                <ul className="flex flex-col">{rows.slice(0, limit)}</ul>
                {rows.length > limit ? (
                  <button
                    type="button"
                    onClick={() => setShown((current) => ({ ...current, [id]: rows.length }))}
                    className="self-start px-2 text-xs text-copper hover:underline"
                  >
                    {t("studio.materials.more", { count: rows.length - limit })}
                  </button>
                ) : null}
              </>
            ) : null}
          </section>
        );
      })}
    </aside>
  );
}

export function Thumbnail({ kind, preview }: { kind: string; preview?: string }) {
  const box = "grid size-10 shrink-0 place-items-center overflow-hidden rounded bg-well text-faint";
  if (preview && kind === "image") return <img src={preview} alt="" className={`${box} object-cover`} />;
  if (preview && kind === "video") return <video src={preview} muted preload="metadata" className={`${box} object-cover`} />;
  const Icon = kind === "video" ? Film : kind === "image" ? ImageIcon : kind === "audio" ? AudioLines : Quote;
  return (
    <span aria-hidden="true" className={box}>
      <Icon size={16} />
    </span>
  );
}

type RowMenu = {
  openBeat?: Beat;
  onAddToOpenBeat?: (itemId: string) => void;
  onShowUse?: (frame: number) => void;
  shownAt: (assetId: string | null | undefined) => number | null;
};

function MaterialRow({
  item,
  label,
  provenance,
  usedIn,
  preview,
  menu: rowMenu,
}: {
  item: StudioMaterial;
  label: string;
  provenance: boolean;
  usedIn: Beat[];
  preview?: string;
  menu?: RowMenu;
}) {
  const { t, day } = useLocale();
  const [why, setWhy] = useState(false);
  const line = [
    item.platform,
    item.owner_handle ? `@${item.owner_handle}` : item.author ? `@${item.author}` : null,
    t(`studio.materials.kind.${item.media_kind}`),
    item.story_score != null ? t("studio.materials.score", { score: Math.round(item.story_score * 100) }) : null,
  ].filter(Boolean);
  const reasons = whyLines(item, t, day);
  const menu = useContextMenu();
  const entries = (): MenuEntry[] => {
    const frame = rowMenu?.shownAt(item.asset_id) ?? null;
    const open = rowMenu?.openBeat;
    const already = Boolean(open && usedIn.some((beat) => beat.id === open.id));
    const unavailable = t("studio.menu.reason.unavailable");
    return [
      {
        kind: "item",
        id: "add",
        label: t("studio.menu.addToOpenBeat"),
        disabled: !open || !rowMenu?.onAddToOpenBeat || item.media_kind === "none" || already,
        reason: item.media_kind === "none" ? t("studio.menu.reason.noMedia") : already ? t("studio.menu.reason.alreadyIn") : unavailable,
        onSelect: () => rowMenu?.onAddToOpenBeat?.(item.item_id),
      },
      {
        kind: "item",
        id: "use",
        label: t("studio.menu.showUse"),
        disabled: frame === null || !rowMenu?.onShowUse,
        reason: frame === null ? t("studio.menu.reason.unused") : unavailable,
        onSelect: () => frame !== null && rowMenu?.onShowUse?.(frame),
      },
      {
        kind: "item",
        id: "why",
        label: t("studio.materials.why"),
        disabled: !(provenance && reasons.length),
        reason: unavailable,
        onSelect: () => setWhy(true),
      },
    ];
  };

  // The menu sits beside the row, not in it: a right click inside the menu must not reach the row.
  return (
    <>
    {menu.element}
    <li
      draggable={item.media_kind !== "none"}
      onDragStart={(event) => event.dataTransfer.setData(MATERIAL_DRAG_TYPE, item.item_id)}
      {...menu.bind(entries)}
      className="flex flex-col gap-1 rounded-md px-2 py-1.5 hover:bg-surface"
    >
      <div className="flex items-start gap-2">
        <Thumbnail kind={item.media_kind} preview={preview} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="line-clamp-2 break-words text-sm text-ink" title={label}>{label}</span>
          <span className="truncate text-xs text-muted-ink">{line.join(" · ")}</span>
          {usedIn.length ? (
            <span className="flex flex-wrap gap-1 pt-0.5">
              {usedIn.map((beat) => (
                <span key={beat.id} className="rounded bg-copper/15 px-1.5 text-[11px] text-copper">
                  {t("studio.materials.usedIn", { beat: t(`studio.story.beat.${beat.id}`) })}
                </span>
              ))}
            </span>
          ) : null}
        </div>
        {provenance && reasons.length ? (
          <button
            type="button"
            aria-label={t("studio.materials.why")}
            aria-expanded={why}
            onClick={() => setWhy((open) => !open)}
            className="grid size-7 shrink-0 place-items-center rounded text-muted-ink hover:text-ink focus-visible:outline-2 focus-visible:outline-copper"
          >
            <Info aria-hidden="true" size={14} />
          </button>
        ) : null}
      </div>
      {why ? (
        <div role="note" className="ml-12 rounded-md border border-hairline bg-raised p-2 text-xs text-muted-ink">
          {reasons.map((reason) => (
            <p key={reason}>{reason}</p>
          ))}
        </div>
      ) : null}
    </li>
    </>
  );
}

/** Spec §6.3: only what the run knows; a missing value is left out. */
function whyLines(
  item: StudioMaterial,
  t: ReturnType<typeof useLocale>["t"],
  day: (iso: string) => string,
): string[] {
  const lines: (string | null)[] = [];
  if (item.verdict && item.verdict !== "none") {
    lines.push(t(`studio.materials.why.${item.verdict}`, { owner: item.owner_handle ?? "" }));
  }
  if (item.ocr_outcome) {
    const trim = item.trim_start_seconds ? `, ${t("studio.materials.why.trim", { seconds: item.trim_start_seconds })}` : "";
    lines.push(`${t("studio.materials.why.ocr", { outcome: item.ocr_outcome })}${trim}`);
  }
  if (item.query) lines.push(t("studio.materials.why.query", { query: item.query }));
  if (item.story_score != null) lines.push(t("studio.materials.why.score", { score: Math.round(item.story_score * 100) }));
  if (item.shows_object) lines.push(t(`studio.materials.why.shows.${item.shows_object}`));
  if (item.likes != null && item.author) lines.push(t("studio.materials.why.likes", { likes: item.likes, author: item.author }));
  if (item.platform && !item.query) {
    lines.push(
      item.published_at
        ? t("studio.materials.why.posted", { date: day(item.published_at), platform: item.platform })
        : t("studio.materials.why.platform", { platform: item.platform }),
    );
  }
  return lines.filter((line): line is string => Boolean(line));
}
