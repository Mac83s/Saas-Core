"use client";

import { useTranslations } from "next-intl";

import { PageTabs } from "#components/panel/page-tabs";

/** Widoczność w Google: the audit and Search Console, one entry (47a). */
export function SeoTabs() {
  const t = useTranslations("SeoAudits");
  return (
    <PageTabs
      label={t("tabs")}
      tabs={[
        { href: "/panel/seo", label: t("tabAudit") },
        { href: "/panel/seo/search-console", label: t("tabSearchConsole") },
      ]}
    />
  );
}
