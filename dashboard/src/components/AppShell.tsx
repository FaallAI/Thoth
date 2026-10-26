// The app shell: top bar, sidebar, avatar menu and the narrow-screen sheet (DESIGN §4, §5.4).
import { Dialog } from "@base-ui/react/dialog";
import { Popover } from "@base-ui/react/popover";
import {
  Clapperboard,
  CreditCard,
  Feather,
  Gauge,
  Inbox,
  ListVideo,
  LogOut,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Settings,
  Users,
} from "lucide-react";
import { useState, type ComponentType, type ReactNode } from "react";
import { NavLink } from "react-router";

import type { Me } from "@/api/auth";
import { useActivity } from "@/features/activity/activity";
import { LOCALES, type MessageKey } from "@/lib/i18n";
import { initials } from "@/lib/initials";
import { useLocale } from "@/lib/locale";
import { cn } from "@/lib/utils";

export type NavItem = {
  path: string;
  label: MessageKey;
  icon: ComponentType<{ className?: string }>;
  admin?: boolean;
  /** A divider goes above this item. */
  section?: boolean;
};

/** Sidebar order (§4). */
export const NAV: NavItem[] = [
  { path: "/workflows", label: "nav.runs", icon: ListVideo },
  { path: "/inbox", label: "nav.inbox", icon: Inbox },
  { path: "/studio", label: "nav.studio", icon: Clapperboard },
  { path: "/usage", label: "nav.usage", icon: Gauge, section: true },
  { path: "/billing", label: "nav.billing", icon: CreditCard },
  { path: "/accounts", label: "nav.accounts", icon: Users, admin: true },
  { path: "/settings", label: "nav.settings", icon: Settings },
];

const COLLAPSED_KEY = "thoth.sidebarCollapsed";

