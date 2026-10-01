import { useCallback, useEffect, useState } from "react";
import {
  createProfile,
  duplicateProfile,
  listProfileRevisions,
  listProfiles,
  restoreProfileRevision,
  updateProfile,
  validateProfile,
  CLIP_STYLES,
  LAYOUTS,
  PROVIDERS,
  WHISPER_MODELS,
  type ProfileRecord,
  type ProfileRevision,
  type ProfileSettings,
  type ProfileValidation,
} from "@/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import { Check, Copy, Grip, Mountain, Plus, Search } from "lucide-react";
import { PageActions } from "@/components/PageActions";

// Mirrors `ProfileSettings::default()` in crates/thoth-jobs/src/profiles.rs so a
// brand-new profile is valid the moment it's created (the server validates it).
const DEFAULT_SETTINGS: ProfileSettings = {
  schema_version: 1,
  narration: { enabled: true, language: null },
  visual_edit: {
    layout: "vertical",
    clip_style: "fade",
    style_profile: "auto",
    social: "",
    bgm: null,
    bgm_volume: 0.12,
    sfx_intro: null,
    headline_dur: 4,
  },
  analysis: { provider: "novita", model: "medium", max_clips: 3, keywords: [] },
  ingest_source: { source: null, content_set: null },
  output: { directory: null },
  advanced: {},
};

type Draft = {
  name: string;
  description: string;
  credentialRef: string;
  settings: ProfileSettings;
};

function draftFrom(profile: ProfileRecord): Draft {
  return {
    name: profile.name,
    description: profile.description,
    credentialRef: profile.credential_ref ?? "",
    settings: structuredClone(profile.settings),
  };
}

function blankDraft(): Draft {
  return { name: "", description: "", credentialRef: "", settings: structuredClone(DEFAULT_SETTINGS) };
}

/** Empty string becomes `null` for the server's nullable settings fields. */
function orNull(value: string): string | null {
  const trimmed = value.trim();
  return trimmed === "" ? null : trimmed;
}

/**
 * Profile Studio: browse a project's profiles (left), edit the six typed
 * settings groups (center), and validate / inspect revisions (right).
 */
