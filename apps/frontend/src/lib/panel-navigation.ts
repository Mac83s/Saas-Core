import {
  CalendarDaysIcon,
  ContactIcon,
  CreditCardIcon,
  Globe2Icon,
  HomeIcon,
  MessageSquareTextIcon,
  PackageIcon,
  PawPrintIcon,
  ServerCogIcon,
  SettingsIcon,
  SparklesIcon,
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
export type PanelNavItem = Omit<ProductNavigationItem, "group"> & {
  group: "work" | "company" | "platform";
  /** A platform operator's (staff with 2FA, S-T7), whatever the company. */
  operator?: boolean;
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
  /** Another name for whoever lacks `unless` (UX-024); see `PanelSectionTab`. */
  otherwise?: Otherwise;
};

/**
 * The name a page has for someone without a right: the warehouse's stock is
 * „Mój zapas” for whoever does not run the warehouse, „Abonament” is
 * „Kredyty” for whoever does not pay — the menu says what the page shows.
 */
type Otherwise = {
  unless: Pick<PanelNavItem, "permission" | "ownerOnly">;
  labelKey: string;
};

export type PanelSectionTab = Pick<
  PanelNavItem,
  | "href"
  | "labelKey"
  | "module"
  | "permission"
  | "ownerOnly"
  | "organizationTypes"
  | "otherwise"
> & {
  /**
   * Choosing between people only makes sense when more than one takes visits
   * (ADR-058: with one lekarka the dispatch pages hide themselves, counted
   * from the data, not from the product). "queue" also shows while something
   * waits; "teams" while a team exists.
   */
  dispatch?: "queue" | "teams";
  /** Only for a company that sells by dates (`GET /booking/overview/` `stays`). */
  stays?: boolean;
  /** A number beside the label, e.g. visits waiting in „Do przydzielenia”. */
  count?: number;
  /** The name as the API gives it, already in the panel's language — an
   * area of „Ustawienia” without a page of its own; `labelKey` otherwise. */
  label?: string;
};

/** An area of „Ustawienia” the generic page draws (answer 33a, ADR-078). */
export type SettingsAreaTab = { key: string; label: string };

export const PANEL_SECTIONS = {
  calendar: [
    {
      href: "/panel/calendar",
      labelKey: "calendar",
      module: "shared.booking",
      permission: "booking.appointment.read",
    },
    {
      href: "/panel/calendar/queue",
      labelKey: "calendarQueue",
      module: "shared.booking",
      permission: "booking.appointment.manage",
      dispatch: "queue",
    },
    {
      // Units against days (ADR-072 phase 2d); whose stay it is, the server
      // hides from whoever may not see it (UX-023).
      href: "/panel/calendar/occupancy",
      labelKey: "calendarOccupancy",
      module: "shared.booking",
      permission: "booking.appointment.read",
      stays: true,
    },
  ],
  team: [
    {
      href: "/panel/team",
      labelKey: "teamPeople",
      permission: "organization.members.read",
    },
    {
      href: "/panel/team/teams",
      labelKey: "teamTeams",
      module: "shared.booking",
      permission: "booking.appointment.read",
      dispatch: "teams",
    },
    {
      // Everybody's results: the owner's and administrator's (answer 3, phase 5).
      href: "/panel/team/performance",
      labelKey: "teamPerformance",
      module: "shared.booking",
      permission: "booking.staff.performance.read",
    },
    {
      href: "/panel/team/roles",
      labelKey: "teamRoles",
      permission: "organization.members.read",
    },
  ],
  inventory: [
    {
      href: "/panel/inventory",
      labelKey: "inventoryStock",
      module: "shared.inventory",
      permission: "inventory.read",
      otherwise: {
        unless: { permission: "inventory.manage" },
        labelKey: "inventoryMine",
      },
    },
    {
      href: "/panel/inventory/items",
      labelKey: "inventoryItems",
      module: "shared.inventory",
      permission: "inventory.read",
    },
    {
      href: "/panel/inventory/lots",
      labelKey: "inventoryLots",
      module: "shared.inventory",
      permission: "inventory.manage",
    },
    {
      href: "/panel/inventory/documents",
      labelKey: "inventoryDocuments",
      module: "shared.inventory",
      permission: "inventory.manage",
    },
    {
      // What the stock is worth and what went out: the warehouse keeper's (43a).
      href: "/panel/inventory/reports",
      labelKey: "inventoryReports",
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
  // The site's own pages first, then its reach (ADR-057; decision 7, 30.09).
  // The editor, /panel/sites/pages/<id>, belongs to "Podstrony".
  website: [
    { href: "/panel/sites", labelKey: "sitePages", module: "shared.sites" },
    { href: "/panel/sites/menu", labelKey: "siteMenu", module: "shared.sites" },
    { href: "/panel/sites/blog", labelKey: "siteBlog", module: "shared.sites" },
    {
      href: "/panel/sites/publication",
      labelKey: "sitePublication",
      module: "shared.sites",
    },
    {
      href: "/panel/sites/address",
      labelKey: "siteAddress",
      module: "shared.sites",
    },
    {
      href: "/panel/sites/integrations",
      labelKey: "siteIntegrations",
      module: "shared.sites",
    },
    // Audits and Search Console are one entry with tabs of its own (47a);
    // /panel/seo/search-console lights it up as a page under it.
    {
      href: "/panel/seo",
      labelKey: "seo",
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
      href: "/panel/settings/languages",
      labelKey: "sectionLanguages",
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
      href: "/panel/settings/bookings",
      labelKey: "sectionBookings",
      module: "shared.booking",
      permission: "organization.settings.manage",
    },
    // The product's own settings (ProductSettingsSection) stand with the
    // company's, before the technical page (UX-002).
    ...(product.settingsSections ?? []),
    {
      href: "/panel/integrations",
      labelKey: "sectionAdvanced",
      module: "shared.notifications",
      permission: "integrations.manage",
    },
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
  /** Who takes visits and what waits (GET /booking/overview/); none without the calendar. */
  booking?: {
    bookableStaff: number;
    teams: number;
    waiting: number | null;
    /** The company sells by dates: „Obłożenie” has a use. */
    stays?: boolean;
  };
  /** The areas of „Ustawienia” the person may change that have no page of
   * their own (GET …/settings/schema/). */
  settingsAreas?: readonly SettingsAreaTab[];
  /** 0 for everyone but a platform operator: 1, or 2 for a platform
   * administrator (GET /auth/me/). */
  operatorLevel?: number;
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
    section: "calendar",
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
  {
    // Last on purpose: a phone's bottom bar is the first three entries
    // (UX-083). Shown by module and permission; the plan is the page's
    // PlanGate, like SEO and Wiadomości (UX-045).
    href: "/panel/assistant",
    icon: SparklesIcon,
    labelKey: "assistant",
    group: "work",
    module: "shared.assistant",
    permission: "assistant.use",
  },
];

const COMPANY: PanelNavItem[] = [
  {
    href: "/panel/team",
    icon: UsersIcon,
    labelKey: "team",
    group: "company",
    permission: "organization.members.read",
    section: "team",
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
    otherwise: { unless: { ownerOnly: true }, labelKey: "credits" },
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

/** The platform's own settings, for its operators only (S-T5). */
const PLATFORM: PanelNavItem = {
  href: "/panel/platform",
  icon: ServerCogIcon,
  labelKey: "platformSettings",
  group: "platform",
  operator: true,
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
    | "operator"
  > & {
    dispatch?: PanelSectionTab["dispatch"];
    stays?: PanelSectionTab["stays"];
  },
): boolean {
  if (item.module && !access.modules.includes(item.module)) return false;
  if (item.operator && (access.operatorLevel ?? 0) < 1) return false;
  if (item.stays && !access.booking?.stays) return false;
  if (item.dispatch) {
    const booking = access.booking;
    if (!booking) return false;
    const choosing = booking.bookableStaff >= 2;
    if (item.dispatch === "queue" && !choosing && !booking.waiting)
      return false;
    if (item.dispatch === "teams" && !choosing && booking.teams === 0)
      return false;
  }
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
  platform: PanelNavEntry[];
} {
  const fromProduct = (product.navigation ?? []).map((item): PanelNavItem => ({
    ...item,
    group: item.group ?? "work",
  }));
  const visible = (items: PanelNavItem[]): PanelNavEntry[] =>
    items.flatMap((item) => {
      if (!allows(access, item)) return [];
      if (!item.section) return [named(access, item)];
      const pages = sectionPages(item.section, access)
        .filter((tab) => allows(access, tab))
        .map((tab) => withCount(access, tab));
      if (pages.length === 0) return [];
      // One page is the entry itself: nothing to unfold.
      return [
        {
          ...named(access, item),
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
    platform: visible([PLATFORM]),
  };
}

function withCount(access: PanelAccess, tab: PanelSectionTab): PanelSectionTab {
  const waiting = access.booking?.waiting;
  const tabNamed = named(access, tab);
  return tab.dispatch === "queue" && waiting
    ? { ...tabNamed, count: waiting }
    : tabNamed;
}

function named<T extends { labelKey: string; otherwise?: Otherwise }>(
  access: PanelAccess,
  item: T,
): T {
  return item.otherwise && !allows(access, item.otherwise.unless)
    ? { ...item, labelKey: item.otherwise.labelKey }
    : item;
}

/**
 * A section's pages: the declared ones, and in „Ustawienia” the areas the
 * generic page draws, right after the company's details (answer 33a).
 */
export function sectionPages(
  section: keyof typeof PANEL_SECTIONS,
  access: PanelAccess,
): PanelSectionTab[] {
  const pages: PanelSectionTab[] = [...PANEL_SECTIONS[section]];
  if (section === "settings" && access.settingsAreas?.length) {
    pages.splice(
      1,
      0,
      ...access.settingsAreas.map((area) => ({
        href: `/panel/settings/${area.key}`,
        labelKey: "settings",
        label: area.label,
      })),
    );
  }
  return pages;
}

/** The tabs of the section `pathname` is in, when there is more than one. */
export function sectionTabs(
  pathname: string,
  access: PanelAccess,
): PanelSectionTab[] | null {
  for (const section of Object.keys(
    PANEL_SECTIONS,
  ) as (keyof typeof PANEL_SECTIONS)[]) {
    const tabs = sectionPages(section, access);
    if (!tabs.some((tab) => matches(pathname, tab.href))) continue;
    const visible = tabs
      .filter((tab) => allows(access, tab))
      .map((tab) => withCount(access, tab));
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
  ) ||
    (item.section === "settings" && genericSettingsPage(pathname))
    ? "true"
    : undefined;
}

/** `/panel/settings/<area>` that no section names: an area the generic page draws. */
function genericSettingsPage(pathname: string): boolean {
  return (
    /^\/panel\/settings\/[a-z][a-z0-9-]*$/.test(pathname) &&
    !(Object.values(PANEL_SECTIONS) as PanelSectionTab[][]).some((tabs) =>
      tabs.some((tab) => matches(pathname, tab.href)),
    )
  );
}

/**
 * The menu entry a page stands under — its name is the page's eyebrow (R1,
 * UX-003): one source for the menu and the page, the deepest entry first.
 */
export function menuEntryFor(pathname: string): PanelNavItem | undefined {
  const fromProduct = (product.navigation ?? []).map((item): PanelNavItem => ({
    ...item,
    group: item.group ?? "work",
  }));
  return [...WORK, ...COMPANY, ...fromProduct, SETTINGS, PLATFORM]
    .filter((item) => isActive(pathname, item))
    .sort((a, b) => b.href.length - a.href.length)[0];
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
