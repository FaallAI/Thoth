import { useEffect, useRef, useState } from "react";
import { Film, Image, MoreHorizontal, SlidersHorizontal, Upload, X } from "lucide-react";
import type { EditDocument } from "@/api/control-plane";

/** Presentation of existing document metadata; media replacement has no direct patch operation. */
export function SceneMediaInspector({ document, sceneId }: { document: EditDocument; sceneId: string }) {
  const [panel, setPanel] = useState<"Media details" | "Replace media" | "Adjust media" | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  const scene = document.scenes.find((entry) => entry.scene_id === sceneId);
  const media = document.clips?.find((clip) => scene?.clip_ids.includes(clip.clip_id) && clip.kind === "video");
  const assetId = media && "asset_id" in media ? media.asset_id : undefined;
  const asset = document.schema_version === 2 ? document.asset_refs?.find((entry) => entry.asset_id === assetId) : undefined;
  const name = assetId ?? "No media attached";
  useEffect(() => {
    if (panel && dialog.current && !dialog.current.open) dialog.current.showModal();
  }, [panel]);

  return <section className="studio-media-field" aria-label="Scene media">
    <h3>Media</h3>
    <div className="studio-media-summary"><Film size={17} /><div><span>{name}</span><small>{asset ? asset.validation_state : "Unavailable"}{media ? ` · ${(media.duration_in_frames / document.canvas.fps).toFixed(1)}s` : ""}</small></div><button type="button" aria-label="Media details" onClick={() => setPanel("Media details")}><MoreHorizontal size={16} /></button></div>
    <div className="studio-media-actions"><button type="button" onClick={() => setPanel("Replace media")}>Replace <Upload size={14} /></button><button type="button" onClick={() => setPanel("Adjust media")}>Adjust <SlidersHorizontal size={14} /></button></div>
    {panel ? <dialog ref={dialog} className={`studio-media-dialog studio-media-dialog-${panel.split(" ")[0].toLowerCase()}`} aria-label={panel} onCancel={() => setPanel(null)} onClose={() => setPanel(null)}>
      <header><h2>{panel}</h2><button type="button" aria-label={`Close ${panel}`} onClick={() => setPanel(null)}><X size={17} /></button></header>
      {panel === "Media details" ? <><div className="studio-media-dialog-body"><Film size={25} /><strong>{name}</strong><dl><div><dt>Type</dt><dd>{media?.kind ?? "—"}</dd></div><div><dt>Status</dt><dd>{asset?.validation_state ?? "Unavailable"}</dd></div><div><dt>Duration</dt><dd>{media ? `${(media.duration_in_frames / document.canvas.fps).toFixed(1)}s` : "—"}</dd></div><div><dt>Source</dt><dd>{assetId ?? "—"}</dd></div></dl><p>The selected scene uses this source. Clip timing can be adjusted in Advanced.</p></div><footer><button type="button" onClick={() => setPanel(null)}>Close</button></footer></> : panel === "Replace media" ? <><div className="studio-media-dialog-body"><h3>Current media</h3><div className="studio-media-summary"><Film size={17} /><span>{name}</span></div><h3>Ready assets</h3><div className="studio-media-empty"><Image size={24} /><p>Replacing media is not available from this panel.</p><small>To change this source, remove its clip in Advanced and add a ready asset to the main video track.</small></div></div><footer><button type="button" onClick={() => setPanel(null)}>Cancel</button><button type="button" disabled>Replace media</button></footer></> : <><div className="studio-media-dialog-body studio-adjust-grid"><div className="studio-adjust-preview"><Image size={32} /><span>{name}</span></div><div><h3>Video properties</h3><label>Fit<select aria-label="Fit" value={media && "fit" in media ? media.fit : "cover"} disabled><option value="cover">Cover</option><option value="contain">Contain</option></select></label><label>Crop<input readOnly disabled value={media && "crop" in media && media.crop ? `${media.crop.left}, ${media.crop.top}, ${media.crop.width}, ${media.crop.height}` : "—"} /></label><label>Position<input readOnly disabled value={media && "position" in media && media.position ? `${media.position.x}, ${media.position.y} ×${media.position.scale}` : "—"} /></label><p>Fit, crop and position are view-only in the current editor.</p></div></div><footer><button type="button" onClick={() => setPanel(null)}>Cancel</button><button type="button" disabled>Apply changes</button></footer></>}
    </dialog> : null}
  </section>;
}
