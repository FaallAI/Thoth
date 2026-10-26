import { useEffect, useRef, useState, type ReactNode } from "react";
import { LockKeyhole, Upload } from "lucide-react";
import { PenDialog } from "@/components/PenDialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
  PLATFORMS,
  REQUIRED_COOKIES,
  SourceAccountsRequestError,
  errorKey,
  platformLabel,
  type CookieValidation,
  type SourceAccount,
  type SourceAccountsClient,
  type SourcePlatform,
  type SourceProxy,
} from "@/api/source-accounts";
import { useLocale } from "@/lib/locale";

const DIRECT = "direct";
const VALIDATE_DELAY_MS = 250;

type Copy = ReturnType<typeof useLocale>;
type T = Copy["t"];

function failureText(t: T, error: unknown): string {
  if (error instanceof SourceAccountsRequestError && error.missing.length) {
    return t("sa.missing", { names: error.missing.join(", ") });
  }
  return t(errorKey(error));
}

function validationText({ t, plural }: Copy, platform: SourcePlatform, result: CookieValidation): string {
  if (result.error === "missing_required_cookie") {
    return t("sa.missingFor", { names: result.missing.join(", "), platform: platformLabel(platform) });
  }
  if (result.error === "all_cookies_expired") return t("sa.allExpired");
  if (result.error) return t("sa.unreadable");
  const names = result.names.join(", ");
  return result.earliest_expiry
    ? plural("sa.foundExpiring", result.count, { names, date: result.earliest_expiry.slice(0, 10) })
    : plural("sa.found", result.count, { names });
}

/** A cookie export from a file or a paste, validated by the server; values are never shown. */
function CookieInput({ platform, client, onChange }: {
  platform: SourcePlatform;
  client: SourceAccountsClient;
  onChange: (text: string, valid: boolean) => void;
}) {
  const copy = useLocale();
  const { t } = copy;
  const [mode, setMode] = useState<"file" | "paste">("file");
  const [text, setText] = useState("");
  const [fileName, setFileName] = useState("");
  const [result, setResult] = useState<CookieValidation | null>(null);
  const [failed, setFailed] = useState(false);
  // The parent passes a fresh closure each render; only the export and platform revalidate.
  const report = useRef(onChange);
  report.current = onChange;

  useEffect(() => {
    if (!text) {
      setResult(null);
      report.current("", false);
      return;
    }
    let live = true;
    const timer = setTimeout(() => {
      client.validate(platform, text).then(
        (validation) => {
          if (!live) return;
          setResult(validation);
          setFailed(false);
          report.current(text, validation.valid);
        },
        () => {
          if (!live) return;
          setResult(null);
          setFailed(true);
          report.current(text, false);
        },
      );
    }, VALIDATE_DELAY_MS);
    return () => {
      live = false;
      clearTimeout(timer);
    };
  }, [text, platform, client]);

  return <div className="sa-cookie-input">
    <div className="sa-segmented" role="group" aria-label={t("sa.cookieSource")}>
      {(["file", "paste"] as const).map((option) => <button key={option} type="button"
        aria-pressed={mode === option} onClick={() => setMode(option)}>
        {t(option === "file" ? "sa.file" : "sa.paste")}</button>)}
    </div>
    {mode === "file" ? <label className="sa-dropzone">
      <Upload aria-hidden="true" />
      <strong>{fileName || t("sa.chooseFile")}</strong>
      <small>{t("sa.fileHint")}</small>
      <input type="file" accept=".txt,.json,text/plain,application/json" aria-label={t("sa.fileLabel")}
        onChange={async (event) => {
          const file = event.target.files?.[0];
          if (!file) return;
          setFileName(file.name);
          setText(await file.text());
        }} />
    </label> : <Textarea aria-label={t("sa.pasteLabel")} className="sa-secret-text" placeholder={t("sa.pastePlaceholder")}
      value={text} onChange={(event) => { setFileName(""); setText(event.target.value); }} />}
    <p className="sa-field-hint">{t("sa.required", { platform: platformLabel(platform), cookies: REQUIRED_COOKIES[platform].join(" & ") })}</p>
    {result && <p role="status" className={result.valid ? "sa-validation sa-validation--ok" : "sa-validation sa-validation--error"}>
      {validationText(copy, platform, result)}</p>}
    {failed && <p role="alert" className="sa-validation sa-validation--error">{t("sa.checkFailed")}</p>}
    <p className="sa-lock-note"><LockKeyhole aria-hidden="true" />{t("sa.lockNote")}</p>
  </div>;
}

