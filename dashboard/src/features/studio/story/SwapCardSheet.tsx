import { useState } from "react";
import { Heart } from "lucide-react";

import type { StudioMaterial } from "@/api/control-plane";
import { useLocale } from "@/lib/locale";

type Props = {
  index: number;
  cards: StudioMaterial[];
  inUse: string | null;
  onCancel: () => void;
  onSwap: (card: StudioMaterial) => void;
};

/** DESIGN §13.5: a bottom sheet of the run's comment cards; the one in use is marked. */
export function SwapCardSheet({ index, cards, inUse, onCancel, onSwap }: Props) {
  const { t } = useLocale();
  const [chosen, setChosen] = useState(inUse);
  const title = t("studio.quick.swapTitle", { index });
  const card = cards.find((entry) => entry.item_id === chosen);

  return (
    <div role="dialog" aria-modal="true" aria-label={title} className="fixed inset-x-0 bottom-0 z-50 flex max-h-[80vh] flex-col gap-3 overflow-auto rounded-t-2xl border-t border-hairline bg-raised p-4 shadow-2xl">
      <span aria-hidden="true" className="mx-auto h-1 w-10 rounded-full bg-hairline" />
      <h2 className="text-[17px] font-semibold text-ink">{title}</h2>
      <p className="text-sm text-muted-ink">{t("studio.quick.swapIntro", { count: cards.length })}</p>
      <div className="flex flex-col gap-2">
        {cards.map((entry) => (
          <label
            key={entry.item_id}
            aria-current={entry.item_id === inUse ? "true" : undefined}
            className={`flex items-start gap-3 rounded-[10px] border bg-bg p-3 text-sm text-ink ${
              chosen === entry.item_id ? "border-copper" : "border-hairline"
            }`}
          >
            <input
              type="radio"
              name="swap-card"
              checked={chosen === entry.item_id}
              onChange={() => setChosen(entry.item_id)}
              className="mt-1 accent-copper"
            />
            <span className="flex min-w-0 flex-col gap-1">
              <span className="font-medium">{entry.label}</span>
              {entry.item_id === inUse ? <span className="text-xs text-muted-ink">{t("studio.quick.inUse")}</span> : null}
              {entry.likes != null ? (
                <span className="flex items-center gap-1 text-xs text-muted-ink">
                  <Heart aria-hidden="true" size={12} /> {t("studio.quick.likes", { count: entry.likes })}
                </span>
              ) : null}
            </span>
          </label>
        ))}
      </div>
      <div className="flex gap-3 pt-1">
        <button type="button" onClick={onCancel} className="h-11 flex-1 rounded-md text-sm text-ink hover:bg-surface focus-visible:outline-2 focus-visible:outline-copper">
          {t("studio.quick.cancel")}
        </button>
        <button
          type="button"
          disabled={!card || chosen === inUse}
          onClick={() => card && onSwap(card)}
          className="h-11 flex-[2] rounded-md bg-copper text-sm font-medium text-bg disabled:opacity-40 focus-visible:outline-2 focus-visible:outline-ink"
        >
          {t("studio.quick.swap")}
        </button>
      </div>
    </div>
  );
}
