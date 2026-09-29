"use client";

import { useLocale, useTranslations } from "next-intl";
import { RotateCcwIcon } from "lucide-react";

import type { SitePublication } from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";

import { useDataTableLabels } from "#lib/data-table-labels";

/** The site's publications, newest first, 100 at a time. */
export function PublicationHistory({
  currentPublicationId,
  loading,
  onLoadOlder,
  onRollback,
  publications,
}: {
  currentPublicationId?: string | null;
  loading: boolean;
  /** Given while the API has older publications. */
  onLoadOlder?: () => void;
  onRollback: (publication: SitePublication) => void;
  publications: SitePublication[];
}) {
  const t = useTranslations("Sites");
  const locale = useLocale();
  const labels = useDataTableLabels();
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  const columns: ColumnDef<SitePublication, unknown>[] = [
    {
      id: "publication",
      accessorKey: "sequence",
      header: t("lists.publicationColumn"),
      meta: { primary: true },
      cell: ({ row: { original: publication } }) => (
        <div className="min-w-0 space-y-1">
          <p className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              {t("publicationSequence", { sequence: publication.sequence })}
            </span>
            {publication.id === currentPublicationId && (
              <Badge>{t("current")}</Badge>
            )}
            {publication.source_publication_id && (
              <Badge variant="secondary">{t("rollback")}</Badge>
            )}
          </p>
          <p className="truncate font-mono text-xs text-muted-foreground">
            {publication.snapshot_hash}
          </p>
        </div>
      ),
    },
    {
      id: "author",
      accessorFn: (publication) => publication.created_by.email,
      header: t("lists.publicationAuthor"),
      cell: ({ row: { original: publication } }) => (
        <span className="break-all">{publication.created_by.email}</span>
      ),
    },
    {
      id: "created",
      accessorKey: "created_at",
      header: t("lists.publicationDate"),
      cell: ({ row: { original: publication } }) =>
        dateFormatter.format(new Date(publication.created_at)),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      // The live publication has nothing to go back to.
      cell: ({ row: { original: publication } }) =>
        publication.id === currentPublicationId ? null : (
          <RowActions
            items={[
              {
                label: t("restore"),
                icon: <RotateCcwIcon aria-hidden="true" />,
                inline: true,
                onSelect: () => {
                  if (!loading) onRollback(publication);
                },
              },
            ]}
            label={t("lists.publicationActionsFor", {
              sequence: publication.sequence,
            })}
          />
        ),
    },
  ];

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("publicationHistory")}</CardTitle>
        <CardDescription>{t("publicationHistoryDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <DataTable
          caption={t("lists.publicationsCaption")}
          columns={columns}
          data={publications}
          getRowId={(publication) => publication.id}
          labels={{ ...labels, empty: t("noPublications") }}
          loading={loading}
        />
        {onLoadOlder ? (
          <Button onClick={onLoadOlder} type="button" variant="outline">
            {t("lists.olderPublications")}
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}
