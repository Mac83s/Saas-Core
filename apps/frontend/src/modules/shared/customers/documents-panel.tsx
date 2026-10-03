"use client";

import { useEffect, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ExternalLinkIcon, PencilIcon } from "lucide-react";

import {
  listCustomerDocuments,
  type CustomerDocument,
  type CustomerDocumentList,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { useDataTableLabels } from "#lib/data-table-labels";

/**
 * Ustawienia › Dokumenty dla klientów (ADR-073 §9): the company's terms and
 * policies its customers read and agree to. The list says, per document, what
 * is in force today, in which languages, and whether a draft waits.
 */
export function CustomerDocumentsPanel() {
  const t = useTranslations("CustomerDocuments");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const [state, setState] = useState<CustomerDocumentList>();
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let mounted = true;
    void listCustomerDocuments()
      .then((value) => {
        if (mounted) setState(value);
      })
      .catch(() => {
        if (mounted) setFailed(true);
      });
    return () => {
      mounted = false;
    };
  }, [attempt]);

  const day = (value: string) =>
    format.dateTime(new Date(`${value}T12:00:00`), { dateStyle: "medium" });
  const href = (row: CustomerDocument) =>
    `/panel/settings/documents/${row.kind}`;
  const companyLocales = state?.options.locales ?? [];

  const columns: ColumnDef<CustomerDocument, unknown>[] = [
    {
      id: "document",
      header: t("colDocument"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <Link className="font-medium hover:underline" href={href(row)}>
          {t(`kinds.${row.kind}`)}
        </Link>
      ),
    },
    {
      id: "inForce",
      header: t("colInForce"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-col gap-1">
          {row.in_force ? (
            <span>
              {t("inForce", {
                number: row.in_force.number,
                date: day(row.in_force.effective_from),
              })}
            </span>
          ) : (
            <span className="text-muted-foreground">{t("notInForce")}</span>
          )}
          {row.upcoming ? (
            <span className="text-muted-foreground">
              {t("upcoming", {
                number: row.upcoming.number,
                date: day(row.upcoming.effective_from),
              })}
            </span>
          ) : null}
        </span>
      ),
    },
    {
      id: "languages",
      header: t("colLanguages"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.in_force ? (
          <span className="flex flex-wrap gap-1.5">
            {row.in_force.locales.map((code) => (
              <Badge key={code} variant="secondary">
                {code.toUpperCase()}
              </Badge>
            ))}
            {companyLocales
              .filter((code) => !row.in_force?.locales.includes(code))
              .map((code) => (
                <Badge key={code} variant="outline">
                  {t("missingLanguage", { code: code.toUpperCase() })}
                </Badge>
              ))}
          </span>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      id: "draft",
      header: t("colDraft"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        row.draft ? (
          <Badge>{t("draftWaits")}</Badge>
        ) : (
          <span className="text-muted-foreground">—</span>
        ),
    },
    {
      id: "actions",
      header: t("colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => (
        <RowActions
          items={[
            {
              label: t("edit"),
              link: <Link href={href(row)} />,
              inline: true,
              main: true,
              icon: <PencilIcon aria-hidden="true" />,
            },
            ...(row.public_url
              ? [
                  {
                    label: t("openPublic"),
                    link: (
                      <a
                        href={row.public_url}
                        rel="noreferrer"
                        target="_blank"
                      />
                    ),
                    icon: <ExternalLinkIcon aria-hidden="true" />,
                  },
                ]
              : []),
          ]}
          label={t("actionsFor", { document: t(`kinds.${row.kind}`) })}
        />
      ),
    },
  ];

  return (
    <PanelPage description={t("description")} title={t("title")}>
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button
            onClick={() => {
              setFailed(false);
              setAttempt((value) => value + 1);
            }}
            variant="outline"
          >
            {t("retry")}
          </Button>
        </div>
      ) : (
        <DataTable
          caption={t("caption")}
          columns={columns}
          data={state?.documents ?? []}
          getRowId={(row) => row.kind}
          labels={labels}
          loading={!state}
        />
      )}
    </PanelPage>
  );
}
