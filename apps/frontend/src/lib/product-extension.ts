import type { ComponentType } from "react";
import type { LucideIcon } from "lucide-react";

import type { ProductContent } from "../marketing/content/types";
import type { PanelAccess } from "./panel-navigation";

export type ProductNavigationItem = {
  href: string;
  icon: LucideIcon;
  /** A key in the `DashboardNav` namespace; the product brings the message. */
  labelKey: string;
  /** Shown only when the deployment composes this module. */
  module?: string;
  /** Shown only to organizations of these types (ADR-050); all when absent. */
  organizationTypes?: readonly string[];
  /** "Praca" (daily work, the default) or "Firma" (running the business). */
  group?: "work" | "company";
  /** Hidden from a role of the organization's type that lacks it. */
  permission?: string;
};

/** The one action the panel header offers everywhere, e.g. "Start trimming". */
export type ProductPrimaryAction = Omit<ProductNavigationItem, "group">;

/**
 * A settings page of the product's own (e.g. the defaults of its field work),
 * shown as a tab of "Ustawienia" after core's tabs. The page is a file of the
 * product's own, by convention under `src/app/[locale]/panel/settings/`; the
 * tab bar shows on every path under `href`. `labelKey` is a `DashboardNav`
 * message the product brings, and the gates work as in `navigation`: a tab the
 * person may not open is not offered.
 */
export type ProductSettingsSection = Pick<
  ProductNavigationItem,
  "href" | "labelKey" | "module" | "permission" | "organizationTypes"
>;

type Messages = Record<string, Record<string, unknown>>;

/**
 * What a product plugs into the core frontend (ADR-049), all from the one file
 * it owns: `src/product/index.ts`. Its pages are files of its own under
 * `src/app`, so they need no entry here.
 */
export type ProductExtension = {
  /** Panel entries, appended to their group after core's own. */
  navigation?: ProductNavigationItem[];
  primaryAction?: ProductPrimaryAction;
  /** Tabs of "Ustawienia", appended after core's own (Company … Advanced). */
  settingsSections?: ProductSettingsSection[];
  /** Merged into core messages namespace by namespace. */
  messages?: Partial<Record<"pl" | "en", Messages>>;
  /** Copy for the marketing pages; without it they show the generic product. */
  marketing?: ProductContent;
};

/**
 * The product's own "Today" under /panel (slot file `src/product/dashboard.tsx`,
 * ADR-049). Core ships `null` there and shows its start page instead. A file of
 * its own rather than a field of `product`, because `product` is imported by
 * the menu on the client and would carry the whole dashboard into it.
 */
export type ProductDashboardProps = {
  access: PanelAccess;
  /** For the greeting; empty until the person gives a name. */
  firstName: string;
};
export type ProductDashboard = {
  component: ComponentType<ProductDashboardProps>;
} & Pick<ProductNavigationItem, "module" | "organizationTypes" | "permission">;

/**
 * A section a product renders inside the animal card (slot file
 * `src/product/animal-sections.tsx`, ADR-049 + ADR-051). The register of farms
 * and animals is core's; what a trade records about an animal — HoofCare's
 * trimmings with their ICAR lesion codes and limbs, another product's
 * treatments — belongs to the product, and core does not know it exists. The
 * section is handed the two identifiers core owns and fetches everything else
 * from the product's own endpoints. Core ships no section, so its card shows
 * the register's own details only.
 *
 * A file of its own rather than a field of `product`, for the same reason as
 * the dashboard: `product` is imported by the menu on the client.
 */
export type ProductAnimalSectionProps = {
  animalId: string;
  farmId: string;
};
export type ProductAnimalSection = {
  /** React key, and the order the card renders the sections in. */
  id: string;
  component: ComponentType<ProductAnimalSectionProps>;
} & Pick<ProductNavigationItem, "module" | "organizationTypes" | "permission">;
