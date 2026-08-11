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

export function PublicationHistory({
  currentPublicationId,
  loading,
  onRollback,
  publications,
}: {
  currentPublicationId?: string | null;
  loading: boolean;
  onRollback: (publication: SitePublication) => void;
  publications: SitePublication[];
}) {
  const t = useTranslations("Sites");
  const locale = useLocale();
  const dateFormatter = new Intl.DateTimeFormat(locale, {
    dateStyle: "medium",
    timeStyle: "short",
  });

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("publicationHistory")}</CardTitle>
        <CardDescription>{t("publicationHistoryDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {publications.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("noPublications")}</p>
        ) : (
          publications.map((publication) => {
            const current = publication.id === currentPublicationId;
            return (
              <article
                className="flex flex-col gap-3 rounded-lg border p-4 sm:flex-row sm:items-center"
                key={publication.id}
              >
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">
                      {t("publicationSequence", {
                        sequence: publication.sequence,
                      })}
                    </span>
                    {current && <Badge>{t("current")}</Badge>}
                    {publication.source_publication_id && (
                      <Badge variant="secondary">{t("rollback")}</Badge>
                    )}
                  </div>
                  <p className="truncate text-sm text-muted-foreground">
                    {publication.created_by.email} ·{" "}
                    {dateFormatter.format(new Date(publication.created_at))}
                  </p>
                  <p className="truncate font-mono text-xs text-muted-foreground">
                    {publication.snapshot_hash}
                  </p>
                </div>
                <Button
                  disabled={current || loading}
                  onClick={() => onRollback(publication)}
                  type="button"
                  variant="outline"
                >
                  <RotateCcwIcon aria-hidden="true" />
                  {t("restore")}
                </Button>
              </article>
            );
          })
        )}
      </CardContent>
    </Card>
  );
}
