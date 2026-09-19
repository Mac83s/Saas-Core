import type { LucideIcon } from "lucide-react";

import type { ProductContent } from "../marketing/content/types";

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
  /** Merged into core messages namespace by namespace. */
  messages?: Partial<Record<"pl" | "en", Messages>>;
  /** Copy for the marketing pages; without it they show the generic product. */
  marketing?: ProductContent;
};
