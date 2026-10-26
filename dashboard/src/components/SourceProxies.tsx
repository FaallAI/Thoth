import { useCallback, useEffect, useState } from "react";
import { ArrowLeft, CircleAlert, CircleCheck, Info, LockKeyhole, Plus, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { PageActions } from "@/components/PageActions";
import { PenDialog } from "@/components/PenDialog";
import { errorKey, platformLabel, type ProxyImportSummary, type SourceAccountsClient, type SourceProxy } from "@/api/source-accounts";
import type { MessageKey } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";

function ImportProxiesDialog({ open, onOpenChange, client, onImported }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onImported: () => void;
}) {
  const { t, plural } = useLocale();
  const [text, setText] = useState("");
  const [summary, setSummary] = useState<ProxyImportSummary | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);
  const [saving, setSaving] = useState(false);
  const reset = () => { setText(""); setSummary(null); setError(null); };
  useEffect(() => { if (open) reset(); }, [open]);
  const lines = text.split(/\r?\n/).filter((line) => line.trim() && !line.trim().startsWith("#")).length;

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      setSummary(await client.importProxies(text));
      setText("");
      onImported();
    } catch (failure) {
      setError(errorKey(failure));
    } finally {
      setSaving(false);
    }
  }

  const summaryText = (done: ProxyImportSummary) => [
    t("px.added", { count: done.added }),
    done.duplicates ? plural("px.duplicates", done.duplicates) : null,
    done.invalid_lines.length ? plural("px.invalid", done.invalid_lines.length, { lines: done.invalid_lines.join(", ") }) : null,
  ].filter(Boolean).join(", ");

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow={t("px.poolEyebrow")} title={t("px.import")}
    description={t("px.importDescription")} className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-proxy-lines">{t("px.lines")}</label>
        <Textarea id="sa-proxy-lines" className="sa-secret-text" placeholder="http://user:pass@host:port"
          value={text} onChange={(event) => setText(event.target.value)} />
        <p className="sa-field-hint">{lines ? t("px.linesReady", { count: lines }) : t("px.onePerLine")} · {t("px.linesHint")}</p>
      </div>
      {summary && <p role="status" className="sa-validation sa-validation--ok"><CircleCheck aria-hidden="true" />{summaryText(summary)}</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{t(error)}</p>}
      <label className="sa-upload-row"><Upload aria-hidden="true" />{t("px.upload")}
        <input type="file" accept=".txt,text/plain" aria-label={t("px.fileLabel")}
          onChange={async (event) => { const file = event.target.files?.[0]; if (file) setText(await file.text()); }} />
      </label>
      <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />{t("px.lockNote")}</p>
    </div>
    <footer className="sa-dialog-footer">
      {summary ? <>
        <Button variant="ghost" onClick={reset}>{t("px.another")}</Button>
        <Button onClick={() => onOpenChange(false)}>{t("px.done")}</Button>
      </> : <>
        <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
        <Button disabled={saving || !lines} onClick={submit}>{t("px.import")}</Button>
      </>}
    </footer>
  </PenDialog>;
}

export function SourceProxies({ client, onBack }: { client: SourceAccountsClient; onBack: () => void }) {
  const { t, plural } = useLocale();
  const [proxies, setProxies] = useState<SourceProxy[] | null>(null);
  const [importing, setImporting] = useState(false);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<MessageKey | null>(null);

  const load = useCallback(async () => {
    try {
      setProxies(await client.proxies());
      setError(null);
    } catch (failure) {
      setProxies([]);
      setError(errorKey(failure));
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
      setError(errorKey(failure));
    }
  }

  const assigned = proxies?.filter((proxy) => proxy.account_label !== null).length ?? 0;
  const total = proxies?.length ?? 0;
  const pad = (value: number) => String(value).padStart(2, "0");

  return <div className="sa-page">
    <PageActions>
      <Button variant="secondary" onClick={onBack}><ArrowLeft aria-hidden="true" />{t("px.back")}</Button>
      <Button onClick={() => setImporting(true)}>{t("px.import")}<Plus aria-hidden="true" /></Button>
    </PageActions>
    <p className="sa-banner"><Info aria-hidden="true" />{t("px.banner")}</p>
    {error && <p role="alert" className="sa-banner sa-banner--error"><CircleAlert aria-hidden="true" />{t(error)}</p>}
    <section className="sa-card sa-counts" aria-label={t("px.counts")}>
      {([["px.total", total], ["px.assigned", assigned], ["px.unassigned", total - assigned]] as const).map(([name, value]) =>
        <div key={name}><strong>{pad(value)}</strong><span>{t(name)}</span></div>)}
    </section>
    <section className="sa-card sa-table" aria-label={t("px.pool")}>
      <header><h2>{t("px.pool")}</h2><span>{plural("px.count", total)}</span></header>
      {total ? <table className="sa-proxies-table">
        <thead><tr>{(["px.col.proxy", "px.col.scheme", "px.col.assigned", "px.col.actions"] as const).map((name) => <th key={name}>{t(name)}</th>)}</tr></thead>
        <tbody>{proxies!.map((proxy, index) => {
          const held = proxy.account_label !== null;
          // The position keeps two proxies on one host and port apart for a screen reader.
          const name = t("px.name", { index: index + 1, display: proxy.display });
          const sure = confirming === proxy.id;
          return <tr key={proxy.id}>
            <td className="sa-label">{proxy.display}</td>
            <td><span className="sa-chip">{proxy.scheme}</span></td>
            <td>{held ? `${platformLabel(proxy.account_platform ?? "")} · ${proxy.account_label}` : t("px.free")}</td>
            <td><div className="sa-row-actions"><button type="button" disabled={held}
              title={held ? t("px.held") : undefined} aria-label={t(sure ? "px.confirmDeleteLabel" : "px.deleteLabel", { name })}
              onClick={() => remove(proxy)}>{t(sure ? "px.confirmDelete" : "px.delete")}</button></div></td>
          </tr>;
        })}</tbody>
      </table> : proxies && <div className="sa-empty">
        <strong>{t("px.empty")}</strong>
        <p>{t("px.emptyHint")}</p>
        <Button onClick={() => setImporting(true)}>{t("px.import")}<Plus aria-hidden="true" /></Button>
      </div>}
      <p className="sa-footnote">{t("px.footnote")}</p>
    </section>
    <ImportProxiesDialog open={importing} onOpenChange={setImporting} client={client} onImported={() => void load()} />
  </div>;
}
