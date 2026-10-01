import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowUpRight, BookOpen, ChevronRight, CircleCheck, ImageIcon, MessageSquare, Pin, Send, Sparkles, UserRound, X } from "lucide-react";
import { PageActions } from "@/components/PageActions";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { LogPane, type LogLine } from "@/components/LogPane";
import { CleanupButton } from "@/components/CleanupButton";
import { projectStudioSource, StudioSourceError } from "@/features/studio/content_set_import";
import type { StudioSourceProjection } from "@/api/control-plane";
import {
  cleanupPackage,
  describeCode,
  formatBytes,
  getContentSetData,
  getPackageSummary,
  packageIdFromManifestPath,
  putContentSet,
  scoutImageUrl,
  scoutValidate,
  scoutStatus,
  streamScout,
  type ContentSetData,
  type PackageSummary,
  type ScoutLogLine,
} from "@/api";

// The curate surface only touches these shapes; everything else in `content` is
// preserved verbatim on save.
type Main = { title?: string; description?: string; thumbnail?: string; image_path?: string; profile?: any };
type Footage = { url?: string; title?: string; description?: string; platform?: string; duration_sec?: number; thumbnail?: string; image_path?: string };
type Comment = { author?: string; text?: string; likes?: number; image_path?: string };
type Figure = { name?: string; kind?: string; role?: string; description?: string };
type Reference = { term?: string; kind?: string; summary?: string };