function storedCollapsed(): boolean {
  try {
    return localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

/** In the sidebar the labels give way to icons when collapsed or at 1024 px and below; the sheet keeps them. */
function NavLinks({ items, collapsed = false, sheet = false, onPick }: { items: NavItem[]; collapsed?: boolean; sheet?: boolean; onPick?: () => void }) {
  const { t } = useLocale();
  const activity = useActivity();
  const iconOnly = sheet ? "" : collapsed ? "sr-only" : "max-[1024px]:sr-only";
  // Live counts (§4): running runs beside Runs, decisions waiting beside Inbox.
  const running = activity ? activity.active.filter((run) => run.status !== "awaiting_approval").length : 0;
  const counts: Record<string, string | null> = {
    "/workflows": running > 0 ? t("nav.countRunning", { count: running }) : null,
    "/inbox": activity && activity.waiting > 0 ? t("nav.countWaiting", { count: activity.waiting }) : null,
  };
  const numbers: Record<string, number> = { "/workflows": running, "/inbox": activity?.waiting ?? 0 };
  return (
    <ul className="flex flex-col gap-1">
      {items.map((item) => (
        <li key={item.path}>
          {item.section && <hr className="mx-3 my-3 border-hairline" />}
          <NavLink
            to={item.path}
            onClick={onPick}
            title={sheet ? undefined : t(item.label)}
            className={cn(
              "relative flex h-11 items-center gap-3.5 rounded-md px-3 text-[15px] text-ink hover:bg-raised",
              "aria-[current=page]:bg-raised aria-[current=page]:before:absolute aria-[current=page]:before:inset-y-2.5 aria-[current=page]:before:-left-2 aria-[current=page]:before:w-0.5 aria-[current=page]:before:rounded-full aria-[current=page]:before:bg-copper",
              !sheet && (collapsed ? "justify-center px-0" : "max-[1024px]:justify-center max-[1024px]:px-0"),
            )}
          >
            <item.icon className="size-5 shrink-0 stroke-[1.75]" />
            <span className={cn("flex-1 truncate", iconOnly)}>{t(item.label)}</span>
            {counts[item.path] && (
              <>
                <span aria-hidden="true" className={cn("rounded-full bg-raised px-2 text-xs text-ink", iconOnly && "hidden", !collapsed && !sheet && "min-[1025px]:inline")}>
                  {numbers[item.path]}
                </span>
                <span className="sr-only">{`, ${counts[item.path]}`}</span>
              </>
            )}
            {item.admin && (
              <span className={cn("rounded-full border border-hairline px-2 text-xs text-muted-ink", iconOnly && "hidden", !collapsed && !sheet && "min-[1025px]:inline")}>
                {t("nav.admin")}
              </span>
            )}
          </NavLink>
        </li>
      ))}
    </ul>
  );
}

function AvatarMenu({ me, onSignOut }: { me: Me; onSignOut: (forgetBrowser: boolean) => void }) {
  const { locale, setLocale, t } = useLocale();
  const [open, setOpen] = useState(false);
  const signOut = (forget: boolean) => () => {
    setOpen(false);
    onSignOut(forget);
  };
  return (
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger
        aria-label={t("topbar.account")}
        className="grid size-10 place-items-center rounded-full bg-studio-ai text-sm font-semibold text-bg"
      >
        {initials(me)}
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={8}>
          <Popover.Popup className="w-[min(268px,calc(100vw-32px))] rounded-[10px] border border-hairline bg-raised p-2 text-sm shadow-xl">
            <div className="px-3 py-2">
              <p className="font-semibold text-ink">{me.display_name ?? me.email ?? me.workspace.name}</p>
              {me.email && <p className="text-muted-ink">{me.email}</p>}
              <p className="text-xs text-faint">{me.workspace.name}</p>
            </div>
            <hr className="my-2 border-hairline" />
            <p id="avatar-language" className="px-3 pb-2 text-muted-ink">{t("avatar.language")}</p>
            <div role="group" aria-labelledby="avatar-language" className="mx-3 mb-2 grid grid-cols-2 rounded-md bg-well p-0.5">
              {LOCALES.map((option) => (
                <button
                  key={option}
                  type="button"
                  aria-pressed={locale === option}
                  onClick={() => void setLocale(option)}
                  className={cn("rounded px-2 py-1.5 text-ink", locale === option && "bg-raised")}
                >
                  {t(`language.${option}`)}
                </button>
              ))}
            </div>
            <hr className="my-2 border-hairline" />
            <NavLink
              to="/settings"
              onClick={() => setOpen(false)}
              className="flex items-center gap-3 rounded-md px-3 py-2 text-ink hover:bg-surface"
            >
              <Settings className="size-4" />
              {t("avatar.settings")}
            </NavLink>
            <button type="button" onClick={signOut(false)} className="flex w-full items-center gap-3 rounded-md px-3 py-2 text-ink hover:bg-surface">
              <LogOut className="size-4" />
              {t("avatar.signOut")}
            </button>
            <button type="button" onClick={signOut(true)} className="w-full rounded-md px-3 py-2 text-left text-muted-ink hover:bg-surface">
              {t("avatar.signOutForget")}
            </button>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

/** Below 640 px the sidebar becomes a bottom sheet with the project and the person (§5.4). */
function MenuSheet({ items, switcher, me, onSignOut }: { items: NavItem[]; switcher: ReactNode; me: Me; onSignOut: () => void }) {
  const { t } = useLocale();
  const [open, setOpen] = useState(false);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger aria-label={t("nav.menu")} className="grid size-10 place-items-center rounded-md text-ink sm:hidden">
        <Menu className="size-6" />
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="fixed inset-0 bg-black/60" />
        <Dialog.Popup className="fixed inset-x-0 bottom-0 max-h-[85dvh] overflow-y-auto rounded-t-[16px] bg-raised px-4 pt-3 pb-6">
          <Dialog.Title className="sr-only">{t("nav.menu")}</Dialog.Title>
          <span aria-hidden="true" className="mx-auto mb-4 block h-1 w-9 rounded-full bg-hairline" />
          <div className="mb-4 rounded-md bg-surface px-3 py-2">
            <p className="text-xs text-muted-ink">{t("project.label")}</p>
            {switcher}
          </div>
          <nav aria-label={t("nav.main")}>
            <NavLinks items={items} sheet onPick={() => setOpen(false)} />
          </nav>
          <hr className="my-4 border-hairline" />
          <div className="flex items-center gap-3 px-3">
            <span className="grid size-10 place-items-center rounded-full bg-studio-ai text-sm font-semibold text-bg">{initials(me)}</span>
            <div className="min-w-0 flex-1">
              <p className="truncate text-ink">{me.display_name ?? me.workspace.name}</p>
              {me.email && <p className="truncate text-sm text-muted-ink">{me.email}</p>}
            </div>
            <button type="button" onClick={onSignOut} className="px-2 py-1 text-ink">
              {t("avatar.signOut")}
            </button>
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

/**
 * Top bar (64 px) and a sidebar of 232 px that collapses to 64 px, by choice or at
 * 1024 px and below. `chrome={false}` hides both, for the full-screen Studio editor.
 */
export function AppShell({
  me,
  switcher,
  palette,
  activity,
  onSignOut,
  chrome = true,
  children,
}: {
  me: Me;
  switcher: ReactNode;
  palette: ReactNode;
  /** The run tray and the inbox bell, beside the avatar (§4). */
  activity?: ReactNode;
  onSignOut: (forgetBrowser: boolean) => void;
  chrome?: boolean;
  children: ReactNode;
}) {
  const { t } = useLocale();
  const [collapsed, setCollapsed] = useState(storedCollapsed);
  const items = NAV.filter((item) => !item.admin || me.platform_admin);
  const toggle = () => {
    setCollapsed((was) => {
      try {
        localStorage.setItem(COLLAPSED_KEY, was ? "0" : "1");
      } catch {
        // A per-viewer convenience only.
      }
      return !was;
    });
  };
  if (!chrome) return <div className="dashboard-shell dashboard-shell--studio min-h-dvh bg-bg">{children}</div>;
  return (
    <div className="dashboard-shell min-h-dvh bg-bg text-ink">
      <a href="#workspace" className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded focus:bg-raised focus:px-3 focus:py-2">
        {t("nav.skip")}
      </a>
      <header className="flex h-16 items-center gap-4 border-b border-hairline px-4 sm:px-6">
        <MenuSheet items={items} switcher={switcher} me={me} onSignOut={() => onSignOut(false)} />
        <div className="flex items-center gap-2 text-lg font-semibold">
          <Feather aria-hidden="true" className="size-5 text-copper" />
          Thoth
        </div>
        <span aria-hidden="true" className="hidden h-6 w-px bg-hairline sm:block" />
        <div className="hidden sm:block">{switcher}</div>
        <div className="hidden flex-1 justify-center md:flex">{palette}</div>
        <div className="ml-auto flex items-center gap-3 md:ml-0">
          {activity}
          <AvatarMenu me={me} onSignOut={onSignOut} />
        </div>
      </header>
      <div className="flex min-h-[calc(100dvh-4rem)]">
        <nav
          aria-label={t("nav.main")}
          className={cn(
            "hidden shrink-0 flex-col justify-between border-r border-hairline px-4 py-4 sm:flex",
            collapsed ? "w-16 px-2" : "w-16 px-2 min-[1025px]:w-[232px] min-[1025px]:px-4",
          )}
        >
          <NavLinks items={items} collapsed={collapsed} />
          <button
            type="button"
            onClick={toggle}
            aria-label={t(collapsed ? "nav.expand" : "nav.collapse")}
            className="hidden h-10 items-center justify-center rounded-md text-muted-ink hover:bg-raised min-[1025px]:flex"
          >
            {collapsed ? <PanelLeftOpen className="size-5" /> : <PanelLeftClose className="size-5" />}
          </button>
        </nav>
        {children}
      </div>
    </div>
  );
}
