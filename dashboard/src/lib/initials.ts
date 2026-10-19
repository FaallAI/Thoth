import type { Me } from "@/api/auth";

/** Up to two capitals from the name, else the email's first letter. */
export function initials(me: Pick<Me, "display_name" | "email">): string {
  const words = (me.display_name ?? "").trim().split(/\s+/).filter(Boolean);
  const fromName = words.slice(0, 2).map((word) => word[0]!.toUpperCase()).join("");
  return fromName || (me.email?.[0]?.toUpperCase() ?? "?");
}
