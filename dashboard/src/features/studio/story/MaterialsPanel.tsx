import { useState } from "react";
import { ChevronDown, Film, ImageIcon, Info, Quote } from "lucide-react";

import type { EditDocumentV2, EditorAsset, StudioMaterial, StudioMaterials } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

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
};

/** Spec 2026-10-27 §9: everything the run collected, grouped, with where it came from. */
export function MaterialsPanel({ materials, uploads, beats, document, previews }: Props) {
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

  const known = new Set((materials?.items ?? []).map((item) => item.asset_id).filter(Boolean));
  const groups: { id: GroupId | "figures"; rows: React.ReactNode[] }[] = [];
  const items = (id: GroupId) =>
    (materials?.items ?? []).filter(
      (item) => item.role && GROUP_OF[item.role] === id && matches(item.label, item.owner_handle, item.query, item.author),
    );
  for (const id of ["main", "cards", "footage", "photos"] as const) {
    groups.push({ id, rows: items(id).map((item) => <MaterialRow key={item.item_id} item={item} provenance={Boolean(materials?.provenance_available)} usedIn={usedIn(item.asset_id)} preview={item.asset_id ? previews[item.asset_id] : undefined} />) });
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
  groups.push({ id: "comments", rows: items("comments").map((item) => <MaterialRow key={item.item_id} item={item} provenance={Boolean(materials?.provenance_available)} usedIn={[]} />) });
  groups.push({
    id: "uploads",
    rows: uploads
      .filter((asset) => !known.has(asset.asset_id) && asset.kind !== "audio" && matches(asset.asset_id))
      .map((asset) => (
        <li
          key={asset.asset_id}
          draggable
          onDragStart={(event) => event.dataTransfer.setData(MATERIAL_DRAG_TYPE, `upload:${asset.asset_id}`)}
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink hover:bg-surface"
        >
          <Thumbnail kind={asset.kind} preview={previews[asset.asset_id]} />
          <span className="min-w-0 truncate">{asset.asset_id}</span>
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

function Thumbnail({ kind, preview }: { kind: string; preview?: string }) {
  const box = "grid size-10 shrink-0 place-items-center overflow-hidden rounded bg-well text-faint";
  if (preview && kind === "image") return <img src={preview} alt="" className={`${box} object-cover`} />;
  if (preview && kind === "video") return <video src={preview} muted preload="metadata" className={`${box} object-cover`} />;
  const Icon = kind === "video" ? Film : kind === "image" ? ImageIcon : Quote;
  return (
    <span aria-hidden="true" className={box}>
      <Icon size={16} />
    </span>
  );
}

function MaterialRow({ item, provenance, usedIn, preview }: { item: StudioMaterial; provenance: boolean; usedIn: Beat[]; preview?: string }) {
  const { t, day } = useLocale();
  const [why, setWhy] = useState(false);
  const line = [
    item.platform,
    item.owner_handle ? `@${item.owner_handle}` : item.author ? `@${item.author}` : null,
    t(`studio.materials.kind.${item.media_kind}`),
    item.story_score != null ? t("studio.materials.score", { score: Math.round(item.story_score * 100) }) : null,
  ].filter(Boolean);
  const reasons = whyLines(item, t, day);

  return (
    <li
      draggable={item.media_kind !== "none"}
      onDragStart={(event) => event.dataTransfer.setData(MATERIAL_DRAG_TYPE, item.item_id)}
      className="flex flex-col gap-1 rounded-md px-2 py-1.5 hover:bg-surface"
    >
      <div className="flex items-start gap-2">
        <Thumbnail kind={item.media_kind} preview={preview} />
        <div className="flex min-w-0 flex-1 flex-col">
          <span className="truncate text-sm text-ink">{item.label}</span>
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