export function ContentSet({
  onSendToRender,
  projectId = null,
  onOpenInStudio = () => {},
}: {
  onSendToRender: (path: string, forced: boolean) => void;
  projectId?: string | null;
  onOpenInStudio?: (source: StudioSourceProjection) => void;
}) {
  const [data, setData] = useState<ContentSetData | null>(null);
  const [content, setContent] = useState<any | null>(null);
  const [dirty, setDirty] = useState(false);
  const [saving, setSaving] = useState(false);
  const [running, setRunning] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [loadErr, setLoadErr] = useState<string | null>(null);
  const [lines, setLines] = useState<ScoutLogLine[]>([]);
  const esRef = useRef<EventSource | null>(null);

  // Load the content-set once on mount.
  useEffect(() => {
    let alive = true;
    getContentSetData()
      .then((d) => {
        if (!alive) return;
        setData(d);
        setContent(d.content);
        setDirty(false);
      })
      .catch((e) => {
        // A failed initial fetch must not leave the view stuck on "Loading…".
        if (alive) setLoadErr(String(e));
      });
    return () => {
      alive = false;
    };
  }, []);

  // Poll scout status so Save is disabled while any scout command is in-flight
  // (the single slot means a running discover/validate could rewrite the file).
  useEffect(() => {
    let alive = true;
    const tick = async () => {
      try {
        const s = await scoutStatus();
        if (alive) setRunning(s?.run?.status === "running");
      } catch {
        // Transient status blip — keep the previous running state.
      }
    };
    tick();
    const id = setInterval(tick, 3000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

  // Close any stream on unmount.
  useEffect(() => () => esRef.current?.close(), []);

  // Forced-main package facts, keyed off the content-set's own descriptor.
  const packageId = content?.main_footage?.mode === "forced_url_pool"
    ? packageIdFromManifestPath(String(content.main_footage.package_manifest ?? ""))
    : null;
  const [pkg, setPkg] = useState<PackageSummary | null>(null);
  const [pkgNonce, setPkgNonce] = useState(0);
  useEffect(() => {
    if (!packageId) {
      setPkg(null);
      return;
    }
    let alive = true;
    getPackageSummary(packageId)
      .then((summary) => alive && setPkg(summary))
      .catch(() => alive && setPkg(null));
    return () => {
      alive = false;
    };
  }, [packageId, pkgNonce]);

  const outputRoot = data?.output_root ?? "";
  const imgSrc = (p?: string) => (p ? scoutImageUrl(p, outputRoot) : undefined);

  const mutate = (fn: (c: any) => void) => {
    setContent((prev: any) => {
      if (!prev) return prev;
      const next = structuredClone(prev);
      fn(next);
      return next;
    });
    setDirty(true);
  };

  const removeAt = (key: string, idx: number) =>
    mutate((c) => {
      if (Array.isArray(c[key])) c[key].splice(idx, 1);
    });

  const setMain = (field: "title" | "description", value: string) =>
    mutate((c) => {
      c.main = c.main ?? {};
      c.main[field] = value;
    });

  const save = async (): Promise<boolean> => {
    if (!content) return false;
    setSaving(true);
    setNotice(null);
    const res = await putContentSet(content);
    setSaving(false);
    if (!res.ok) {
      setNotice(res.error ?? "save failed");
      return false;
    }
    setDirty(false);
    setNotice("Saved. Validating…");
    // Reuse B's validate command; tail its log over SSE into the LogPane.
    setLines([]);
    esRef.current?.close();
    esRef.current = streamScout(0, (l) => setLines((prev) => [...prev, l]));
    const ack = await scoutValidate(res.path ?? data?.path ?? "");
    // Surface a rejected validate (e.g. 409 slot-busy) instead of leaving the
    // footer stuck on "Saved. Validating…" with no signal.
    if (!ack.ok) {
      setNotice(
        ack.status === 409
          ? "Saved. Validate skipped — scout is busy; try again shortly."
          : `Saved, but validate failed${ack.error ? `: ${ack.error}` : ""}.`,
      );
    }
    // Repaint from the canonical file after the write.
    const fresh = await getContentSetData();
    setData(fresh);
    setContent(fresh.content);
    setDirty(false);
    return true; // putContentSet succeeded — safe to hand off to render
  };

  // Sub-project D: save the on-screen edits (if any) then hand the canonical
  // content-set path to RunForm via the lifted App state. A running scout or an
  // empty/missing set disables the trigger; a failed save aborts the hand-off.
  const sendToRender = async () => {
    if (!data?.path || !content || running) return;
    if (dirty) {
      const ok = await save();
      if (!ok) return; // save failed → stay put; notice already shown
    }
    // `data.path` is the canonical content-set path; a save never changes it
    // (save() re-fetches the same file), so reading it from the pre-save
    // closure is safe. Revisit if a future path-picker lets save() relocate it.
    onSendToRender(data.path, content.main_footage?.mode === "forced_url_pool");
  };

  const openInStudio = async () => {
    if (!content || !projectId || running) return;
    setNotice(null);
    try {
      onOpenInStudio(await projectStudioSource(content));
    } catch (error) {
      setNotice(
        error instanceof StudioSourceError
          ? `Studio cannot open this Content Set: ${error.message}.`
          : "Could not open Studio. Try again.",
      );
    }
  };

  const logLines: LogLine[] = lines.map((l) => ({
    id: String(l.seq),
    ts: "",
    text: l.text,
    kind: l.stream === "err" ? "error" : "log",
  }));

  const main: Main = content?.main ?? {};
  const footage: Footage[] = Array.isArray(content?.footage) ? content.footage : [];
  const comments: Comment[] = Array.isArray(content?.comments) ? content.comments : [];
  const figures: Figure[] = Array.isArray(content?.figures) ? content.figures : [];
  const references: Reference[] = Array.isArray(content?.references) ? content.references : [];
  const mainImg = imgSrc(main.thumbnail ?? main.image_path);
  const unavailable = loadErr ? `Couldn't load the content-set: ${loadErr}` : !data ? "Loading…" : !data.exists ? "No content-set yet — run Discovery first." : data.error === "malformed" || !content ? `The content-set on disk isn't valid JSON (${data.path}).` : null;
  const ready = !unavailable && !!content;

  return (
    <div className="contentset-workspace pen-contentset">
      <PageActions>
        {dirty && <Button onClick={save} disabled={!ready || saving || running}>{saving ? "Saving…" : "Save"}</Button>}
        <Button className="pen-secondary-action" onClick={sendToRender} disabled={saving || running || !data?.path || !ready}>Send to render <Send aria-hidden="true" /></Button>
        <Button onClick={openInStudio} disabled={running || !projectId || !ready} title={!projectId ? "Select a project to open this brief in Studio" : undefined}>Open in Studio <ArrowUpRight aria-hidden="true" /></Button>
      </PageActions>
      <div className="contentset-summary">
        <div><p className="pen-section-eyebrow">Current brief</p><h2>{main.title || "Untitled content set"}</h2></div>
        <dl><div><dt>Source</dt><dd>{references.length} references</dd></div><div title="Drafted scene totals are not supplied by this Content Set"><dt>Scenes</dt><dd>—</dd></div><div><dt>Status</dt><dd>{dirty ? "Unsaved changes" : ready ? "Saved source" : "No saved source"}</dd></div></dl>
      </div>
      <div className="contentset-grid">
        <section className="contentset-story" aria-label="Story structure">
          <header className="pen-story-heading"><div><p className="pen-section-eyebrow">Story structure</p><h2>The story we are telling</h2></div><small>{dirty ? "Unsaved changes" : ""}</small></header>
          <div className="pen-main-angle">
            <p className="pen-section-eyebrow"><Sparkles aria-hidden="true" /> Main angle</p>
            <Input aria-label="Story title" value={main.title ?? ""} placeholder="Add a story title" disabled={!ready} onChange={(event) => setMain("title", event.target.value)} />
            <Textarea aria-label="Story description" value={main.description ?? ""} placeholder="Add the angle and supporting context" disabled={!ready} onChange={(event) => setMain("description", event.target.value)} />
          </div>
          <div className="pen-forced-main"><Pin aria-hidden="true" /><div><span>Forced main footage</span><p>{packageId ? `${packageId}${pkg ? ` · ${pkg.total_duration_sec.toFixed(1)}s` : ""}` : "No forced main footage attached"}</p></div><small>{pkg ? "Attached" : packageId ? "Unavailable" : "None"}</small></div>
          <p className="pen-field-label">Footage &amp; scenes</p>
          <div className="pen-footage-list">
            {footage.length === 0 && <p className="pen-empty-state">No footage in this content set.</p>}
            {footage.map((item, index) => {
              const source = imgSrc(item.thumbnail ?? item.image_path);
              return <div key={`${item.url ?? "footage"}-${index}`} className="pen-footage-row">
                <span className="pen-footage-thumbnail">{source ? <img src={source} alt="" /> : <ImageIcon aria-hidden="true" />}</span>
                <span className="pen-footage-copy"><strong>{item.title ?? item.url ?? "Untitled footage"}</strong><small>{item.description ?? item.platform ?? "Source footage"}</small></span>
                <span className="pen-footage-duration" title={typeof item.duration_sec === "number" ? undefined : "Duration is not supplied"}>{typeof item.duration_sec === "number" ? `${item.duration_sec}s` : "—"}</span>
                <Button className="pen-remove-footage" size="icon-xs" variant="ghost" aria-label="Remove footage" disabled={running || saving} onClick={() => removeAt("footage", index)}><X aria-hidden="true" /></Button>
              </div>;
            })}
          </div>
        </section>
        <aside className="contentset-context" aria-label="Evidence and context">
          <div className="contentset-context-heading"><p className="pen-section-eyebrow">Evidence &amp; context</p><h2>What supports this story</h2></div>
          <details className="pen-evidence-group pen-evidence-comments">
            <summary><span className="pen-evidence-icon"><MessageSquare aria-hidden="true" /></span><span><strong>Comments <em>{comments.length}</em></strong><small>Audience language and questions</small></span><ChevronRight aria-hidden="true" /></summary>
            <div className="pen-evidence-items">{comments.length === 0 && <p>No comments in this content set.</p>}{comments.map((item, index) => <div key={`${item.author ?? "comment"}-${index}`}><strong>{item.author ?? "Unknown author"}</strong><p>{item.text}</p>{imgSrc(item.image_path) && <img src={imgSrc(item.image_path)} alt="Comment capture" />}<Button size="icon-xs" variant="ghost" aria-label="Remove comment" disabled={running || saving} onClick={() => removeAt("comments", index)}><X aria-hidden="true" /></Button></div>)}</div>
          </details>
          <details className="pen-evidence-group pen-evidence-figures">
            <summary><span className="pen-evidence-icon"><UserRound aria-hidden="true" /></span><span><strong>Figures <em>{String(figures.length).padStart(2, "0")}</em></strong><small>People and creators referenced</small></span><ChevronRight aria-hidden="true" /></summary>
            <div className="pen-evidence-items">{figures.length === 0 && <p>No figures in this content set.</p>}{figures.map((item, index) => <div key={`${item.name ?? "figure"}-${index}`}><strong>{item.name}</strong><p>{[item.kind, item.role].filter(Boolean).join(" · ")}</p><p>{item.description}</p><Button size="icon-xs" variant="ghost" aria-label="Remove figure" disabled={running || saving} onClick={() => removeAt("figures", index)}><X aria-hidden="true" /></Button></div>)}</div>
          </details>
          <details className="pen-evidence-group pen-evidence-references">
            <summary><span className="pen-evidence-icon"><BookOpen aria-hidden="true" /></span><span><strong>References <em>{references.length}</em></strong><small>Sources linked to the brief</small></span><ChevronRight aria-hidden="true" /></summary>
            <div className="pen-evidence-items">{references.length === 0 && <p>No references in this content set.</p>}{references.map((item, index) => <div key={`${item.term ?? "reference"}-${index}`}><strong>{item.term}</strong><p>{item.kind}</p><p>{item.summary}</p><Button size="icon-xs" variant="ghost" aria-label="Remove reference" disabled={running || saving} onClick={() => removeAt("references", index)}><X aria-hidden="true" /></Button></div>)}</div>
          </details>
          <div className="pen-import-readiness"><CircleCheck aria-hidden="true" /><span>{ready ? "Review source compatibility in Studio" : "Source brief is not available"}</span></div>
        </aside>
      </div>
      {(unavailable || notice || running) && <p className="pen-surface-notice" role="status">{unavailable ?? notice ?? "Scout busy — save disabled"}</p>}
      {ready && <details className="pen-operational-details"><summary>Source file &amp; package details</summary><div className="pen-operation-panel"><p className="pen-source-path">{data?.path}</p>{mainImg && <img className="pen-source-image" src={mainImg} alt="Source thumbnail" />}{packageId && <>
        <h3>Forced main ({packageId})</h3>
        {!pkg ? <p>Package facts unavailable — it may already have been deleted.</p> : <div data-testid="forced-main-facts"><p>{pkg.platform} · {pkg.usable_count} usable · {pkg.skipped_count} skipped · {pkg.ignored_count} ignored</p><p>{pkg.total_duration_sec.toFixed(1)}s · {formatBytes(pkg.total_bytes)} across {pkg.file_count} files</p><p>mode: {pkg.analysis_mode ?? "unknown"} · fingerprint: {(pkg.fingerprint ?? "—").replace(/^sha256:/, "").slice(0, 12)}</p>{pkg.warnings.length > 0 && <ul>{pkg.warnings.map((code) => <li key={code}>{describeCode(code)}</li>)}</ul>}</div>}
        <CleanupButton id={packageId} trigger="Delete package" disabled={running} disabledReason="Scout is running and may still be writing into this package" onCleanup={cleanupPackage} onDone={() => setPkgNonce((value) => value + 1)} />
      </>}</div></details>}
      {logLines.length > 0 && <div className="pen-validation-log"><LogPane lines={logLines} /></div>}
    </div>
  );
}
