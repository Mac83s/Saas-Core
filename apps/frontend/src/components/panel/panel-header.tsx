"use client";

import { useState, useSyncExternalStore } from "react";
import {
  IdCardIcon,
  LogOutIcon,
  MoonIcon,
  SettingsIcon,
  SunIcon,
  WifiOffIcon,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Link, usePathname, useRouter } from "#i18n/navigation";
import {
  currentColorScheme,
  setColorScheme,
  subscribeColorScheme,
  type ColorScheme,
} from "#lib/color-scheme";
import { allows, type PanelAccess } from "#lib/panel-navigation";
import { logoutAccount, type UserSummary } from "@saas-core/api-client";
import { buttonVariants } from "@saas-core/ui/components/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuLinkItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@saas-core/ui/components/dropdown-menu";
import { SidebarTrigger } from "@saas-core/ui/components/sidebar";
import { cn } from "@saas-core/ui/lib/utils";
import { product } from "../../product";
import { NotificationBell } from "../../modules/shared/notifications";
import { WidthToggle } from "./panel-width";

/** Header of shell 1a: status on the left, the day's action and the account on the right. */
export function PanelHeader({
  access,
  user,
}: {
  access: PanelAccess;
  user: Pick<UserSummary, "email" | "first_name" | "last_name">;
}) {
  const t = useTranslations("DashboardNav");
  const action = product.primaryAction;
  const ActionIcon = action?.icon;

  return (
    <header className="sticky top-0 z-30 border-b bg-background/90 backdrop-blur-xl">
      <div className="flex h-17 items-center gap-2 px-3 sm:gap-3 sm:px-6">
        <SidebarTrigger
          aria-controls="customer-dashboard-sidebar"
          aria-label={t("toggleNavigation")}
          className="size-11"
        />
        {/* The page's frame sits with the menu's: both change the layout. */}
        <WidthToggle />
        <ConnectionStatus />
        <div className="ml-auto flex items-center gap-1 sm:gap-2">
          {/* A phone keeps the bar for the day's work: the theme and the
              language are in the account menu there (UX-006). */}
          <div className="flex items-center gap-2 max-sm:hidden">
            <ThemeToggle />
            <LocaleToggle />
          </div>
          <NotificationBell />
          {action && ActionIcon && allows(access, action) ? (
            <Link
              className={cn(buttonVariants(), "max-sm:size-11 max-sm:px-0")}
              href={action.href}
            >
              <ActionIcon aria-hidden="true" />
              <span className="max-sm:sr-only">{t(action.labelKey)}</span>
            </Link>
          ) : null}
          <AccountMenu
            // One's own card needs a company to be a person of.
            myCard={access.permissions !== null}
            user={user}
          />
        </div>
      </div>
    </header>
  );
}

const PHONE = "(max-width: 639px)";

function subscribePhone(onChange: () => void) {
  const query = window.matchMedia?.(PHONE);
  query?.addEventListener("change", onChange);
  return () => query?.removeEventListener("change", onChange);
}

const isPhone = () => window.matchMedia?.(PHONE).matches ?? false;

function subscribeOnline(onChange: () => void) {
  window.addEventListener("online", onChange);
  window.addEventListener("offline", onChange);
  return () => {
    window.removeEventListener("online", onChange);
    window.removeEventListener("offline", onChange);
  };
}

/**
 * Says something only when it matters: offline (UX-006). The live region
 * stays in place, so the change is read out the moment it happens.
 */
function ConnectionStatus() {
  const t = useTranslations("DashboardNav");
  const online = useSyncExternalStore(
    subscribeOnline,
    () => navigator.onLine,
    () => true,
  );
  return (
    <span
      className={cn(
        "flex items-center gap-2 rounded-full text-xs font-medium",
        !online && "bg-warning px-3 py-1.5 text-warning-foreground",
      )}
      role="status"
    >
      {online ? null : (
        <>
          {/* A shape, not only a colour, tells offline apart on a phone. */}
          <WifiOffIcon aria-hidden="true" className="size-3.5" />
          <span className="max-sm:sr-only">{t("offline")}</span>
        </>
      )}
    </span>
  );
}

const segment =
  "flex min-h-11 min-w-11 items-center justify-center px-2.5 transition-colors not-first:border-l not-first:border-foreground/15 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring";
const segmentOn =
  "bg-primary text-primary-foreground focus-visible:outline-primary-foreground";

