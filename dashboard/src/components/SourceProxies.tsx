import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CircleAlert, CircleCheck, Info, LockKeyhole, Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageActions } from "@/components/PageActions";
import { PenDialog } from "@/components/PenDialog";
import { errorText, platformLabel, type ProxyImportSummary, type SourceAccountsClient, type SourceProxy } from "@/api/source-accounts";

function summaryText(summary: ProxyImportSummary): string {
  const parts = [`${summary.added} added`];
  if (summary.duplicates) parts.push(`${summary.duplicates} duplicate${summary.duplicates === 1 ? "" : "s"} skipped`);
  if (summary.invalid_lines.length) {
    const count = summary.invalid_lines.length;
    parts.push(`${count} invalid line${count === 1 ? "" : "s"} (line${count === 1 ? "" : "s"} ${summary.invalid_lines.join(", ")})`);
  }
  return parts.join(", ");
}

function ImportProxiesDialog({ open, onOpenChange, client, onImported }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onImported: () => void;
}) {
  const [text, setText] = useState("");
  const [summary, setSummary] = useState<ProxyImportSummary | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const reset = () => { setText(""); setSummary(null); setError(""); };
  useEffect(() => { if (open) reset(); }, [open]);
  const lines = text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")).length;

  async function submit() {
    setSaving(true);
    setError("");
    try {
      setSummary(await client.importProxies(text));
      setText("");
      onImported();
    } catch (failure) {
      setError(errorText(failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow="Proxy pool" title="Import proxies"
    description="Paste one proxy per line or upload a .txt file." className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-proxy-lines">Proxy lines</label>
        <Textarea id="sa-proxy-lines" className="sa-secret-text" placeholder="http://user:pass@host:port"
          value={text} onChange={(event) => setText(event.target.value)} />
        <p className="sa-field-hint">{lines ? `${lines} lines ready` : "One per line"} · http, https, or socks5 · credentials optional</p>
      </div>
      {summary && <p role="status" className="sa-validation sa-validation--ok"><CircleCheck aria-hidden="true" />{summaryText(summary)}</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
      <label className="sa-upload-row"><Upload aria-hidden="true" />Upload .txt instead
        <input type="file" accept=".txt,text/plain" aria-label="Proxy list file"
          onChange={async (event) => { const file = event.target.files?.[0]; if (file) setText(await file.text()); }} />
      </label>
      <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />Credentials are never shown after import.</p>
    </div>
    <footer className="sa-dialog-footer">
      {summary ? <>
        <Button variant="ghost" onClick={reset}>Import another file</Button>
        <Button onClick={() => onOpenChange(false)}>Done</Button>
      </> : <>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button disabled={saving || !lines} onClick={submit}>Import proxies</Button>
      </>}
    </footer>
  </PenDialog>;
}

export function SourceProxies({ client, onBack }: { client: SourceAccountsClient; onBack: () => void }) {
  const [proxies, setProxies] = useState<SourceProxy[] | null>(null);
  const [importing, setImporting] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setProxies(await client.proxies());
      setError("");
    } catch (failure) {
      setProxies([]);
      setError(errorText(failure));
    }
  }, [client]);
  useEffect(() => { void load(); }, [load]);

  async function remove(proxy: SourceProxy) {
    if (confirming !== proxy.id) {
      setConfirming(proxy.id);
      return;
    }
    setConfirming(null);
    try {
      await client.removeProxy(proxy.id);
      await load();
    } catch (failure) {
      setError(errorText(failure));
    }
  }

  const assigned = proxies?.filter((proxy) => proxy.account_label !== null).length ?? 0;
  const total = proxies?.length ?? 0;
  const pad = (value: number) => String(value).padStart(2, "0");

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onBack}><ArrowLeft aria-hidden="true" />Back to accounts</Button>
      <Button onClick={() => setImporting(true)}>Import proxies<Plus aria-hidden="true" /></Button>
    </PageActions>
    <p className="sa-banner"><Info aria-hidden="true" />Each proxy can serve one account. Assign it while adding or editing an account.</p>
    {error && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{error}</p>}
    <section className="sa-card sa-counts" aria-label="Proxy counts">
      {([["total", total], ["assigned", assigned], ["unassigned", total - assigned]] as const).map(([name, value]) =>
        <div key={name}><strong>{pad(value)}</strong><span>{name}</span></div>)}
    </section>
    <section className="sa-card sa-table" aria-label="Proxy pool">
      <header><h2>Proxy pool</h2><span>{pad(total)} proxies</span></header>
      {total ? <table className="sa-proxies-table">
        <thead><tr>{["Proxy", "Scheme", "Assigned to", "Actions"].map((name) => <th key={name}>{name}</th>)}</tr></thead>
        <tbody>{proxies!.map((proxy, index) => {
          const held = proxy.account_label !== null;
          // The position keeps two proxies on one host and port apart for a screen reader.
          const name = `proxy ${index + 1}, ${proxy.display}`;
          const sure = confirming === proxy.id;
          return <tr key={proxy.id}>
            <td className="sa-label">{proxy.display}</td>
            <td><span className="sa-chip">{proxy.scheme}</span></td>
            <td>{held ? `${platformLabel(proxy.account_platform ?? "")} · ${proxy.account_label}` : "Unassigned"}</td>
            <td><div className="sa-row-actions"><button type="button" disabled={held}
              title={held ? "Assigned to an account" : undefined} aria-label={`${sure ? "Confirm delete" : "Delete"} ${name}`}
              onClick={() => remove(proxy)}>{sure ? "Confirm delete" : "Delete"}</button></div></td>
          </tr>;
        })}</tbody>
      </table> : proxies && <div className="sa-empty">
        <strong>No proxies yet</strong>
        <p>Import a list of dedicated proxies, one per line. Each account can then use its own.</p>
        <Button onClick={() => setImporting(true)}>Import proxies<Plus aria-hidden="true" /></Button>
      </div>}
      <p className="sa-footnote">Only host and port are displayed. Credentials are stored privately.</p>
    </section>
    <ImportProxiesDialog open={importing} onOpenChange={setImporting} client={client} onImported={() => void load()} />
  </div>;
}
