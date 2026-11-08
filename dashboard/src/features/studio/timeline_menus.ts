// What the Timeline's right-click menus offer (spec 2026-11-08 §5.1). Every entry is built from the
// edit helpers, so a menu, a key and a button make the same edit and give the same reason.
import type { EditDocumentOperation, EditDocumentV2 } from "@/api/control-plane";
import type { MenuEntry } from "@/components/ContextMenu";
import type { LocaleState } from "@/lib/locale";
import { shortcutKeys } from "./studio_keys";
import { compatibleTrackIds } from "./timeline_domain";
import {
  closeGap,
  deleteClip,
  moveToTrack,
  moveTrack,
  removeTrack,
  rippleDelete,
  setClipFlag,
  splitAt,
  type Edit,
} from "./timeline_edits";

type Clip = NonNullable<EditDocumentV2["clips"]>[number];
type Track = EditDocumentV2["tracks"][number];

export type MenuContext = {
  t: LocaleState["t"];
  doc: EditDocumentV2;
  playheadFrame: number;
  commit: (operations: EditDocumentOperation[]) => void;
  trackName: (track: Track) => string;
};

/** One entry for one edit: disabled with its reason when the helper refuses. */
function editEntry(context: MenuContext, id: string, label: string, edit: Edit, shortcut?: string): MenuEntry {
  return {
    kind: "item",
    id,
    label,
    shortcut,
    disabled: Boolean(edit.refusal) || !edit.operations.length,
    reason: edit.refusal ? context.t(`studio.menu.reason.${edit.refusal}`) : undefined,
    onSelect: () => context.commit(edit.operations),
  };
}

export function clipMenu(
  context: MenuContext,
  clip: Clip,
  extra: { onReplace: () => void; storyBeat: string | null; onShowInStory?: () => void },
): MenuEntry[] {
  const { t, doc, playheadFrame } = context;
  const locked = clip.locked === true || doc.tracks.find((track) => track.track_id === clip.track_id)?.locked === true;
  const lockedReason = t("studio.menu.reason.locked");
  const targets = compatibleTrackIds(doc, clip.kind).filter((trackId) => trackId !== clip.track_id);
  const entries: MenuEntry[] = [
    editEntry(context, "split", t("studio.menu.split"), splitAt(doc, clip.clip_id, playheadFrame), shortcutKeys("split")),
    editEntry(context, "delete", t("studio.menu.delete"), deleteClip(doc, clip.clip_id), shortcutKeys("delete")),
    editEntry(context, "ripple", t("studio.menu.rippleDelete"), rippleDelete(doc, clip.clip_id), shortcutKeys("ripple_delete")),
    {
      kind: "item",
      id: "replace",
      label: t("studio.menu.replaceMedia"),
      disabled: locked || clip.kind !== "video",
      reason: locked ? lockedReason : clip.kind !== "video" ? t("studio.menu.reason.notVideo") : undefined,
      onSelect: extra.onReplace,
    },
  ];
  if (targets.length && !locked) {
    entries.push({
      kind: "group",
      id: "move",
      label: t("studio.menu.moveToTrack"),
      entries: targets.map((trackId) => {
        const track = doc.tracks.find((entry) => entry.track_id === trackId)!;
        return editEntry(context, `move-${trackId}`, context.trackName(track), moveToTrack(doc, clip.clip_id, trackId));
      }),
    });
  }
  entries.push(
    editEntry(context, "hide", t(clip.hidden ? "studio.menu.show" : "studio.menu.hide"), setClipFlag(doc, clip.clip_id, "hidden", !clip.hidden)),
    editEntry(context, "lock", t(clip.locked ? "studio.menu.unlock" : "studio.menu.lock"), setClipFlag(doc, clip.clip_id, "locked", !clip.locked)),
    {
      kind: "item",
      id: "story",
      label: t("studio.menu.showInStory"),
      disabled: !extra.storyBeat || !extra.onShowInStory,
      reason: t("studio.menu.reason.notInStory"),
      onSelect: () => extra.onShowInStory?.(),
    },
  );
  return entries;
}

export function gapMenu(context: MenuContext, trackId: string, frame: number): MenuEntry[] {
  return [editEntry(context, "close-gap", context.t("studio.menu.closeGap"), closeGap(context.doc, trackId, frame))];
}

export function trackMenu(
  context: MenuContext,
  track: Track,
  extra: { onSelect: () => void; onToggle: (field: "hidden" | "muted" | "locked", value: boolean) => void },
): MenuEntry[] {
  const { t, doc } = context;
  const lockedReason = t("studio.menu.reason.trackLocked");
  type Key = Parameters<MenuContext["t"]>[0];
  const toggle = (field: "hidden" | "muted", on: Key, off: Key): MenuEntry => ({
    kind: "item",
    id: field,
    label: t(track[field] ? off : on),
    disabled: track.locked === true,
    reason: lockedReason,
    onSelect: () => extra.onToggle(field, !track[field]),
  });
  return [
    { kind: "item", id: "select", label: t("studio.menu.selectTrack"), onSelect: extra.onSelect },
    editEntry(context, "up", t("studio.menu.moveUp"), moveTrack(doc, track.track_id, -1)),
    editEntry(context, "down", t("studio.menu.moveDown"), moveTrack(doc, track.track_id, 1)),
    toggle("hidden", "studio.menu.hide", "studio.menu.show"),
    toggle("muted", "studio.menu.mute", "studio.menu.unmute"),
    {
      kind: "item",
      id: "locked",
      label: t(track.locked ? "studio.menu.unlock" : "studio.menu.lock"),
      onSelect: () => extra.onToggle("locked", !track.locked),
    },
    editEntry(context, "remove", t("studio.menu.removeTrack"), removeTrack(doc, track.track_id)),
  ];
}
