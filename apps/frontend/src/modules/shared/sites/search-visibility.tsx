"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  readSearchVisibility,
  type SearchVisibilitySite,
} from "@saas-core/api-client";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";

import { PanelSection } from "#components/panel/panel-page";
import { useDataTableLabels } from "#lib/data-table-labels";

type Language = SearchVisibilitySite["languages"][number];

function Address({ href }: { href: string }) {
  return (
    <a
      className="wrap-anywhere text-primary hover:underline"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {href}
    </a>
  );
}

/**
 * „Widoczność w wyszukiwarkach i AI” (TL19) on Ustawienia › Języki: per
 * site its sitemap and robots.txt, and per language the site answers in its
 * home and its llms.txt. The API lists only addresses that answer now; a
 * company with no published site gets no section at all.
 */
export function SearchVisibility() {
  const t = useTranslations("SearchVisibility");
  const labels = useDataTableLabels();
  const [sites, setSites] = useState<SearchVisibilitySite[]>([]);

  useEffect(() => {
    let mounted = true;
    void readSearchVisibility().then(
      (value) => {
        if (mounted) setSites(value.sites.filter((site) => site.origin));
      },
      // Not the page's subject: a reader who may not see the sites, or a
      // failed read, leaves the languages page as it is.
      () => undefined,
    );
    return () => {
      mounted = false;
    };
  }, []);

  if (sites.length === 0) return null;

  const columns: ColumnDef<Language, unknown>[] = [
    {
      id: "language",
      accessorKey: "name",
      header: t("colLanguage"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-wrap items-center gap-2">
          <span className="font-medium">{row.name}</span>
          <span className="text-muted-foreground uppercase">{row.locale}</span>
        </span>
      ),
    },
    {
      id: "home",
      header: t("colHome"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.home_url ? (
          <Address href={row.home_url} />
        ) : (
          <span className="text-muted-foreground">{t("noHome")}</span>
        ),
    },
    {
      id: "llms",
      header: t("colLlms"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.llms_url ? <Address href={row.llms_url} /> : null,
    },
  ];

  return (
    <PanelSection description={t("description")} title={t("title")}>
      {sites.map((site) => (
        <div className="space-y-3" key={site.site_id}>
          {sites.length > 1 ? (
            <h3 className="font-medium">{site.name}</h3>
          ) : null}
          <DataTable
            caption={t("caption", { site: site.name })}
            columns={columns}
            data={site.languages}
            getRowId={(row) => row.locale}
            labels={labels}
          />
          {site.sitemap_url && site.robots_url ? (
            <dl className="grid gap-x-4 gap-y-1 text-sm sm:grid-cols-[auto_1fr]">
              <dt className="text-muted-foreground">{t("sitemap")}</dt>
              <dd>
                <Address href={site.sitemap_url} />
              </dd>
              <dt className="text-muted-foreground">{t("robots")}</dt>
              <dd>
                <Address href={site.robots_url} />
              </dd>
            </dl>
          ) : null}
        </div>
      ))}
    </PanelSection>
  );
}
