"use client";

import { useTranslations } from "next-intl";
import type { DataTableLabels } from "@saas-core/ui/components/data-table";

/** The shared list's own words, the same on every panel page (ADR-054). */
export function useDataTableLabels(): DataTableLabels {
  const t = useTranslations("DataTable");
  return {
    search: t("search"),
    empty: t("empty"),
    loading: t("loading"),
    pagination: t("pagination"),
    previousPage: t("previousPage"),
    nextPage: t("nextPage"),
    pageOf: (page, pages) => t("pageOf", { page, pages }),
  };
}
