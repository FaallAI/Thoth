import { useEffect, useRef, useState } from "react";
import { Film, Image, MoreHorizontal, SlidersHorizontal, Upload, X } from "lucide-react";
import type { EditDocument } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

type Panel = "details" | "replace" | "adjust";
/** The dialog's class in pen-studio.css. */
const PANEL_CLASS: Record<Panel, string> = { details: "media", replace: "replace", adjust: "adjust" };

/** Presentation of existing document metadata; media replacement has no direct patch operation. */
export function SceneMediaInspector({ document, sceneId, labelOf }: { document: EditDocument; sceneId: string; labelOf?: (assetId: string) => string }) {
  const { t } = useLocale();
  const [panel, setPanel] = useState<Panel | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const scene = document.scenes.find((entry) => entry.scene_id === sceneId);
  const mainTrack = document.tracks.find((track) => track.kind === "main_video")?.track_id;
  // A narrated scene lists only its text; its video is the main-track clip that plays under it.
  const media =
    document.clips?.find((clip) => scene?.clip_ids.includes(clip.clip_id) && clip.kind === "video") ??
    (scene &&
      document.clips?.find(
        (clip) =>
          clip.kind === "video" &&
          clip.track_id === mainTrack &&
          clip.from_frame < scene.start_frame + scene.duration_in_frames &&
          clip.from_frame + clip.duration_in_frames > scene.start_frame,
      ));
  const assetId = media && "asset_id" in media ? media.asset_id : undefined;
  const asset = document.schema_version === 2 ? document.asset_refs?.find((entry) => entry.asset_id === assetId) : undefined;
  const name = !media ? t("studio.media.none") : (assetId && labelOf?.(assetId)) || t("studio.media.video");
  const state = asset ? (asset.validation_state === "ready" ? t("studio.media.ready") : asset.validation_state) : t("studio.media.unavailable");
  const title = panel && t(`studio.media.${panel}`);
  useEffect(() => {
    if (panel && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [panel]);

  return <section className="studio-media-field" aria-label={t("studio.media.region")}>
    <h3>{t("studio.media.title")}</h3>
    <div className="studio-media-summary"><Film size={17} /><div><span>{name}</span><small>{state}{media ? ` · ${(media.duration_in_frames / document.canvas.fps).toFixed(1)}s` : ""}</small></div><button type="button" aria-label={t("studio.media.details")} onClick={() => setPanel("details")}><MoreHorizontal size={16} /></button></div>
    <div className="studio-media-actions"><button type="button" onClick={() => setPanel("replace")}>{t("studio.media.replaceShort")} <Upload size={14} /></button><button type="button" onClick={() => setPanel("adjust")}>{t("studio.media.adjustShort")} <SlidersHorizontal size={14} /></button></div>
    {panel ? <dialog ref={dialog} className={`studio-media-dialog studio-media-dialog-${PANEL_CLASS[panel]}`} aria-label={title ?? undefined} onCancel={() => setPanel(null)} onClose={() => setPanel(null)}>
      <header><h2>{title}</h2><button type="button" aria-label={t("studio.media.closeNamed", { panel: title ?? "" })} onClick={() => setPanel(null)}><X size={17} /></button></header>
      {panel === "details" ? <><div className="studio-media-dialog-body"><Film size={25} /><strong>{name}</strong><dl><div><dt>{t("studio.media.type")}</dt><dd>{media?.kind ?? "—"}</dd></div><div><dt>{t("studio.media.status")}</dt><dd>{state}</dd></div><div><dt>{t("studio.media.duration")}</dt><dd>{media ? `${(media.duration_in_frames / document.canvas.fps).toFixed(1)}s` : "—"}</dd></div><div><dt>{t("studio.media.source")}</dt><dd>{media ? name : "—"}</dd></div></dl><p>{t("studio.media.detailsNote")}</p></div><footer><button type="button" onClick={() => setPanel(null)}>{t("studio.media.close")}</button></footer></> : panel === "replace" ? <><div className="studio-media-dialog-body"><h3>{t("studio.media.current")}</h3><div className="studio-media-summary"><Film size={17} /><span>{name}</span></div><h3>{t("studio.media.readyAssets")}</h3><div className="studio-media-empty"><Image size={24} /><p>{t("studio.media.replaceNote")}</p><small>{t("studio.media.replaceHow")}</small></div></div><footer><button type="button" onClick={() => setPanel(null)}>{t("studio.media.cancel")}</button><button type="button" disabled>{t("studio.media.replace")}</button></footer></> : <><div className="studio-media-dialog-body studio-adjust-grid"><div className="studio-adjust-preview"><Image size={32} /><span>{name}</span></div><div><h3>{t("studio.media.properties")}</h3><label>{t("studio.media.fit")}<select aria-label={t("studio.media.fit")} value={media && "fit" in media ? media.fit : "cover"} disabled><option value="cover">{t("studio.media.fit.cover")}</option><option value="contain">{t("studio.media.fit.contain")}</option></select></label><label>{t("studio.media.crop")}<input readOnly disabled value={media && "crop" in media && media.crop ? `${media.crop.left}, ${media.crop.top}, ${media.crop.width}, ${media.crop.height}` : "—"} /></label><label>{t("studio.media.position")}<input readOnly disabled value={media && "position" in media && media.position ? `${media.position.x}, ${media.position.y} ×${media.position.scale}` : "—"} /></label><p>{t("studio.media.viewOnly")}</p></div></div><footer><button type="button" onClick={() => setPanel(null)}>{t("studio.media.cancel")}</button><button type="button" disabled>{t("studio.media.apply")}</button></footer></>}
    </dialog> : null}
  </section>;
}
