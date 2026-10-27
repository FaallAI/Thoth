// The platforms a run can start from (DESIGN §8.2): their names and how a link is recognised.

export const PLATFORMS = ["tiktok", "x", "instagram", "youtube", "threads"] as const;
export type Platform = (typeof PLATFORMS)[number];

/** Platform names are proper nouns, the same in both languages. */
export const PLATFORM_NAMES: Record<string, string> = {
  tiktok: "TikTok",
  instagram: "Instagram",
  x: "X",
  youtube: "YouTube",
  threads: "Threads",
};

const HOSTS: [string, Platform][] = [
  ["tiktok.com", "tiktok"],
  ["x.com", "x"],
  ["twitter.com", "x"],
  ["instagram.com", "instagram"],
  ["youtube.com", "youtube"],
  ["youtu.be", "youtube"],
  ["threads.net", "threads"],
  ["threads.com", "threads"],
];

/** The platform of a link, or null for another host or text that is not a web link. */
export function detectPlatform(text: string): Platform | null {
  let host: string;
  try {
    const url = new URL(text.trim());
    if (url.protocol !== "https:" && url.protocol !== "http:") return null;
    host = url.hostname.toLowerCase();
  } catch {
    return null;
  }
  const found = HOSTS.find(([domain]) => host === domain || host.endsWith(`.${domain}`));
  return found ? found[1] : null;
}

/** The host a list row shows under its title, without "www.". */
export function displayHost(link: string): string {
  try {
    return new URL(link).hostname.replace(/^www\./, "");
  } catch {
    return link;
  }
}
