// English and Indonesian copy for the dashboard (DESIGN §12.1, restyle spec D2).
//
// One catalogue per language with the same keys: the Indonesian one is typed against the
// English one, so a missing key is a compile error. Every sentence is a whole key, so word
// order can differ between the languages; nothing is assembled from fragments.

export type Locale = "en" | "id";
export const LOCALES: readonly Locale[] = ["en", "id"];

const en = {
  "nav.runs": "Runs",
  "nav.inbox": "Inbox",
  "nav.studio": "Studio",
  "nav.usage": "Usage",
  "nav.billing": "Billing",
  "nav.accounts": "Accounts",
  "nav.settings": "Settings",
  "nav.admin": "Admin",
  "nav.main": "Main navigation",
  "nav.collapse": "Collapse the sidebar",
  "nav.expand": "Expand the sidebar",
  "nav.menu": "Menu",

  "topbar.search": "Search runs, documents…",
  "topbar.inbox": "Inbox",
  "topbar.account": "Account menu",

  "tray.summary": "{running} running · {waiting} waiting",
  "tray.idle": "Nothing running",
  "tray.open": "Open the run tray",

  "inbox.count.one": "{count} decision waiting",
  "inbox.count.other": "{count} decisions waiting",

  "avatar.language": "Language",
  "avatar.settings": "Settings",
  "avatar.signOut": "Sign out",
  "language.en": "English",
  "language.id": "Bahasa Indonesia",

  "project.all": "All projects",
  "project.switch": "Switch project",
  "project.current": "Project: {name}",

  "palette.title": "Go to",
  "palette.placeholder": "Go to a page, project, run or document…",
  "palette.empty": "Nothing matches “{query}”.",
  "palette.pages": "Pages",
  "palette.projects": "Projects",
  "palette.runs": "Recent runs",
  "palette.documents": "Studio documents",

  "status.queued": "Queued",
  "status.running": "Running",
  "status.waiting": "Waiting for you",
  "status.succeeded": "Done",
  "status.failed": "Failed",
  "status.cancelled": "Cancelled",
  "status.skipped": "Skipped",
  "status.expired": "Expired",

  "stage.source": "Fetch the source",
  "stage.approval": "Your review",
  "stage.attribution": "Find the original",
  "stage.footage": "Collect footage",
  "stage.assembly": "Build the content set",

  "skip.attribution_off": "Attribution is off for this run",
  "skip.footage_off": "Footage is off for this run",
  "skip.assembly_off": "The content set is off for this run",
  "skip.legacy_source": "The legacy source path has nothing to build on",
  "skip.approval_rejected": "Stopped at your review",
  "skip.not_in_this_version": "Not part of this run's version",
  "skip.run_failed": "Not reached: the run failed",
  "skip.run_cancelled": "Not reached: the run was cancelled",

  // One sentence per run-progress step code (run-progress spec §5); `lib/steps.ts` reads them.
  "step.source.read_link": "Reading the link",
  "step.source.fetch_post": "Fetching the post from {platform}",
  "step.source.download_media": "Downloading the media",
  "step.source.capture_post_card": "Capturing the post card",
  "step.source.capture_comment_cards": "Capturing the comment cards",
  "step.source.gate_covered": "Comments hidden behind a sign-in prompt: {count}",
  "step.source.page_gap": "Pausing between pages",
  "step.source.capture_embed_cards": "Capturing the embedded post cards",
  "step.source.capture_profile": "Capturing the creator's profile",
  "step.source.login_wall": "The page asked for a sign-in",
  "step.source.save_report": "Saving the source report",
  "step.attribution.read_text": "Reading the text on screen",
  "step.attribution.ask_vision": "Asking the vision model",
  "step.attribution.search_candidates": "Candidate videos found: {count}",
  "step.attribution.compare_frames": "Comparing frames",
  "step.attribution.verdict.original": "This post is the original",
  "step.attribution.verdict.replaced": "Found the original elsewhere",
  "step.attribution.verdict.unresolved": "No original found",
  "step.footage.plan_queries": "Search queries planned: {count}",
  "step.footage.search_platforms": "Searching {platform}",
  "step.footage.screen_clips": "Screening the clips",
  "step.footage.creator_listing": "Reading the creator's videos",
  "step.footage.keep_clips": "Clips kept: {count}",
  "step.assembly.read_subtitles": "Reading the subtitles",
  "step.assembly.judge_comments": "Comments kept: {count} of {total}",
  "step.assembly.find_figures": "People identified: {count}",
  "step.assembly.save_content_set": "Saving the content set",

  "time.today": "Today, {time}",
  "time.yesterday": "Yesterday, {time}",
  "time.day": "{date}, {time}",

  "estimate.minutes": "About {minutes} min left",
  "estimate.fewMinutes": "A few minutes left",

  "common.loading": "Loading…",
  "common.retry": "Try again",
  "common.cancel": "Cancel",
  "common.close": "Close",
  "common.unavailable": "Unavailable",
} as const;

