"use client";

import { useSyncExternalStore, type ReactNode } from "react";
import { useTranslations } from "next-intl";

import { routing } from "#i18n/routing";
import { menuEntryFor } from "#lib/panel-navigation";

// The address as the browser has it: a page's eyebrow is mounted with the
// page, so a navigation brings a new one. On the server there is none yet,
// and the page's own eyebrow stands until the browser takes over.
const subscribe = (onChange: () => void) => {
  window.addEventListener("popstate", onChange);
  return () => window.removeEventListener("popstate", onChange);
};
const browserPath = () => window.location.pathname;
const noPath = () => null;

/** The path without a language prefix ("/en/panel/x" → "/panel/x"). */
function withoutLocale(pathname: string): string {
  const [, first, ...rest] = pathname.split("/");
  return (routing.locales as readonly string[]).includes(first)
    ? `/${rest.join("/")}`
    : pathname;
}

/**
 * The line over a page's title: the name of the menu entry the page stands
 * under, from the menu itself (R1, UX-003) — „Strona internetowa” over
 * „Widoczność w Google”, „Kalendarz” over „Do przydzielenia”. On the entry's
 * own page it is the menu's group instead („Praca”, „Firma”), never the title
 * twice. A page outside the menu keeps the eyebrow it gives.
 */
export function PanelEyebrow({
  fallback,
  title,
}: {
  fallback?: ReactNode;
  title: ReactNode;
}) {
  const t = useTranslations("DashboardNav");
  const pathname = useSyncExternalStore<string | null>(
    subscribe,
    browserPath,
    noPath,
  );
  const entry = pathname ? menuEntryFor(withoutLocale(pathname)) : undefined;
  const text = entry
    ? typeof title === "string" && title === t(entry.labelKey)
      ? t(entry.group)
      : t(entry.labelKey)
    : fallback;
  return text ? (
    <p className="text-sm font-medium text-primary">{text}</p>
  ) : null;
}
