import {
  CalendarDaysIcon,
  ContactIcon,
  CreditCardIcon,
  Globe2Icon,
  HomeIcon,
  MessageSquareTextIcon,
  PackageIcon,
  PawPrintIcon,
  SettingsIcon,
  UsersIcon,
  WarehouseIcon,
} from "lucide-react";

import type { OrganizationSummary } from "@saas-core/api-client";

import { product } from "../product";
import { modulesFor, typeRole } from "./organization-types";
import type { ProductNavigationItem } from "./product-extension";

/**
 * The panel menu from the HoofCare design (shell 1a): two groups, "Praca" for
 * daily work and "Firma" for running the business. Tools that used to be
 * top-level (SEO, credits, integrations) are pages of the entry they belong
 * to, so daily work does not drown among them. An entry's pages unfold under
 * it in the menu (ADR-057); on a phone they are also tabs above the content.
 */
export type PanelNavItem = ProductNavigationItem & {
  group: "work" | "company";
  /** Owner only, for what permissions cannot express. */
  ownerOnly?: boolean;
  /** Hidden from the type's limited roles (a trimmer, a viewer). */
  notForLimited?: boolean;
  /**
   * The entry leads to the first tab of this section the person may open,
   * and lights up on all of them.
   */
  section?: keyof typeof PANEL_SECTIONS;
  /** Access to at least one independent feature on a combined screen. */
  anyAccess?: readonly { module: string; permission: string }[];
};

export type PanelSectionTab = Pick<
  PanelNavItem,
  | "href"
  | "labelKey"
  | "module"
  | "permission"
  | "ownerOnly"
  | "organizationTypes"
>;

export const PANEL_SECTIONS = {
  inventory: [
    {
      href: "/panel/inventory",
      labelKey: "inventoryStock",
      module: "shared.inventory",
      permission: "inventory.read",
    },
    {
      href: "/panel/inventory/items",
      labelKey: "inventoryItems",
      module: "shared.inventory",
      permission: "inventory.read",
    },
    {
      href: "/panel/inventory/documents",
      labelKey: "inventoryDocuments",
      module: "shared.inventory",
      permission: "inventory.manage",
    },
    {
      href: "/panel/inventory/settings",
      labelKey: "inventorySettings",
      module: "shared.inventory",
      permission: "inventory.manage",
    },
  ],
  messages: [
    {
      href: "/panel/notifications",
      labelKey: "messagesInquiries",
      module: "shared.sites",
      permission: "site.content.edit",
    },
    {
      href: "/panel/notifications/automation",
      labelKey: "messagesAutomation",
      module: "shared.notifications",
      permission: "notifications.manage",
    },
  ],
  website: [
    { href: "/panel/sites", labelKey: "sectionSite", module: "shared.sites" },
    {
      href: "/panel/seo",
      labelKey: "seo",
      module: "shared.seo",
      permission: "seo.audit.read",
    },
    {
      href: "/panel/seo/search-console",
      labelKey: "searchConsole",
      module: "shared.seo",
      permission: "seo.audit.read",
    },
  ],
  subscription: [
    {
      href: "/panel/settings/billing",
      labelKey: "sectionPlan",
      module: "shared.billing",
      ownerOnly: true,
    },
    {
      href: "/panel/settings/credits",
      labelKey: "credits",
      module: "shared.billing",
    },
  ],
  settings: [
    {
      href: "/panel/settings/company",
      labelKey: "sectionCompany",
      permission: "organization.settings.manage",
    },
    {
      href: "/panel/settings/history",
      labelKey: "sectionHistory",
      permission: "organization.settings.manage",
    },
    { href: "/panel/settings/account", labelKey: "sectionAccount" },
    {
      href: "/panel/settings/services",
      labelKey: "sectionServices",
      module: "shared.booking",
      permission: "booking.appointment.manage",
    },
    {
      href: "/panel/integrations",
      labelKey: "sectionAdvanced",
      module: "shared.notifications",
      permission: "integrations.manage",
    },
    // The product's own settings come after core's (ProductSettingsSection).
    ...(product.settingsSections ?? []),
  ],
} satisfies Record<string, PanelSectionTab[]>;

/**
 * What the current membership may be offered. `permissions` is null only
 * without an active organization. The API enforces access regardless; this
 * keeps the panel from leading anyone to a 403.
 */
export type PanelAccess = {
  modules: readonly string[];
  permissions: readonly string[] | null;
  isOwner: boolean;
  /** A limited role of the organization's type (ADR-050). */
  limited: boolean;
  organizationType?: string;
};

export function panelAccess(
  organization: OrganizationSummary | null,
): PanelAccess {
  const type = organization?.organization_type;
  return {
    modules: [...modulesFor(type)],
    permissions: organization?.permissions ?? null,
    isOwner: organization?.role === "owner",
    limited: typeRole(type, organization?.role)?.limited ?? false,
    organizationType: type,
  };
}

const WORK: PanelNavItem[] = [
  { href: "/panel", icon: HomeIcon, labelKey: "today", group: "work" },
  {
    href: "/panel/calendar",
    icon: CalendarDaysIcon,
    labelKey: "calendar",
    group: "work",
    module: "shared.booking",
    permission: "booking.appointment.read",
  },
  {
    href: "/panel/farms",
    icon: WarehouseIcon,
    labelKey: "farms",
    group: "work",
    module: "shared.farms",
    permission: "farms.read",
  },
  {
    // Magazyn prowadzi firma, ale własny zapas widzi każdy, kto nim pracuje.
    href: "/panel/inventory",
    icon: PackageIcon,
    labelKey: "inventory",
    group: "work",
    module: "shared.inventory",
    permission: "inventory.read",
    section: "inventory",
  },
  {
    // Every farm's animals at once: how a trimmer looks for one ear tag.
    href: "/panel/animals",
    icon: PawPrintIcon,
    labelKey: "animals",
    group: "work",
    module: "shared.farms",
    permission: "farms.read",
  },
];