export function ProfileStudio({
  projectId,
  onProfileChanged,
}: {
  projectId: string;
  onProfileChanged?: () => void;
}) {
  const [profiles, setProfiles] = useState<ProfileRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [revisions, setRevisions] = useState<ProfileRevision[]>([]);
  const [validation, setValidation] = useState<ProfileValidation | null>(null);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");

  const refresh = useCallback(async () => {
    try {
      setProfiles(await listProfiles(projectId));
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    void refresh();
    setSelectedId(null);
    setCreating(false);
    setDraft(null);
  }, [refresh]);

  const editing = creating || selectedId !== null;

  function patchSettings(update: (s: ProfileSettings) => void) {
    setDraft((current) => {
      if (!current) return current;
      const next = structuredClone(current);
      update(next.settings);
      return next;
    });
  }

  function startNew() {
    setSelectedId(null);
    setCreating(true);
    setDraft(blankDraft());
    setRevisions([]);
    setValidation(null);
    setError(null);
  }

  async function selectProfile(profile: ProfileRecord) {
    setCreating(false);
    setSelectedId(profile.id);
    setDraft(draftFrom(profile));
    setValidation(null);
    setError(null);
    setRevisions(await listProfileRevisions(projectId, profile.id));
  }

  async function save() {
    if (!draft) return;
    if (draft.name.trim() === "") {
      setError("Profile name is required.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      const body = {
        name: draft.name.trim(),
        description: draft.description,
        settings: draft.settings,
        credential_ref: orNull(draft.credentialRef),
      };
      const saved =
        selectedId !== null
          ? await updateProfile(projectId, selectedId, body)
          : await createProfile(projectId, body);
      await refresh();
      await selectProfile(saved);
      onProfileChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save profile.");
    } finally {
      setSaving(false);
    }
  }

  async function duplicate() {
    if (selectedId === null || !draft) return;
    setError(null);
    try {
      const copy = await duplicateProfile(projectId, selectedId, `${draft.name} copy`);
      await refresh();
      await selectProfile(copy);
      onProfileChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to duplicate profile.");
    }
  }

  async function runValidation() {
    // The server validates against an existing profile's scope, so a profile
    // must be saved first. The button is disabled until then; guard anyway.
    if (!draft || selectedId === null) return;
    setValidation(await validateProfile(projectId, selectedId, draft.settings));
  }

  async function restore(revisionId: string) {
    if (selectedId === null) return;
    setError(null);
    try {
      const restored = await restoreProfileRevision(projectId, selectedId, revisionId);
      await refresh();
      await selectProfile(restored);
      onProfileChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore revision.");
    }
  }

  const s = draft?.settings;

  return (
    <div className="profile-workspace pen-profiles">
      <PageActions><Button onClick={startNew}>New profile <Plus size={14} /></Button></PageActions>
      {/* Left: profile list */}
      <aside className="profile-list flex min-h-0 flex-col gap-3">
        <div className="flex items-center justify-between">
          <h2 className="text-sm font-semibold">Your profiles</h2>
          <span className="profile-count">{String(profiles.length).padStart(2, "0")}</span>
        </div>
        <div className="pen-profile-search"><Search size={14} /><Input aria-label="Find a profile" placeholder="Find a profile" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <ScrollArea className="min-h-0 flex-1">
          {loading ? (
            <p className="p-3 text-sm text-muted-foreground">Loading profiles…</p>
          ) : profiles.length === 0 ? (
            <p className="p-3 text-sm text-muted-foreground">
              No profiles yet. Create one to get started.
            </p>
          ) : (
            <ul className="pen-profile-items">
              {profiles.filter((profile) => `${profile.name} ${profile.description}`.toLowerCase().includes(search.toLowerCase())).map((profile) => (
                <li key={profile.id}>
                  <button
                    type="button"
                    onClick={() => void selectProfile(profile)}
                    className={cn(
                      "pen-profile-item",
                      selectedId === profile.id && "is-selected",
                    )}
                  >
                    <span className="block truncate">{profile.name}</span>
                    {profile.description ? (
                      <span className="block truncate text-xs text-muted-foreground">
                        {profile.description}
                      </span>
                    ) : null}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </ScrollArea>
        <p className="pen-profile-footnote">Profiles apply to new runs and can be refined at any time.</p>
      </aside>

      {/* Center: editor */}
      <section className="pen-profile-editor">
        {!editing || !draft || !s ? (
          <div className="flex h-full min-h-40 items-center justify-center text-sm text-muted-foreground">
            No profile selected. Pick one on the left or create a new profile.
          </div>
        ) : (
          <form
            className="pen-profile-form"
            onSubmit={(e) => {
              e.preventDefault();
              void save();
            }}
          >
            <div className="pen-profile-editor-heading">
              <div className="grid gap-2">
                <Label htmlFor="profile-name" className="pen-eyebrow">Creative profile</Label>
                <Input
                  id="profile-name"
                  aria-label="Profile name"
                  value={draft.name}
                  onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                  placeholder="Untitled profile"
                />
              </div>
              <div className="pen-profile-save-actions">
                <Button type="button" variant="secondary" onClick={() => void duplicate()} disabled={selectedId === null}>Duplicate <Copy size={14} /></Button>
                <Button type="button" aria-label="Save profile" onClick={() => void save()} disabled={saving}>{saving ? "Saving…" : "Save changes"} <Check size={14} /></Button>
              </div>
            </div>
            <div className="pen-profile-description">
                <Label htmlFor="profile-desc">Description</Label>
                <textarea
                  id="profile-desc"
                  value={draft.description}
                  onChange={(e) => setDraft({ ...draft, description: e.target.value })}
                  placeholder="Describe this profile’s creative direction."
                />
            </div>
            <div className="pen-profile-summary">
              <div><h3>Voice &amp; tone</h3><div className="pen-profile-summary-card"><strong>{s.narration.enabled ? "Narration enabled" : "Narration disabled"}</strong><span>{s.narration.language || "Auto-detect language"}</span></div></div>
              <div><h3>Visual language</h3><div className="pen-profile-summary-card"><strong>{s.visual_edit.style_profile}</strong><span>{s.visual_edit.layout} · {s.visual_edit.clip_style}</span></div></div>
            </div>
            <div className="pen-profile-principles">
              <h3 title="Creative principles are unavailable in the profile API; these rows summarize actual production settings.">Production principles</h3>
              {[`${s.analysis.provider} · ${s.analysis.model} analysis`, `Up to ${s.analysis.max_clips} clips per run`, `${s.visual_edit.headline_dur}s headline · ${Math.round(s.visual_edit.bgm_volume * 100)}% music volume`].map((value, index) => <div className="pen-profile-principle" key={index}><span>{String(index + 1).padStart(2, "0")}</span>{value}<Grip size={14} aria-hidden="true" /></div>)}
            </div>
            <details className="pen-profile-settings"><summary>All profile settings</summary>
            <Fieldset legend="Narration">
              <Field label="Narrator mode" htmlFor="nar-enabled">
                <input
                  id="nar-enabled"
                  type="checkbox"
                  checked={s.narration.enabled}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.narration.enabled = e.target.checked;
                    })
                  }
                  className="size-4 accent-primary"
                />
              </Field>
              <Field label="Language" htmlFor="nar-lang">
                <Input
                  id="nar-lang"
                  value={s.narration.language ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.narration.language = orNull(e.target.value);
                    })
                  }
                  placeholder="Auto-detect"
                />
              </Field>
            </Fieldset>

            <Fieldset legend="Visual edit">
              <Field label="Layout" htmlFor="ve-layout">
                <Select
                  value={s.visual_edit.layout}
                  onValueChange={(v) =>
                    patchSettings((n) => {
                      n.visual_edit.layout = String(v);
                    })
                  }
                >
                  <SelectTrigger id="ve-layout" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {LAYOUTS.map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Clip style" htmlFor="ve-clip">
                <Select
                  value={s.visual_edit.clip_style}
                  onValueChange={(v) =>
                    patchSettings((n) => {
                      n.visual_edit.clip_style = String(v);
                    })
                  }
                >
                  <SelectTrigger id="ve-clip" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {CLIP_STYLES.map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Style profile" htmlFor="ve-style">
                <Input
                  id="ve-style"
                  value={s.visual_edit.style_profile}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.style_profile = e.target.value;
                    })
                  }
                />
              </Field>
              <Field label="Social" htmlFor="ve-social">
                <Input
                  id="ve-social"
                  value={s.visual_edit.social}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.social = e.target.value;
                    })
                  }
                />
              </Field>
              <Field label="BGM path" htmlFor="ve-bgm">
                <Input
                  id="ve-bgm"
                  value={s.visual_edit.bgm ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.bgm = orNull(e.target.value);
                    })
                  }
                  placeholder="None"
                />
              </Field>
              <Field label="BGM volume" htmlFor="ve-bgmvol">
                <Input
                  id="ve-bgmvol"
                  type="number"
                  step="0.01"
                  min="0"
                  max="1"
                  value={s.visual_edit.bgm_volume}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.bgm_volume = Number(e.target.value);
                    })
                  }
                />
              </Field>
              <Field label="SFX intro path" htmlFor="ve-sfx">
                <Input
                  id="ve-sfx"
                  value={s.visual_edit.sfx_intro ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.sfx_intro = orNull(e.target.value);
                    })
                  }
                  placeholder="None"
                />
              </Field>
              <Field label="Headline duration (s)" htmlFor="ve-headline">
                <Input
                  id="ve-headline"
                  type="number"
                  step="0.5"
                  min="0"
                  value={s.visual_edit.headline_dur}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.visual_edit.headline_dur = Number(e.target.value);
                    })
                  }
                />
              </Field>
            </Fieldset>

            <Fieldset legend="Analysis">
              <Field label="Provider" htmlFor="an-provider">
                <Select
                  value={s.analysis.provider}
                  onValueChange={(v) =>
                    patchSettings((n) => {
                      n.analysis.provider = String(v);
                    })
                  }
                >
                  <SelectTrigger id="an-provider" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {PROVIDERS.map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Model" htmlFor="an-model">
                <Select
                  value={s.analysis.model}
                  onValueChange={(v) =>
                    patchSettings((n) => {
                      n.analysis.model = String(v);
                    })
                  }
                >
                  <SelectTrigger id="an-model" className="w-full">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WHISPER_MODELS.map((v) => (
                      <SelectItem key={v} value={v}>
                        {v}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </Field>
              <Field label="Max clips" htmlFor="an-maxclips">
                <Input
                  id="an-maxclips"
                  type="number"
                  min="1"
                  value={s.analysis.max_clips}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.analysis.max_clips = Number(e.target.value);
                    })
                  }
                />
              </Field>
              <Field label="Keywords (comma-separated)" htmlFor="an-keywords">
                <Input
                  id="an-keywords"
                  value={s.analysis.keywords.join(", ")}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.analysis.keywords = e.target.value
                        .split(",")
                        .map((k) => k.trim())
                        .filter(Boolean);
                    })
                  }
                />
              </Field>
            </Fieldset>

            <Fieldset legend="Ingest source">
              <Field label="Source URL" htmlFor="in-source">
                <Input
                  id="in-source"
                  value={s.ingest_source.source ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.ingest_source.source = orNull(e.target.value);
                    })
                  }
                  placeholder="None (set per run)"
                />
              </Field>
              <Field label="Content-set path" htmlFor="in-cset">
                <Input
                  id="in-cset"
                  value={s.ingest_source.content_set ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.ingest_source.content_set = orNull(e.target.value);
                    })
                  }
                  placeholder="None"
                />
              </Field>
            </Fieldset>

            <Fieldset legend="Output">
              <Field label="Output directory" htmlFor="out-dir">
                <Input
                  id="out-dir"
                  value={s.output.directory ?? ""}
                  onChange={(e) =>
                    patchSettings((n) => {
                      n.output.directory = orNull(e.target.value);
                    })
                  }
                  placeholder="Managed by Thoth home"
                />
              </Field>
            </Fieldset>

            <Fieldset legend="Credential">
              <Field label="Credential reference" htmlFor="cred-ref">
                <Input
                  id="cred-ref"
                  value={draft.credentialRef}
                  onChange={(e) => setDraft({ ...draft, credentialRef: e.target.value })}
                  placeholder="e.g. OPENAI_API_KEY (name only, never the secret)"
                />
              </Field>
              <p className="text-xs text-muted-foreground">
                A non-secret reference name. The secret value is resolved on the
                server and never entered or shown here.
              </p>
            </Fieldset>

            </details>
            <p className="pen-profile-availability">Creative principles are unavailable. The rows above show current production settings.</p>
            {error ? <p className="text-sm text-destructive">{error}</p> : null}

            <div className="flex gap-2">
              {/* A visually-hidden submit button enables real Enter-to-save via
                  the form's onSubmit. The visible button uses onClick so a click
                  saves even where the DOM doesn't synthesize a submit on click —
                  it is type=button, so the two paths never double-fire. */}
              <button type="submit" className="sr-only" tabIndex={-1} aria-hidden="true" />
            </div>
          </form>
        )}
      </section>

      {/* Right: validation + revisions */}
      <aside className="pen-profile-preview">
        <span className="pen-eyebrow">Live preview</span>
        <h2>How it feels</h2>
        <div className="pen-profile-preview-art" aria-hidden="true"><Mountain size={44} strokeWidth={2} /></div>
        <span className="pen-eyebrow">{s ? `${s.visual_edit.layout} · ${s.visual_edit.clip_style}` : "Awaiting selection"}</span>
        <h3>{draft?.name || "Your creative voice"}</h3>
        <p className="pen-profile-preview-description">{draft?.description || "Choose a profile to see its saved description and production settings."}</p>
        <details className="pen-profile-tools"><summary>Validation &amp; revisions</summary>
        <div className="rounded-md border p-3">
          <div className="flex items-center justify-between">
            <h3 className="text-sm font-semibold">Validation</h3>
            <Button
              size="sm"
              variant="outline"
              onClick={() => void runValidation()}
              disabled={selectedId === null}
              title={selectedId === null ? "Save the profile first" : undefined}
            >
              Validate
            </Button>
          </div>
          {validation ? (
            <p
              className={cn(
                "mt-2 text-sm",
                validation.valid ? "text-status-succeeded" : "text-destructive",
              )}
            >
              {validation.valid ? "Settings are valid." : validation.message}
            </p>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">Not checked yet.</p>
          )}
        </div>

        <div className="rounded-md border p-3">
          <h3 className="text-sm font-semibold">Revisions</h3>
          {selectedId === null ? (
            <p className="mt-2 text-sm text-muted-foreground">
              Save a profile to start tracking revisions.
            </p>
          ) : revisions.length === 0 ? (
            <p className="mt-2 text-sm text-muted-foreground">No earlier revisions.</p>
          ) : (
            <ul className="mt-2 divide-y">
              {revisions.map((rev) => (
                <li key={rev.id} className="flex items-center justify-between py-2 text-sm">
                  <span className="text-muted-foreground">
                    r{rev.revision} · {rev.name}
                  </span>
                  <Button size="sm" variant="ghost" onClick={() => void restore(rev.id)}>
                    Restore
                  </Button>
                </li>
              ))}
            </ul>
          )}
        </div>
        </details>
        <p className="pen-profile-footnote">Workflow usage is unavailable.</p>
      </aside>
    </div>
  );
}

function Fieldset({ legend, children }: { legend: string; children: React.ReactNode }) {
  return (
    <fieldset className="grid gap-3 rounded-md border p-3">
      <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
        {legend}
      </legend>
      <div className="grid gap-3 sm:grid-cols-2">{children}</div>
    </fieldset>
  );
}

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-2">
      <Label htmlFor={htmlFor}>{label}</Label>
      {children}
    </div>
  );
}