export type MessageKey = keyof typeof en;
type Messages = Record<MessageKey, string>;

const id: Messages = {
  "nav.runs": "Run",
  "nav.inbox": "Kotak masuk",
  "nav.studio": "Studio",
  "nav.usage": "Pemakaian",
  "nav.billing": "Tagihan",
  "nav.accounts": "Akun",
  "nav.settings": "Pengaturan",
  "nav.admin": "Admin",
  "nav.main": "Navigasi utama",
  "nav.collapse": "Ciutkan bilah samping",
  "nav.expand": "Bentangkan bilah samping",
  "nav.menu": "Menu",

  "topbar.search": "Cari run, dokumen…",
  "topbar.inbox": "Kotak masuk",
  "topbar.account": "Menu akun",

  "tray.summary": "{running} berjalan · {waiting} menunggu",
  "tray.idle": "Tidak ada yang berjalan",
  "tray.open": "Buka baki run",

  "inbox.count.one": "{count} keputusan menunggu",
  "inbox.count.other": "{count} keputusan menunggu",

  "avatar.language": "Bahasa",
  "avatar.settings": "Pengaturan",
  "avatar.signOut": "Keluar",
  "language.en": "English",
  "language.id": "Bahasa Indonesia",

  "project.all": "Semua proyek",
  "project.switch": "Ganti proyek",
  "project.current": "Proyek: {name}",

  "palette.title": "Buka",
  "palette.placeholder": "Buka halaman, proyek, run, atau dokumen…",
  "palette.empty": "Tidak ada yang cocok dengan “{query}”.",
  "palette.pages": "Halaman",
  "palette.projects": "Proyek",
  "palette.runs": "Run terbaru",
  "palette.documents": "Dokumen Studio",

  "status.queued": "Antre",
  "status.running": "Berjalan",
  "status.waiting": "Menunggu Anda",
  "status.succeeded": "Selesai",
  "status.failed": "Gagal",
  "status.cancelled": "Dibatalkan",
  "status.skipped": "Dilewati",
  "status.expired": "Kedaluwarsa",

  "stage.source": "Ambil sumber",
  "stage.approval": "Tinjauan Anda",
  "stage.attribution": "Cari yang asli",
  "stage.footage": "Kumpulkan footage",
  "stage.assembly": "Susun content set",

  "skip.attribution_off": "Atribusi dimatikan untuk run ini",
  "skip.footage_off": "Footage dimatikan untuk run ini",
  "skip.assembly_off": "Content set dimatikan untuk run ini",
  "skip.legacy_source": "Jalur sumber lama tidak menyediakan bahan",
  "skip.approval_rejected": "Berhenti di tinjauan Anda",
  "skip.not_in_this_version": "Tidak ada di versi run ini",
  "skip.run_failed": "Tidak tercapai: run gagal",
  "skip.run_cancelled": "Tidak tercapai: run dibatalkan",

  "step.source.read_link": "Membaca tautan",
  "step.source.fetch_post": "Mengambil postingan dari {platform}",
  "step.source.download_media": "Mengunduh media",
  "step.source.capture_post_card": "Menangkap kartu postingan",
  "step.source.capture_comment_cards": "Menangkap kartu komentar",
  "step.source.gate_covered": "Komentar tertutup ajakan masuk akun: {count}",
  "step.source.page_gap": "Jeda antarhalaman",
  "step.source.capture_embed_cards": "Menangkap kartu postingan sematan",
  "step.source.capture_profile": "Menangkap profil kreator",
  "step.source.login_wall": "Halaman meminta masuk akun",
  "step.source.save_report": "Menyimpan laporan sumber",
  "step.attribution.read_text": "Membaca teks di layar",
  "step.attribution.ask_vision": "Bertanya ke model visi",
  "step.attribution.search_candidates": "Video kandidat ditemukan: {count}",
  "step.attribution.compare_frames": "Membandingkan frame",
  "step.attribution.verdict.original": "Postingan ini yang asli",
  "step.attribution.verdict.replaced": "Yang asli ditemukan di tempat lain",
  "step.attribution.verdict.unresolved": "Yang asli tidak ditemukan",
  "step.footage.plan_queries": "Kueri pencarian disusun: {count}",
  "step.footage.search_platforms": "Mencari di {platform}",
  "step.footage.screen_clips": "Menyaring klip",
  "step.footage.creator_listing": "Membaca video kreator",
  "step.footage.keep_clips": "Klip disimpan: {count}",
  "step.assembly.read_subtitles": "Membaca subtitle",
  "step.assembly.judge_comments": "Komentar dipertahankan: {count} dari {total}",
  "step.assembly.find_figures": "Tokoh dikenali: {count}",
  "step.assembly.save_content_set": "Menyimpan content set",

  "time.today": "Hari ini, {time}",
  "time.yesterday": "Kemarin, {time}",
  "time.day": "{date}, {time}",

  "estimate.minutes": "Sekitar {minutes} mnt lagi",
  "estimate.fewMinutes": "Beberapa menit lagi",

  "common.loading": "Memuat…",
  "common.retry": "Coba lagi",
  "common.cancel": "Batal",
  "common.close": "Tutup",
  "common.unavailable": "Tidak tersedia",
};

