import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ArrowRight, ArrowUpRight, CircleCheck, RefreshCw, Search, ChevronDown } from "lucide-react";
import { PageActions } from "@/components/PageActions";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { LogPane, type LogLine } from "@/components/LogPane";
import {
  scoutStatus, scoutStartBrowser, scoutDiscover, scoutRun, scoutValidate, scoutCancel,
  scoutTopics, scoutContentSet, streamScout,
  type ScoutStatus, type ScoutTopic, type ScoutLogLine,
} from "@/api";

const NOT_READY_REASON =
  "Unavailable: this server is paired with a Scout install that has no main-footage planner.";

/** Discovery surface: drives the scout browser -> discover -> run -> validate flow. */
export function Discovery() {
  const [status, setStatus] = useState<ScoutStatus | null>(null);
  const [topics, setTopics] = useState<ScoutTopic[]>([]);
  const [lines, setLines] = useState<ScoutLogLine[]>([]);
  const [url, setUrl] = useState("");
  const [maxPer, setMaxPer] = useState("");
  const [hours, setHours] = useState("");
  const [include, setInclude] = useState("");
  const [tiktok, setTiktok] = useState(false);
  const [per, setPer] = useState("");
  const [max, setMax] = useState("");
  const [cap, setCap] = useState("");
  const [noComments, setNoComments] = useState(false);
  const [useInputAsMain, setUseInputAsMain] = useState(false);
  const [contentSet, setContentSet] = useState<{ path: string; exists: boolean } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const esRef = useRef<EventSource | null>(null);

  const runStatus = status?.run?.status;
  const running = runStatus === "running";
  // Forced main footage needs the Scout planner module this server is paired with.
  // Until the server has answered, treat it as not ready: offering the control and
  // withdrawing it looks like a bug, and a run started without a planner dies partway
  // through instead of refusing up front.
  const mainFootageReady = status?.main_footage_ready === true;

  // Poll status every 3s.
  useEffect(() => {
    let alive = true;
    const tick = async () => { const s = await scoutStatus(); if (alive) setStatus(s); };
    tick();
    const id = setInterval(tick, 3000);
    return () => { alive = false; clearInterval(id); };
  }, []);
  useEffect(() => {
    let alive = true;
    if (runStatus && runStatus !== "running") {
      scoutTopics().then((topics) => { if (alive) setTopics(topics); });
      scoutContentSet().then((set) => { if (alive) setContentSet(set); });
    }
    return () => { alive = false; };
  }, [runStatus]);
  useEffect(() => {
    if (!running) { esRef.current?.close(); esRef.current = null; return; }
    setLines([]);
    const stream = streamScout(0, (line) => setLines((previous) => [...previous, line]));
    esRef.current = stream;
    return () => stream.close();
  }, [running, status?.run?.started_at]);
  const num = (value: string): number | undefined => value.trim() === "" ? undefined : Number(value);
  const ack = (label: string) => (result: { ok: boolean; status: number; error?: string }) => {
    if (!result.ok) setNotice(`${label}: ${result.status === 409 ? "already running" : result.error ?? result.status}`);
    else setNotice(null);
    scoutStatus().then(setStatus);
  };
  const logLines: LogLine[] = lines.map((line) => ({ id: String(line.seq), ts: "", text: line.text, kind: line.stream === "err" ? "error" : "log" }));
  const discover = () => scoutDiscover({ max_per: num(maxPer), hours: num(hours), include: include.trim() || undefined, tiktok }).then(ack("discover"));
  const run = () => scoutRun({ url: url.trim(), per: num(per), max: num(max), cap: num(cap), no_comments: noComments, use_input_as_main: useInputAsMain && mainFootageReady }).then((result) => {
    ack("run")(result);
    if (result.ok) setUseInputAsMain(false);
  });
  const selectedTopic = topics.find((topic) => topic.url === url);

  return (
    <div className="discovery-workspace pen-discovery">
      <PageActions><Button className="pen-secondary-action" disabled={running} onClick={discover}>Refresh signals <RefreshCw aria-hidden="true" /></Button></PageActions>
      <div className="discovery-steps" aria-label="Discovery flow">
        {[["01", "Discover", "Source signals"], ["02", "Topics", "Shape the angle"], ["03", "Run pipeline", "Generate assets"], ["04", "Validate", "Review output"]].map(([number, title, hint]) => (
          <div key={number} className={number === (running ? "03" : topics.length ? "02" : "01") ? "is-active" : undefined}><span>{number}</span><p>{title}<small>{hint}</small></p></div>
        ))}
      </div>
      <div className="pen-discovery-columns">
        <section className="pen-signal-sources" aria-label="Source signals">
          <p className="pen-section-eyebrow">Source signals</p><h2>Explore the feed</h2>
          <div className="pen-platform-tabs" aria-label="Signal platforms">
            <button aria-pressed={tiktok} onClick={() => setTiktok(!tiktok)} title="Include TikTok signals in the Scout scan">TikTok</button>
            <button aria-pressed={false} onClick={() => setNotice("YouTube-only discovery is not available from this Scout server.")}>YouTube</button>
            <button aria-pressed={false} onClick={() => setNotice("Saved signals are not available from this Scout server.")}>Saved</button>
          </div>
          <label className="pen-field-label" htmlFor="disc-query">Search query</label>
          <div className="pen-signal-search-field"><Search aria-hidden="true" /><Input id="disc-query" placeholder="Search source signals" value={include} onChange={(event) => setInclude(event.target.value)} /></div>
          <div className="pen-signal-filters">
            <label><span className="pen-field-label">Window</span><select aria-label="Window" value={["", "24", "168", "720"].includes(hours) ? hours : "custom"} onChange={(event) => { if (event.target.value !== "custom") setHours(event.target.value); }}><option value="">Scout default</option><option value="24">Past 24 hours</option><option value="168">Past 7 days</option><option value="720">Past 30 days</option>{!["", "24", "168", "720"].includes(hours) && <option value="custom">{hours} hours</option>}</select></label>
            <div><span className="pen-field-label">Region</span><button className="pen-select-unavailable" onClick={() => setNotice("Region filtering is not available from this Scout server.")} title="Region filtering is unavailable">Global <ChevronDown aria-hidden="true" /></button></div>
          </div>
          <div className="pen-signal-summary"><p className="pen-field-label">Scan summary</p><dl>{[["Videos", "—"], ["Clusters", "—"], ["Saved", "—"]].map(([label, value]) => <div key={label} title={`${label} totals are not provided by Scout`}><dd>{value}</dd><dt>{label}</dt></div>)}</dl></div>
        </section>
        <section className="pen-topic-candidates" aria-label="Topic candidates">
          <header><div><p className="pen-section-eyebrow">Curated from your signals</p><h2>Topic candidates</h2></div><span className="pen-topic-count">{topics.length} ideas</span></header>
          <div className="discovery-topic-list">
            {topics.length === 0 && <p className="pen-empty-state">Run Discover to collect topic candidates. Choose a topic to use its source in the pipeline.</p>}
            {topics.map((topic, index) => (
              <button key={`${topic.url}-${index}`} aria-pressed={url === topic.url} className="pen-discovery-topic" title={topic.url} onClick={() => setUrl(topic.url)}>
                <span className="pen-topic-index">{String(index + 1).padStart(2, "0")}</span><span className="pen-topic-copy"><strong>{topic.title ?? topic.url}</strong><small>{topic.platform ?? "Source signal"}</small></span><span className="pen-topic-score"><strong>{typeof topic.score === "number" ? topic.score : "—"}</strong><small>{typeof topic.score === "number" ? "Source score" : "Score unavailable"}</small></span><ArrowUpRight aria-hidden="true" />
              </button>
            ))}
          </div>
        </section>
      </div>
      <div className="pen-discovery-footer"><p><CircleCheck aria-hidden="true" /><span>{selectedTopic ? `${selectedTopic.title ?? selectedTopic.url} selected for production` : url.trim() ? "Source URL selected for production" : "Select a topic for production"}</span></p><Button disabled={running || url.trim() === ""} onClick={run}>Build content brief <ArrowRight aria-hidden="true" /></Button></div>
      {notice && <p role="status" className="pen-surface-notice">{notice}</p>}
      <details className="pen-operational-details">
        <summary>Scout controls &amp; pipeline options</summary>
        <div className="pen-operations-grid">
          <section className="pen-operation-panel"><h3>Browser &amp; discovery</h3><p>Browser {status?.browser_attached ? "attached" : "not attached"} <small>{status?.cdp_base}</small></p><Button disabled={running} onClick={() => scoutStartBrowser().then(ack("browser"))}>Start browser</Button>{running && <Button variant="destructive" onClick={() => scoutCancel().then(ack("cancel"))}>Cancel ({status?.run?.kind})</Button>}<Label htmlFor="disc-max-per">max_per</Label><Input id="disc-max-per" value={maxPer} onChange={(event) => setMaxPer(event.target.value)} /><Label htmlFor="disc-hours">hours</Label><Input id="disc-hours" value={hours} onChange={(event) => setHours(event.target.value)} /><Button disabled={running} onClick={discover}>Discover</Button></section>
          <section className="pen-operation-panel"><h3>Run pipeline</h3><Label htmlFor="run-url">topic url</Label><Input id="run-url" placeholder="https://…" value={url} onChange={(event) => setUrl(event.target.value)} /><div className="pen-run-limits"><label>per<Input aria-label="per" value={per} onChange={(event) => setPer(event.target.value)} /></label><label>max<Input aria-label="max" value={max} onChange={(event) => setMax(event.target.value)} /></label><label>cap<Input aria-label="cap" value={cap} onChange={(event) => setCap(event.target.value)} /></label></div><label title={mainFootageReady ? undefined : NOT_READY_REASON}><input type="checkbox" disabled={!mainFootageReady} checked={useInputAsMain && mainFootageReady} onChange={(event) => setUseInputAsMain(event.target.checked)} /> Use URL media as main footage</label><small>Download every video from this post, ignore photos, and build narration-aligned cuts.</small><small>{mainFootageReady ? "Narrator mode is required." : NOT_READY_REASON}</small><label><input type="checkbox" checked={noComments} onChange={(event) => setNoComments(event.target.checked)} /> no-comments</label><Button disabled={running || url.trim() === ""} onClick={run}>Run pipeline</Button><Button disabled={running || !contentSet?.path} onClick={() => contentSet?.path && scoutValidate(contentSet.path).then(ack("validate"))}>Validate content-set</Button>{contentSet && <small>{contentSet.exists ? "content-set: " : "content-set (missing): "}{contentSet.path}</small>}</section>
        </div>
      </details>
      {(running || logLines.length > 0) && <div className="discovery-log"><LogPane lines={logLines} /></div>}
    </div>
  );
}