const COMPANY: PanelNavItem[] = [
  {
    href: "/panel/team",
    icon: UsersIcon,
    labelKey: "team",
    group: "company",
    permission: "organization.members.read",
  },
  {
    // Above the website on purpose: the business card is the floor of the
    // offer and the website the option above it (ADR-053).
    href: "/panel/profile",
    icon: ContactIcon,
    labelKey: "profile",
    group: "company",
    module: "shared.profiles",
    permission: "profiles.manage",
  },
  {
    href: "/panel/sites",
    icon: Globe2Icon,
    labelKey: "website",
    group: "company",
    module: "shared.sites",
    permission: "site.content.edit",
    section: "website",
  },
  {
    href: "/panel/notifications",
    icon: MessageSquareTextIcon,
    labelKey: "messages",
    group: "company",
    module: "shared.notifications",
    anyAccess: [
      { module: "shared.notifications", permission: "notifications.manage" },
      { module: "shared.sites", permission: "site.content.edit" },
    ],
    section: "messages",
  },
  {
    // The owner lands on the plan, everyone else on the credits they spend.
    href: "/panel/settings/billing",
    icon: CreditCardIcon,
    labelKey: "billing",
    group: "company",
    module: "shared.billing",
    notForLimited: true,
    section: "subscription",
  },
];

const SETTINGS: PanelNavItem = {
  href: "/panel/settings/company",
  icon: SettingsIcon,
  labelKey: "settings",
  group: "company",
  section: "settings",
};

export function allows(
  access: PanelAccess,
  item: Pick<
    PanelNavItem,
    | "module"
    | "permission"
    | "ownerOnly"
    | "notForLimited"
    | "anyAccess"
    | "organizationTypes"
  >,
): boolean {
  if (item.module && !access.modules.includes(item.module)) return false;
  if (
    item.anyAccess &&
    !item.anyAccess.some((feature) => allows(access, feature))
  )
    return false;
  if (item.ownerOnly && !access.isOwner) return false;
  if (item.notForLimited && access.limited) return false;
  if (
    item.permission &&
    access.permissions &&
    !access.permissions.includes(item.permission)
  )
    return false;
  return (
    !item.organizationTypes ||
    (access.organizationType !== undefined &&
      item.organizationTypes.includes(access.organizationType))
  );
}

/** A menu entry as offered: the pages it unfolds to, when there are several. */
export type PanelNavEntry = PanelNavItem & { pages?: PanelSectionTab[] };

export function panelNavigation(access: PanelAccess): {
  work: PanelNavEntry[];
  company: PanelNavEntry[];
} {
  const fromProduct = (product.navigation ?? []).map((item): PanelNavItem => ({
    ...item,
    group: item.group ?? "work",
  }));
  const visible = (items: PanelNavItem[]): PanelNavEntry[] =>
    items.flatMap((item) => {
      if (!allows(access, item)) return [];
      if (!item.section) return [item];
      const pages = PANEL_SECTIONS[item.section].filter((tab) =>
        allows(access, tab),
      );
      if (pages.length === 0) return [];
      // One page is the entry itself: nothing to unfold.
      return [
        {
          ...item,
          href: pages[0].href,
          ...(pages.length > 1 ? { pages } : {}),
        },
      ];
    });
  return {
    work: visible([...WORK, ...fromProduct.filter((i) => i.group === "work")]),
    // Settings closes the list whatever the product adds.
    company: visible([
      ...COMPANY,
      ...fromProduct.filter((i) => i.group === "company"),
      SETTINGS,
    ]),
  };
}

/** The tabs of the section `pathname` is in, when there is more than one. */
export function sectionTabs(
  pathname: string,
  access: PanelAccess,
): PanelSectionTab[] | null {
  for (const tabs of Object.values(PANEL_SECTIONS) as PanelSectionTab[][]) {
    if (!tabs.some((tab) => matches(pathname, tab.href))) continue;
    const visible = tabs.filter((tab) => allows(access, tab));
    return visible.length > 1 ? visible : null;
  }
  return null;
}

/**
 * aria-current for a menu entry: "page" on its own page, "true" anywhere else
 * inside it (a sub-page, or another tab of its section), so a screen reader
 * does not hear two links claiming to be the current page.
 */
export function ariaCurrent(
  pathname: string,
  item: PanelNavItem,
): "page" | "true" | undefined {
  if (pathname === item.href) return "page";
  if (item.href === "/panel") return undefined;
  const tabs: PanelSectionTab[] = item.section
    ? PANEL_SECTIONS[item.section]
    : [];
  return [item.href, ...tabs.map((tab) => tab.href)].some((href) =>
    matches(pathname, href),
  )
    ? "true"
    : undefined;
}

export function isActive(pathname: string, item: PanelNavItem): boolean {
  return ariaCurrent(pathname, item) !== undefined;
}

export function matches(pathname: string, href: string): boolean {
  return pathname === href || pathname.startsWith(`${href}/`);
}

/**
 * The page of a section `pathname` is on: the deepest match, because the
 * first page is often the section's root ("/panel/inventory" also matches
 * "/panel/inventory/items").
 */
export function currentPage(
  pathname: string,
  pages: readonly Pick<PanelSectionTab, "href">[],
): string | undefined {
  return pages
    .map((page) => page.href)
    .filter((href) => matches(pathname, href))
    .sort((a, b) => b.length - a.length)[0];
}