export const messages: { en: Messages; id: Messages } = { en, id };

/** The BCP 47 tag `Intl` formats with. */
const TAG: Record<Locale, string> = { en: "en-US", id: "id-ID" };

export type Values = Record<string, string | number>;

export function translate(locale: Locale, key: MessageKey, values: Values = {}): string {
  return messages[locale][key].replace(/\{(\w+)\}/g, (hole, name: string) =>
    name in values ? String(values[name]) : hole,
  );
}

/** Keys with `.one`/`.other` forms, named without the suffix. */
export type PluralKey = {
  [K in MessageKey]: K extends `${infer Base}.other` ? Base : never;
}[MessageKey];

export function plural(locale: Locale, key: PluralKey, count: number, values: Values = {}): string {
  const rule = new Intl.PluralRules(TAG[locale]).select(count);
  const form = `${key}.${rule}` in messages[locale] ? `${key}.${rule}` : `${key}.other`;
  return translate(locale, form as MessageKey, { count: formatNumber(locale, count), ...values });
}

export function formatNumber(locale: Locale, value: number): string {
  return new Intl.NumberFormat(TAG[locale]).format(value);
}

/** Compact durations in both languages: "2m 24s" / "2 mnt 24 dtk", "1h 5m" / "1 jam 5 mnt". */
export function formatDuration(locale: Locale, totalSeconds: number): string {
  const seconds = Math.max(0, Math.round(totalSeconds));
  const hours = Math.floor(seconds / 3_600);
  const minutes = Math.floor((seconds % 3_600) / 60);
  const rest = seconds % 60;
  const units = locale === "id" ? { h: " jam", m: " mnt", s: " dtk" } : { h: "h", m: "m", s: "s" };
  if (hours > 0) return `${hours}${units.h} ${minutes}${units.m}`;
  if (minutes > 0) return `${minutes}${units.m} ${rest}${units.s}`;
  return `${rest}${units.s}`;
}

function dayKey(moment: Date, timeZone?: string): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit" }).format(
    moment,
  );
}

/** A time as a list reads it: "Today, 14:02", "Yesterday, 18:47", "Oct 20, 18:47". */
export function formatDay(locale: Locale, iso: string, now: Date = new Date(), timeZone?: string): string {
  const moment = new Date(iso);
  const time = new Intl.DateTimeFormat(TAG[locale], {
    timeZone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(moment);
  const yesterday = new Date(now.getTime() - 86_400_000);
  if (dayKey(moment, timeZone) === dayKey(now, timeZone)) return translate(locale, "time.today", { time });
  if (dayKey(moment, timeZone) === dayKey(yesterday, timeZone)) {
    return translate(locale, "time.yesterday", { time });
  }
  const date = new Intl.DateTimeFormat(TAG[locale], { timeZone, month: "short", day: "numeric" }).format(moment);
  return translate(locale, "time.day", { date, time });
}

/** The first language: the browser's first preference, Indonesian or else English. */
export function browserLocale(preferences: readonly string[]): Locale {
  return preferences[0]?.toLowerCase().startsWith("id") ? "id" : "en";
}
