"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowRightIcon } from "lucide-react";

import {
  getPublicLocales,
  listContentTypes,
  listSites,
  type ContentTypes,
  type SiteSummary,
} from "@saas-core/api-client";
import { Link } from "#i18n/navigation";
import { companyLocales, type CompanyLocale } from "#lib/company-locales";
import { productSite } from "#lib/product-site/site";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

/**
 * The start page of a platform workspace (ADR-077 pkt 9): what the platform
 * has written, before anything else — its content types, how many entries
 * they hold and how many of those readers get, and the languages it writes
 * in. Read from what „Treści” reads, so the first screen and that list never
 * disagree. It asks for nothing a publisher is refused.
 *
 * Nothing here is about a site (ADR-079 pkt 29): no host serves the
 * workspace's builder site, so the card names no pages, no publication of a
 * site, no address and no domain. What is published is shown by the
 * product's own pages — on the host this panel is on, where the product has
 * such pages.
 */
type Loaded =
  | { site: null }
  | {
      site: SiteSummary;
      types: ContentTypes["types"];
      languages: CompanyLocale[];
    };

async function read(): Promise<Loaded> {
  // The record the content hangs on: the workspace's quota is one
  // (`sites.max`, ADR-077 pkt 2).
  const site = (await listSites()).items[0];
  if (!site) return { site: null };
  const [types, locales] = await Promise.all([
    listContentTypes(site.id),
    getPublicLocales(),
  ]);
  return {
    site,
    // A type that is switched off shows nothing to anybody.
    types: types.types.filter((row) => !row.collection.archived),
    languages: companyLocales(locales, [site.default_locale]),
  };
}

export function SiteState() {
  const t = useTranslations("SiteState");
  const [state, setState] = useState<Loaded>();
  const [failed, setFailed] = useState(false);

  const load = useCallback(async () => {
    setFailed(false);
    try {
      setState(await read());
    } catch {
      setFailed(true);
    }
  }, []);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- initial load
    void load();
  }, [load]);

  if (failed)
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("title")}</h2>
          </CardTitle>
          <CardDescription role="alert">{t("failed")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </CardContent>
      </Card>
    );

  if (!state)
    return (
      <div className="h-56 animate-pulse rounded-xl bg-muted">
        <span className="sr-only">{t("loading")}</span>
      </div>
    );

  if (!state.site)
    return (
      <Card>
        <CardHeader>
          <CardTitle>
            <h2>{t("emptyTitle")}</h2>
          </CardTitle>
          <CardDescription>{t("emptyBody")}</CardDescription>
        </CardHeader>
        <CardContent>
          <Link className={buttonVariants()} href="/panel/sites/content">
            {t("emptyAction")}
            <ArrowRightIcon aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>
    );

  const { types, languages } = state;
  // The product's own host: the panel stands on it, port included.
  const host = productSite ? window.location.host : "";
  const entries = types.reduce((sum, row) => sum + row.entries, 0);
  const published = types.reduce((sum, row) => sum + row.published, 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>{t("title")}</h2>
        </CardTitle>
        <CardDescription>
          {host ? t("shownAt", { host }) : t("noProductPages")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-4 text-sm sm:grid-cols-3">
          <Fact label={t("types")}>
            {types.length
              ? types.map((row) => row.collection.name).join(", ")
              : t("typesNone")}
          </Fact>
          <Fact label={t("entries")}>
            {t("entriesCount", { count: entries })}
            {entries > 0 ? (
              <span className="block text-muted-foreground">
                {t("entriesPublished", { count: published })}
              </span>
            ) : null}
          </Fact>
          <Fact label={t("languages")}>
            {languages.map((item) => item.name).join(", ")}
          </Fact>
        </dl>
      </CardContent>
    </Card>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted-foreground">{label}</dt>
      <dd className="mt-0.5 font-medium break-words">{children}</dd>
    </div>
  );
}
