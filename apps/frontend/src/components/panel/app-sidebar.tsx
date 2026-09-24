"use client";

import { useId, useState } from "react";
import {
  ArrowRightIcon,
  ChevronDownIcon,
  TriangleAlertIcon,
  XIcon,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { Link, usePathname } from "#i18n/navigation";
import type { BillingAttention } from "#lib/billing-attention";
import {
  ariaCurrent,
  currentPage,
  panelNavigation,
  type PanelAccess,
  type PanelNavEntry,
} from "#lib/panel-navigation";
import type { OrganizationSummary } from "@saas-core/api-client";
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarHeader,
  useSidebar,
} from "@saas-core/ui/components/sidebar";
import { Button } from "@saas-core/ui/components/button";
import { cn } from "@saas-core/ui/lib/utils";
import { OrganizationSwitcher } from "./organization-switcher";

export function AppSidebar({
  access,
  attention,
  organizations,
  roleLabel,
}: {
  access: PanelAccess;
  /** Shown to the owner only when the subscription needs attention. */
  attention: BillingAttention | null;
  organizations: OrganizationSummary[];
  roleLabel: string;
}) {
  const t = useTranslations("DashboardNav");
  const { closeMobile } = useSidebar();
  const { work, company } = panelNavigation(access);

  return (
    <Sidebar
      aria-label={t("navigation")}
      id="customer-dashboard-sidebar"
      mobileCloseLabel={t("closeNavigation")}
    >
      <SidebarHeader className="flex items-center gap-2">
        <OrganizationSwitcher
          organizations={organizations}
          roleLabel={roleLabel}
        />
        <Button
          aria-label={t("closeNavigation")}
          className="lg:hidden"
          onClick={closeMobile}
          size="icon"
          type="button"
          variant="ghost"
        >
          <XIcon aria-hidden="true" />
        </Button>
      </SidebarHeader>
      <SidebarContent>
        <NavGroup items={work} label={t("work")} />
        <NavGroup items={company} label={t("company")} />
      </SidebarContent>
      {attention ? (
        <SidebarFooter>
          <AttentionCard attention={attention} onNavigate={closeMobile} />
        </SidebarFooter>
      ) : null}
    </Sidebar>
  );
}

function NavGroup({ items, label }: { items: PanelNavEntry[]; label: string }) {
  if (items.length === 0) return null;
  return (
    <nav aria-label={label} className="mt-5 first:mt-1">
      <p className="mb-2 px-3 text-[0.6875rem] font-semibold tracking-[0.13em] text-muted-foreground uppercase group-data-[collapsed=true]/sidebar-wrapper:sr-only">
        {label}
      </p>
      <ul className="space-y-0.5">
        {items.map((item) => (
          <NavEntry item={item} key={item.href} />
        ))}
      </ul>
    </nav>
  );
}

/**
 * A menu entry; one with pages of its own unfolds them under it (ADR-057).
 * The section one is in stays open; the others open on request. A collapsed
 * menu shows icons only, and the entry leads to the section's first page.
 */
function NavEntry({ item }: { item: PanelNavEntry }) {
  const t = useTranslations("DashboardNav");
  const pathname = usePathname();
  const { closeMobile } = useSidebar();
  const listId = useId();
  const [toggled, setToggled] = useState<boolean>();
  const current = ariaCurrent(pathname, item);
  const Icon = item.icon;
  const text = t(item.labelKey);
  const pages = item.pages;
  const open = toggled ?? current !== undefined;
  const page = pages ? currentPage(pathname, pages) : undefined;
  return (
    <li>
      <div className="flex items-center gap-0.5">
        <Link
          aria-current={current}
          className={cn(
            "flex min-h-11 min-w-0 flex-1 items-center gap-3 rounded-lg px-3 text-sm transition-colors hover:bg-foreground/6 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring",
            current &&
              "bg-primary font-medium text-primary-foreground hover:bg-primary",
          )}
          href={item.href}
          onClick={closeMobile}
          title={text}
        >
          <Icon aria-hidden="true" className="size-4.5 shrink-0" />
          <span className="truncate group-data-[collapsed=true]/sidebar-wrapper:sr-only">
            {text}
          </span>
        </Link>
        {pages ? (
          <button
            aria-controls={listId}
            aria-expanded={open}
            aria-label={t("sectionPages", { section: text })}
            className="flex size-11 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-foreground/6 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring group-data-[collapsed=true]/sidebar-wrapper:hidden"
            onClick={() => setToggled(!open)}
            type="button"
          >
            <ChevronDownIcon
              aria-hidden="true"
              className={cn(
                "size-4 transition-transform",
                open && "rotate-180",
              )}
            />
          </button>
        ) : null}
      </div>
      {pages && open ? (
        <ul
          className="mt-0.5 mb-1 ml-5 space-y-0.5 border-l pl-2 group-data-[collapsed=true]/sidebar-wrapper:hidden"
          id={listId}
        >
          {pages.map((sub) => (
            <li key={sub.href}>
              <Link
                aria-current={sub.href === page ? "page" : undefined}
                className="flex min-h-10 items-center rounded-md px-3 text-sm text-muted-foreground transition-colors hover:bg-foreground/6 hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring aria-[current=page]:bg-foreground/8 aria-[current=page]:font-medium aria-[current=page]:text-foreground pointer-coarse:min-h-11"
                href={sub.href}
                onClick={closeMobile}
              >
                <span className="truncate">{t(sub.labelKey)}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </li>
  );
}

function AttentionCard({
  attention,
  onNavigate,
}: {
  attention: BillingAttention;
  onNavigate: () => void;
}) {
  const t = useTranslations("DashboardNav");
  const headline =
    attention.kind === "trial"
      ? attention.days === null
        ? t("trial")
        : t("trialDays", { days: attention.days })
      : t(attention.kind);
  return (
    <Link
      className="flex items-start gap-2.5 rounded-lg bg-warning p-3 text-warning-foreground focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      href="/panel/settings/billing"
      onClick={onNavigate}
      title={headline}
    >
      <TriangleAlertIcon
        aria-hidden="true"
        className="mt-0.5 size-4 shrink-0"
      />
      <span className="min-w-0 group-data-[collapsed=true]/sidebar-wrapper:sr-only">
        <span className="block text-[0.8125rem] font-semibold">{headline}</span>
        <span className="flex items-center gap-1 text-xs font-semibold underline-offset-2 hover:underline">
          {t("openBilling")}
          <ArrowRightIcon aria-hidden="true" className="size-3.5" />
        </span>
      </span>
    </Link>
  );
}