/** Direct, or one pool proxy; a proxy another account holds is shown but cannot be chosen. */
function ProxySelect({ proxies, value, onChange, currentProxyId, currentDisplay, onImportProxies }: {
  proxies: SourceProxy[];
  value: string | null;
  onChange: (proxyId: string | null) => void;
  currentProxyId?: string | null;
  currentDisplay?: string | null;
  onImportProxies: () => void;
}) {
  const { t } = useLocale();
  const selected = proxies.find((proxy) => proxy.id === value);
  // A held proxy missing from the list (not loaded yet, or the list failed) still shows by name.
  const shown = selected?.display ?? (value ? (value === currentProxyId && currentDisplay) || t("sa.unlisted") : t("sa.direct"));
  return <div className="sa-field">
    <label htmlFor="sa-proxy">{t("sa.proxy")}</label>
    <Select value={value ?? DIRECT} onValueChange={(next) => onChange(next === DIRECT ? null : String(next))}>
      <SelectTrigger id="sa-proxy" aria-label={t("sa.proxy")} className="sa-select"><SelectValue>{shown}</SelectValue></SelectTrigger>
      <SelectContent>
        <SelectItem value={DIRECT}><span className="sa-option"><strong>{t("sa.direct")}</strong><small>{t("sa.noProxy")}</small></span></SelectItem>
        {proxies.map((proxy) => {
          const held = proxy.account_label !== null && proxy.id !== currentProxyId;
          return <SelectItem key={proxy.id} value={proxy.id} disabled={held}>
            <span className="sa-option"><strong>{proxy.display}</strong>
              <small>{held ? t("sa.inUse", { platform: platformLabel(proxy.account_platform ?? ""), label: proxy.account_label ?? "" }) : t("sa.available")}</small></span>
          </SelectItem>;
        })}
      </SelectContent>
    </Select>
    {proxies.length ? <p className="sa-field-hint">{t("sa.proxyHint")}</p>
      : <p className="sa-field-hint">{t("sa.noProxies")} <button type="button" className="sa-link" onClick={onImportProxies}>{t("sa.importFirst")}</button></p>}
  </div>;
}

function Footer({ children }: { children: ReactNode }) {
  return <footer className="sa-dialog-footer">{children}</footer>;
}

export function AddAccountDialog({ open, onOpenChange, client, platform: initialPlatform, proxies, onSaved, onImportProxies }: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  platform: SourcePlatform;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onImportProxies: () => void;
}) {
  const { t } = useLocale();
  const [platform, setPlatform] = useState<SourcePlatform>(initialPlatform);
  const [label, setLabel] = useState("");
  const [proxyId, setProxyId] = useState<string | null>(null);
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setPlatform(initialPlatform);
      setLabel("");
      setProxyId(null);
      setCookies({ text: "", valid: false });
      setError("");
    }
  }, [open, initialPlatform]);

  async function save() {
    setSaving(true);
    setError("");
    try {
      onSaved(await client.create({ platform, label: label.trim(), cookies: cookies.text, proxy_id: proxyId }));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(t, failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open={open} onOpenChange={onOpenChange} eyebrow={t("sa.sourceAccess")} title={t("sa.add")}
    description={t("sa.addDescription")} className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field">
        <label htmlFor="sa-platform">{t("sa.platform")}</label>
        <Select value={platform} onValueChange={(next) => setPlatform(next as SourcePlatform)}>
          <SelectTrigger id="sa-platform" aria-label={t("sa.platform")} className="sa-select"><SelectValue>{platformLabel(platform)}</SelectValue></SelectTrigger>
          <SelectContent>{PLATFORMS.map((entry) => <SelectItem key={entry.id} value={entry.id}>{entry.label}</SelectItem>)}</SelectContent>
        </Select>
      </div>
      <div className="sa-field">
        <label htmlFor="sa-label">{t("sa.label")}</label>
        <Input id="sa-label" maxLength={64} placeholder={t("sa.labelPlaceholder")} value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} onImportProxies={onImportProxies} />
      <div className="sa-field">
        <span className="sa-field-label">{t("sa.cookieExport")}</span>
        <CookieInput key={`${open}`} platform={platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
      <Button disabled={saving || !label.trim() || !cookies.valid} onClick={save}>{t("sa.import")}</Button>
    </Footer>
  </PenDialog>;
}

export function ReimportDialog({ account, onOpenChange, client, onSaved }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  onSaved: (account: SourceAccount) => void;
}) {
  const { t } = useLocale();
  const [cookies, setCookies] = useState({ text: "", valid: false });
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setCookies({ text: "", valid: false });
    setError("");
  }, [account?.id]);
  if (!account) return null;

  async function save() {
    if (!account) return;
    setSaving(true);
    setError("");
    try {
      onSaved(await client.reimport(account.id, cookies.text));
      onOpenChange(false);
    } catch (failure) {
      setError(failureText(t, failure));
    } finally {
      setSaving(false);
    }
  }

  return <PenDialog open onOpenChange={onOpenChange} eyebrow={t("sa.sourceAccess")} title={t("sa.reimportTitle")}
    description={t("sa.reimportDescription")} className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">{t("sa.account")}</span>
        <p className="sa-readonly">{platformLabel(account.platform)} · {account.label}</p></div>
      <div className="sa-field">
        <span className="sa-field-label">{t("sa.cookieExport")}</span>
        <CookieInput key={account.id} platform={account.platform} client={client} onChange={(text, valid) => setCookies({ text, valid })} />
      </div>
      {cookies.valid && <p className="sa-field-hint">{t("sa.reimportReady")}</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
      <Button disabled={saving || !cookies.valid} onClick={save}>{t("sa.replace")}</Button>
    </Footer>
  </PenDialog>;
}

