"use client";

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";

import { PageCount } from "#components/panel/app-sidebar";
import { Link, usePathname } from "#i18n/navigation";
import {
  currentPage,
  sectionTabs,
  type PanelAccess,
} from "#lib/panel-navigation";
import { cn } from "@saas-core/ui/lib/utils";

/** The edge a fade hides more tabs behind (UX-001). */
const FADE = {
  none: "",
  start:
    "[mask-image:linear-gradient(to_left,#000_calc(100%-1.5rem),transparent)]",
  end: "[mask-image:linear-gradient(to_right,#000_calc(100%-1.5rem),transparent)]",
  both: "[mask-image:linear-gradient(to_right,transparent,#000_1.5rem,#000_calc(100%-1.5rem),transparent)]",
} as const;

/**
 * The pages of the section the page belongs to, e.g. Magazyn › Dokumenty, as
 * tabs above the content — on a phone and a tablet only. A wide screen has
 * them unfolded in the menu (ADR-057). The current tab scrolls into view, a
 * faded edge says there is more behind it, and a long name has a short one
 * for the eye (UX-001).
 */
export function SectionTabs({ access }: { access: PanelAccess }) {
  const t = useTranslations("DashboardNav");
  const pathname = usePathname();
  const list = useRef<HTMLUListElement>(null);
  const [fade, setFade] = useState<keyof typeof FADE>("none");
  const tabs = sectionTabs(pathname, access);
  const current = tabs ? currentPage(pathname, tabs) : undefined;

  useEffect(() => {
    const element = list.current;
    if (!element) return;
    element
      .querySelector('[aria-current="page"]')
      ?.scrollIntoView?.({ inline: "center", block: "nearest" });
    const edges = () => {
      const start = element.scrollLeft > 4;
      const end =
        element.scrollLeft + element.clientWidth < element.scrollWidth - 4;
      setFade(start && end ? "both" : start ? "start" : end ? "end" : "none");
    };
    edges();
    element.addEventListener("scroll", edges, { passive: true });
    window.addEventListener("resize", edges);
    return () => {
      element.removeEventListener("scroll", edges);
      window.removeEventListener("resize", edges);
    };
  }, [current]);

  if (!tabs) return null;
  return (
    <nav aria-label={t("sections")} className="-mt-2 mb-6 lg:hidden">
      <ul
        className={cn("flex gap-1 overflow-x-auto border-b", FADE[fade])}
        ref={list}
      >
        {tabs.map((tab) => {
          const active = tab.href === current;
          const short = `${tab.labelKey}Short`;
          return (
            <li key={tab.href}>
              <Link
                aria-current={active ? "page" : undefined}
                // `relative`: a tab's full name for screen readers is taken out
                // of the flow; without a positioned tab around it, the name of
                // a tab scrolled out of sight widens the whole page on a phone.
                className={cn(
                  "relative -mb-px flex min-h-11 items-center gap-2 border-b-2 border-transparent px-3 text-sm font-medium whitespace-nowrap text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-ring",
                  active && "border-primary text-foreground",
                )}
                href={tab.href}
              >
                {tab.label ? (
                  tab.label
                ) : t.has(short) ? (
                  <>
                    <span aria-hidden="true">{t(short)}</span>
                    <span className="sr-only">{t(tab.labelKey)}</span>
                  </>
                ) : (
                  t(tab.labelKey)
                )}
                <PageCount count={tab.count} />
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
