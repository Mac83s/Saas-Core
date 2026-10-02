import type { ComponentType } from "react";
import type { LucideIcon } from "lucide-react";
import type {
  BookingAppointment,
  BookingAppointmentInput,
  BookingCatalog,
} from "@saas-core/api-client";

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
  /**
   * The industry the site section library opens with — an industry id of the
   * section catalogue (`medicine`, `agriculture`, `electronics`), so a
   * product's customer sees the sections of their trade first. The person may
   * choose another or all of them; without it the library shows all.
   */
  siteIndustry?: string;
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

/**
 * A product's part of the calendar (slot file `src/product/calendar.tsx`,
 * ADR-067). For the kinds of visit it owns (`Service.appointment_kind`), its
 * section stands in the „Nowa wizyta” form and books the visit itself — a
 * HoofCare herd visit needs its farm, which core does not know. The section
 * may fill the form's customer and place, which the person still sees and may
 * change. Under a visit's details the product may add its own actions.
 *
 * The contract stays small on purpose (service, value, filling, errors,
 * access), so the form can change around it. Core ships `null`.
 */
/** A key present is written ("" clears it); a key left out stays as typed. */
export type ProductVisitFill = {
  customer?: { display_name?: string; phone?: string; email?: string };
  place?: { town: string; address?: string };
};
export type ProductVisitFormProps = {
  service: BookingCatalog["services"][number];
  access: PanelAccess;
  /** The product's parameters from the calendar's address, e.g. `farm`. */
  params: Readonly<Record<string, string>>;
  value: unknown;
  onChange: (value: unknown) => void;
  fill: (values: ProductVisitFill) => void;
  /** The section's field errors: its own check, or the server's answer. */
  errors: Readonly<Record<string, string>>;
};
/** What the form needs of a booked visit: whom and when, for its notice. */
export type ProductVisitBooked = Pick<
  BookingAppointment,
  "customer_name" | "starts_at" | "ends_at"
>;
export type ProductVisitDetailsProps = {
  appointment: BookingAppointment;
  access: PanelAccess;
  onChanged: (appointment: BookingAppointment) => void;
};
export type ProductCalendar = {
  /** The kinds of visit the product books itself. */
  kinds: readonly string[];
  formSection: ComponentType<ProductVisitFormProps>;
  /** The section's field errors before saving; null when it may save. */
  check: (
    value: unknown,
    input: BookingAppointmentInput,
  ) => Record<string, string> | null;
  /** Books the visit instead of core's POST: the section takes over „Zapisz”. */
  save: (args: {
    input: BookingAppointmentInput;
    value: unknown;
    idempotencyKey: string;
  }) => Promise<ProductVisitBooked>;
  /** The section's field errors in a server problem; null when not its own. */
  problemErrors?: (error: unknown) => Record<string, string> | null;
  /** Below a visit's details: the product's own actions on it. */
  detailsSection?: ComponentType<ProductVisitDetailsProps>;
  /**
   * The kinds whose details the section extends, `""` for a service without
   * a kind (HoofCare turns such an old booking into a herd visit, UX plan W1);
   * `kinds` when left out.
   */
  detailsKinds?: readonly string[];
} & Pick<ProductNavigationItem, "module" | "organizationTypes" | "permission">;
