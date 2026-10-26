// Settings (DESIGN §8.10, restyle R4): language, desktop notifications and developer tokens.
import { Check } from "lucide-react";
import { useState } from "react";

import type { Me } from "@/api/auth";
import { Button } from "@/components/ui/button";
import { LOCALES } from "@/lib/i18n";
import { useLocale } from "@/lib/locale";
import { askPermission } from "@/lib/notifications";
import { cn } from "@/lib/utils";

import { TokensPage } from "./TokensPage";

type Permission = NotificationPermission | "unsupported";

function currentPermission(): Permission {
  return typeof window !== "undefined" && "Notification" in window ? Notification.permission : "unsupported";
}

export function SettingsPage({ me, tokens }: { me: Me; tokens?: Parameters<typeof TokensPage>[0]["client"] }) {
  const { locale, setLocale, t } = useLocale();
  const [permission, setPermission] = useState<Permission>(currentPermission);

  return (
    <div className="flex max-w-[1140px] flex-col gap-10">
      {me.email && <p className="-mt-4 text-sm text-muted-ink">{me.email}</p>}
      <section className="flex flex-col gap-4">
        <h2 className="text-base font-semibold text-ink">{t("settings.preferences")}</h2>
        <div className="flex flex-col divide-y divide-hairline rounded-[10px] bg-surface px-5">
          <div className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div>
              <p id="settings-language" className="text-ink">{t("settings.language")}</p>
              <p className="text-sm text-muted-ink">{t("settings.languageHint")}</p>
            </div>
            <div role="group" aria-labelledby="settings-language" className="grid grid-cols-2 rounded-md bg-well p-1">
              {LOCALES.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={locale === option}
                  onClick={() => void setLocale(option)}
                  className={cn("rounded px-4 py-2 text-sm text-ink", locale === option && "bg-raised")}
                >
                  {t(`language.${option}`)}
                </button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center justify-between gap-4 py-5">
            <div>
              <p className="text-ink">{t("settings.notifications")}</p>
              <p className="text-sm text-muted-ink">{t("settings.notificationsHint")}</p>
            </div>
            {permission === "granted" && (
              <span className="inline-flex items-center gap-1.5 text-sm text-ink">
                <Check aria-hidden="true" className="size-4 text-status-done" />
                {t("settings.allowed")}
              </span>
            )}
            {permission === "default" && (
              <Button variant="secondary" onClick={() => void askPermission().then(() => setPermission(currentPermission()))}>
                {t("settings.allow")}
              </Button>
            )}
            {permission === "denied" && <p className="max-w-sm text-sm text-status-waiting">{t("settings.blocked")}</p>}
            {permission === "unsupported" && <p className="text-sm text-muted-ink">{t("settings.unsupported")}</p>}
          </div>
        </div>
      </section>
      <TokensPage client={tokens} />
    </div>
  );
}