export function EditAccountDialog({ account, onOpenChange, client, proxies, onSaved, onDeleted, onImportProxies }: {
  account: SourceAccount | null;
  onOpenChange: (open: boolean) => void;
  client: SourceAccountsClient;
  proxies: SourceProxy[];
  onSaved: (account: SourceAccount) => void;
  onDeleted: (accountId: string) => void;
  onImportProxies: () => void;
}) {
  const { t } = useLocale();
  const [label, setLabel] = useState(account?.label ?? "");
  const [proxyId, setProxyId] = useState<string | null>(account?.proxy_id ?? null);
  const [locale, setLocale] = useState(account?.locale ?? "");
  const [timezone, setTimezone] = useState(account?.timezone ?? "");
  const [confirming, setConfirming] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setLabel(account?.label ?? "");
    setProxyId(account?.proxy_id ?? null);
    setLocale(account?.locale ?? "");
    setTimezone(account?.timezone ?? "");
    setConfirming(false);
    setResetting(false);
    setError("");
  }, [account]);

  if (!account) return null;
  const disabled = account.status === "disabled";

  async function run(action: () => Promise<void>) {
    setSaving(true);
    setError("");
    try {
      await action();
    } catch (failure) {
      setError(failureText(t, failure));
    } finally {
      setSaving(false);
    }
  }

  const save = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, {
      label: label.trim(),
      proxy_id: proxyId,
      ...(locale.trim() !== account.locale ? { locale: locale.trim() } : {}),
      ...(timezone.trim() !== account.timezone ? { timezone: timezone.trim() } : {}),
    }));
    onOpenChange(false);
  });
  const resetFingerprint = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { reset_fingerprint: true }));
    onOpenChange(false);
  });
  const toggle = () => run(async () => {
    if (!account) return;
    onSaved(await client.update(account.id, { disabled: !disabled }));
    onOpenChange(false);
  });
  const remove = () => run(async () => {
    if (!account) return;
    await client.remove(account.id);
    onDeleted(account.id);
    onOpenChange(false);
  });

  return <PenDialog open onOpenChange={onOpenChange} eyebrow={t("sa.settings")} title={t("sa.editTitle")}
    description={t("sa.editDescription")} className="sa-dialog">
    <div className="sa-dialog-body">
      <div className="sa-field"><span className="sa-field-label">{t("sa.platform")}</span>
        <p className="sa-readonly">{platformLabel(account.platform)}</p></div>
      <div className="sa-field">
        <label htmlFor="sa-edit-label">{t("sa.label")}</label>
        <Input id="sa-edit-label" maxLength={64} value={label} onChange={(event) => setLabel(event.target.value)} />
      </div>
      <ProxySelect proxies={proxies} value={proxyId} onChange={setProxyId} currentProxyId={account.proxy_id}
        currentDisplay={account.proxy_display} onImportProxies={onImportProxies} />
      <p className="sa-field-hint">{t("sa.oneProxy")}</p>
      <div className="sa-field">
        <label htmlFor="sa-edit-locale">{t("sa.locale")}</label>
        <Input id="sa-edit-locale" maxLength={6} value={locale} onChange={(event) => setLocale(event.target.value)} />
      </div>
      <div className="sa-field">
        <label htmlFor="sa-edit-timezone">{t("sa.timezone")}</label>
        <Input id="sa-edit-timezone" maxLength={64} value={timezone} onChange={(event) => setTimezone(event.target.value)} />
      </div>
      <p className="sa-field-hint">{t("sa.matchProxy")}</p>
      <div className="sa-field"><span className="sa-field-label">{t("sa.fingerprint")}</span>
        <p className="sa-readonly">{t(account.fingerprint_set ? "sa.fingerprintSet" : "sa.fingerprintUnset")}</p></div>
      {resetting
        ? <><p role="alert" className="sa-validation sa-validation--error">{t("sa.resetConfirmText", { label: account.label })}</p>
          <Button variant="destructive" disabled={saving} onClick={resetFingerprint}>{t("sa.resetConfirm")}</Button></>
        : <Button variant="ghost" disabled={saving} onClick={() => setResetting(true)}>{t("sa.reset")}</Button>}
      {confirming && <p role="alert" className="sa-validation sa-validation--error">{t("sa.deleteConfirmText", { label: account.label })}</p>}
      {error && <p role="alert" className="sa-validation sa-validation--error">{error}</p>}
    </div>
    <Footer>
      <div className="sa-footer-secondary">
        <Button variant="ghost" disabled={saving} onClick={toggle}>{t(disabled ? "sa.enable" : "sa.disable")}</Button>
        {confirming
          ? <Button variant="destructive" disabled={saving} onClick={remove}>{t("sa.deleteAccount")}</Button>
          : <Button variant="ghost" disabled={saving} onClick={() => setConfirming(true)}>{t("sa.delete")}</Button>}
      </div>
      <Button variant="ghost" onClick={() => onOpenChange(false)}>{t("common.cancel")}</Button>
      <Button disabled={saving || !label.trim()} onClick={save}>{t("sa.save")}</Button>
    </Footer>
  </PenDialog>;
}
