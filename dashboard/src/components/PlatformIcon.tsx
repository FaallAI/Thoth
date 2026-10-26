// Platform marks drawn in the lucide style (24 grid, 1.75 stroke); lucide ships no brand icons.
import { AtSign, Globe } from "lucide-react";

import { PLATFORM_NAMES } from "@/lib/platforms";
import { cn } from "@/lib/utils";

const PATHS: Record<string, string[]> = {
  tiktok: ["M14 3v11.5a3.5 3.5 0 1 1-3.5-3.5", "M14 3c.6 2.7 2.6 4.4 5 4.6"],
  x: ["M4 4l16 16", "M20 4L4 20"],
  instagram: ["M7 3h10a4 4 0 0 1 4 4v10a4 4 0 0 1-4 4H7a4 4 0 0 1-4-4V7a4 4 0 0 1 4-4z", "M12 8.5a3.5 3.5 0 1 0 0 7a3.5 3.5 0 0 0 0-7z", "M17.5 6.5h.01"],
  youtube: ["M4 6.5c3-1 13-1 16 0c1 2.5 1 8.5 0 11c-3 1-13 1-16 0c-1-2.5-1-8.5 0-11z", "M10 9.5v5l4.5-2.5z"],
};

/**
 * The platform's mark. With `label` it names the platform to assistive technology; without it
 * the mark is decoration beside a visible name.
 */
export function PlatformIcon({ platform, label = false, className }: { platform: string; label?: boolean; className?: string }) {
  const name = PLATFORM_NAMES[platform] ?? platform;
  const a11y = label ? { role: "img", "aria-label": name } : { "aria-hidden": true as const };
  const classes = cn("size-4 shrink-0", className);
  if (platform === "threads") return <AtSign {...a11y} className={classes} strokeWidth={1.75} />;
  const paths = PATHS[platform];
  if (!paths) return <Globe {...a11y} className={classes} strokeWidth={1.75} />;
  return (
    <svg
      {...a11y}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      strokeLinecap="round"
      strokeLinejoin="round"
      className={classes}
    >
      {paths.map((path) => (
        <path key={path} d={path} />
      ))}
    </svg>
  );
}