function ThemeToggle() {
  const t = useTranslations("DashboardNav");
  const scheme = useSyncExternalStore(
    subscribeColorScheme,
    currentColorScheme,
    (): ColorScheme => "light",
  );
  const options = [
    { value: "light", icon: SunIcon, label: t("themeLight") },
    { value: "dark", icon: MoonIcon, label: t("themeDark") },
  ] as const;
  return (
    <>
      <div
        aria-label={t("theme")}
        className="flex overflow-hidden rounded-lg border border-foreground/15 max-sm:hidden"
        role="group"
      >
        {options.map(({ value, icon: Icon, label }) => (
          <button
            aria-label={label}
            aria-pressed={scheme === value}
            className={cn(
              segment,
              scheme === value ? segmentOn : "hover:bg-foreground/6",
            )}
            key={value}
            onClick={() => setColorScheme(value)}
            title={label}
            type="button"
          >
            <Icon aria-hidden="true" className="size-4" />
          </button>
        ))}
      </div>
    </>
  );
}

function LocaleToggle() {
  const t = useTranslations("Panel");
  const locale = useLocale();
  const pathname = usePathname();
  return (
    <nav
      aria-label={t("language")}
      className="flex overflow-hidden rounded-lg border border-foreground/15 text-xs font-semibold"
    >
      {(["pl", "en"] as const).map((code) => (
        <Link
          aria-current={code === locale ? "true" : undefined}
          className={cn(
            segment,
            "uppercase",
            code === locale ? segmentOn : "hover:bg-foreground/6",
          )}
          href={pathname}
          hrefLang={code}
          key={code}
          lang={code}
          locale={code}
        >
          {code}
        </Link>
      ))}
    </nav>
  );
}

function AccountMenu({
  user,
  myCard,
}: {
  user: Pick<UserSummary, "email" | "first_name" | "last_name">;
  myCard: boolean;
}) {
  const t = useTranslations("DashboardNav");
  const panel = useTranslations("Panel");
  const router = useRouter();
  const locale = useLocale();
  const pathname = usePathname();
  const phone = useSyncExternalStore(subscribePhone, isPhone, () => false);
  const scheme = useSyncExternalStore(
    subscribeColorScheme,
    currentColorScheme,
    (): ColorScheme => "light",
  );
  const [pending, setPending] = useState(false);
  const name = [user.first_name, user.last_name].join(" ").trim();
  const initials = (
    name
      ? name
          .split(/\s+/)
          .map((part) => part.charAt(0))
          .join("")
          .slice(0, 2)
      : user.email.slice(0, 2)
  ).toUpperCase();

  async function logout() {
    setPending(true);
    try {
      await logoutAccount();
    } finally {
      router.replace("/login");
      router.refresh();
    }
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label={`${initials}, ${t("account")}`}
        className="flex size-11 shrink-0 items-center justify-center rounded-lg border border-foreground/15 bg-muted text-[0.8125rem] font-semibold transition-colors hover:bg-foreground/8 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {initials}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end">
        <DropdownMenuGroup>
          <DropdownMenuLabel>
            <span className="block">{t("signedIn")}</span>
            {name ? (
              <span className="block truncate text-sm font-medium text-foreground">
                {name}
              </span>
            ) : null}
            <span className="block truncate">{user.email}</span>
          </DropdownMenuLabel>
        </DropdownMenuGroup>
        <DropdownMenuSeparator />
        {myCard ? (
          <DropdownMenuLinkItem render={<Link href="/panel/team/me" />}>
            <IdCardIcon aria-hidden="true" />
            {t("myCard")}
          </DropdownMenuLinkItem>
        ) : null}
        <DropdownMenuLinkItem render={<Link href="/panel/settings/account" />}>
          <SettingsIcon aria-hidden="true" />
          {t("accountSettings")}
        </DropdownMenuLinkItem>
        {phone ? (
          // On a phone the bar has no room for them (UX-006): the theme
          // and the language, each showing which one is on.
          <>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
              <DropdownMenuLabel>{t("theme")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                onValueChange={(value) => setColorScheme(value as ColorScheme)}
                value={scheme}
              >
                <DropdownMenuRadioItem value="light">
                  <SunIcon aria-hidden="true" />
                  {t("themeLight")}
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="dark">
                  <MoonIcon aria-hidden="true" />
                  {t("themeDark")}
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
            <DropdownMenuGroup>
              <DropdownMenuLabel>{panel("language")}</DropdownMenuLabel>
              <DropdownMenuRadioGroup
                onValueChange={(value) =>
                  router.replace(pathname, { locale: String(value) })
                }
                value={locale}
              >
                <DropdownMenuRadioItem lang="pl" value="pl">
                  Polski
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem lang="en" value="en">
                  English
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
          </>
        ) : null}
        <DropdownMenuItem disabled={pending} onClick={() => void logout()}>
          <LogOutIcon aria-hidden="true" />
          {pending ? panel("loggingOut") : panel("logout")}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
