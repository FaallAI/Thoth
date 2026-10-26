// A finished run's results (DESIGN §8.6): the main, real card crops, footage, figures, comments.
import { Building2, Check, Heart, ImageIcon, User, Users } from "lucide-react";
import type { ReactNode } from "react";

import type { ControlPlaneClient } from "@/api/control-plane";
import { PlatformIcon } from "@/components/PlatformIcon";
import { useLocale } from "@/lib/locale";
import { PLATFORM_NAMES } from "@/lib/platforms";

/** The parts of a Content Set (schema 1) this page shows; the server validates the whole. */
type Media = { location: string; media_type: string; duration_seconds?: number | null };
export type ContentSet = {
  attribution_verdict: "original" | "replaced" | "unresolved" | "none";
  style_a?: boolean;
  main: {
    title?: string;
    owner_handle: string;
    platform: string;
    kind: "video" | "images" | "card";
    video?: Media | null;
    images?: Media[];
    card?: Media | null;
    post_card?: Media | null;
    profile_card?: Media | null;
    profile_page?: Media | null;
  };
  comments: { author: string; text: string; likes: number; card?: Media | null }[];
  figures: { name: string; type: "person" | "organization" | "community"; role?: string }[];
  footage: { platform: string; owner_handle: string; video: Media }[];
};

const FIGURE_ICONS = { person: User, organization: Building2, community: Users } as const;

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <h3 className="text-sm text-muted-ink">{title}</h3>
      {children}
    </section>
  );
}

export function RunResults({
  set,
  workflowId,
  client,
}: {
  set: ContentSet;
  workflowId: string;
  client: Pick<ControlPlaneClient, "mediaUrl">;
}) {
  const { t, plural, duration, number } = useLocale();
  const url = (media: Media) => client.mediaUrl(workflowId, media.location);
  const main = set.main;
  const still = main.post_card ?? main.card ?? main.images?.[0] ?? null;
  const cards: { label: string; media: Media | null | undefined }[] = [
    { label: t("results.card.post"), media: main.post_card ?? main.card },
    { label: t("results.card.profile"), media: main.profile_card },
    { label: t("results.card.profilePage"), media: main.profile_page },
  ];
  const commentCards = set.comments.filter((comment) => comment.card);
  const verdict = set.attribution_verdict === "none" ? null : set.attribution_verdict;

  return (
    <div className="flex flex-col gap-8">
      <Section title={t("results.main")}>
        <div className="flex items-center gap-4">
          {main.video ? (
            <video src={url(main.video)} preload="metadata" muted controls className="h-28 w-20 shrink-0 rounded-md bg-well object-cover" />
          ) : still ? (
            <img src={url(still)} alt="" className="h-28 w-20 shrink-0 rounded-md bg-well object-cover object-top" />
          ) : null}
          <div className="min-w-0">
            {main.title && <p className="text-base font-semibold text-ink">{main.title}</p>}
            <p className="text-sm text-muted-ink">
              @{main.owner_handle} · {PLATFORM_NAMES[main.platform] ?? main.platform}
              {main.video?.duration_seconds ? ` · ${duration(main.video.duration_seconds)}` : ""}
            </p>
            {verdict && (
              <span className="mt-2 inline-flex items-center gap-1.5 rounded-full bg-raised px-2.5 py-0.5 text-sm text-status-done">
                <Check aria-hidden="true" className="size-3.5" />
                {t(`results.verdict.${verdict}`)}
              </span>
            )}
          </div>
        </div>
      </Section>

      <Section title={t("results.cards")}>
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {cards.map(({ label, media }) =>
            media ? (
              <figure key={label} className="flex flex-col gap-2">
                <img src={url(media)} alt={label} className="w-full rounded-md bg-well" />
                <figcaption className="text-sm text-muted-ink">{label}</figcaption>
              </figure>
            ) : set.style_a ? (
              <figure key={label} className="flex flex-col gap-2">
                <div className="grid aspect-[4/5] place-items-center rounded-md bg-well text-sm text-faint">{t("results.notCaptured")}</div>
                <figcaption className="text-sm text-muted-ink">{label}</figcaption>
              </figure>
            ) : null,
          )}
          {commentCards.length > 0 && (
            <figure className="flex flex-col gap-2">
              {commentCards.slice(0, 3).map((comment) => (
                <img key={comment.card!.location} src={url(comment.card!)} alt={`@${comment.author}`} className="w-full rounded-md bg-well" />
              ))}
              <figcaption className="text-sm text-muted-ink">{t("results.card.comments", { count: commentCards.length })}</figcaption>
            </figure>
          )}
        </div>
      </Section>

      {set.footage.length > 0 && (
        <Section title={plural("results.footage", set.footage.length)}>
          <div className="flex flex-wrap gap-3">
            {set.footage.map((clip) => (
              <div key={clip.video.location} className="relative">
                <video src={url(clip.video)} preload="metadata" muted controls className="size-28 rounded-md bg-well object-cover" aria-label={`@${clip.owner_handle}`} />
                <span className="absolute bottom-1.5 left-1.5 grid size-6 place-items-center rounded-full bg-bg/80 text-ink">
                  <PlatformIcon platform={clip.platform} label className="size-3.5" />
                </span>
              </div>
            ))}
          </div>
        </Section>
      )}

      {set.figures.length > 0 && (
        <Section title={t("results.figures")}>
          <ul className="flex flex-col gap-2.5">
            {set.figures.map((figure) => {
              const Icon = FIGURE_ICONS[figure.type];
              return (
                <li key={figure.name} className="flex items-center gap-3 text-sm">
                  <Icon aria-hidden="true" className="size-4 text-muted-ink" />
                  <span className="text-base text-ink">{figure.name}</span>
                  <span className="text-muted-ink">
                    {t(`results.figure.${figure.type}`)}
                    {figure.role ? ` · ${figure.role}` : ""}
                  </span>
                </li>
              );
            })}
          </ul>
        </Section>
      )}

      {set.comments.length > 0 && (
        <Section title={t("results.comments", { count: set.comments.length })}>
          <ul className="flex flex-col gap-3">
            {set.comments.map((comment, index) => (
              <li key={`${comment.author}-${index}`} className="grid grid-cols-[1.25rem_10rem_1fr_auto] items-start gap-3 text-sm">
                {comment.card ? <ImageIcon role="img" aria-label={t("results.hasCard")} className="size-4 text-muted-ink" /> : <span />}
                <span className="truncate text-ink">@{comment.author}</span>
                <span className="text-ink">{comment.text}</span>
                <span className="inline-flex items-center gap-1 text-muted-ink">
                  <Heart aria-hidden="true" className="size-3.5" />
                  {number(comment.likes)}
                </span>
              </li>
            ))}
          </ul>
        </Section>
      )}
    </div>
  );
}
