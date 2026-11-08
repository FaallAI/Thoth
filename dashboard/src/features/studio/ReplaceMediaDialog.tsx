// Replace media (spec 2026-11-08 §5.1): another ready video of this project behind the same clip.
// The server swaps only a video clip's media, so only ready videos are offered.
import { useEffect, useRef } from "react";
import { Film, X } from "lucide-react";

import type { EditorAsset } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

type Props = {
  currentAssetId: string;
  assets: EditorAsset[];
  nameOf: (asset: EditorAsset) => string;
  onReplace: (assetId: string) => void;
  onClose: () => void;
};

export function ReplaceMediaDialog({ currentAssetId, assets, nameOf, onReplace, onClose }: Props) {
  const { t } = useLocale();
  const panel = useRef<HTMLDivElement>(null);
  const offered = assets.filter(
    (asset) => asset.kind === "video" && asset.validation_state === "ready" && asset.asset_id !== currentAssetId,
  );
  useEffect(() => panel.current?.focus(), []);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-bg/70 p-4" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div
        ref={panel}
        role="dialog"
        aria-modal="true"
        aria-label={t("studio.replace.title")}
        tabIndex={-1}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
        className="flex max-h-[80vh] w-full max-w-md flex-col gap-3 rounded-lg border border-hairline bg-raised p-4 outline-none"
      >
        <header className="flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink">{t("studio.replace.title")}</h2>
          <button type="button" aria-label={t("studio.media.close")} onClick={onClose} className="rounded p-1 text-faint hover:text-ink">
            <X aria-hidden="true" size={16} />
          </button>
        </header>
        {offered.length ? (
          <ul className="flex min-h-0 flex-col gap-1 overflow-auto">
            {offered.map((asset) => {
              const name = nameOf(asset);
              return (
                <li key={asset.asset_id}>
                  <button
                    type="button"
                    aria-label={t("studio.replace.use", { name })}
                    onClick={() => onReplace(asset.asset_id)}
                    className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm text-ink hover:bg-well focus-visible:outline-2 focus-visible:outline-copper"
                  >
                    <Film aria-hidden="true" size={15} className="shrink-0 text-muted-ink" />
                    <span className="truncate">{name}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <p className="text-sm text-muted-ink">{t("studio.replace.none")}</p>
        )}
        <footer className="flex justify-end">
          <button type="button" onClick={onClose} className="rounded-md border border-hairline px-3 py-1.5 text-[13px] text-ink">
            {t("studio.media.cancel")}
          </button>
        </footer>
      </div>
    </div>
  );
}
