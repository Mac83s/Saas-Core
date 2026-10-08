"use client";

import { useCallback, useEffect, useState, type ReactNode } from "react";
import { useFormatter, useTranslations } from "next-intl";
import { ArrowRightIcon } from "lucide-react";

import {
  getPublicLocales,
  listContentCollections,
  listSiteDomains,
  listSitePages,
  listSitePublications,
  listSites,
  type ContentCollection,
  type PageListItem,
  type SiteDomain,
  type SitePublication,
  type SiteSummary,
} from "@saas-core/api-client";
import { Link } from "#i18n/navigation";
import { companyLocales, type CompanyLocale } from "#lib/company-locales";
import { productSite } from "#lib/product-site/site";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

/**
 * The start page of a platform workspace (ADR-077 pkt 9): what state its
 * site is in, before anything else. Read from what the site's own screens
 * read — the pages, the publications, the domains, the blog, the
 * workspace's languages — and said in their words, so the first screen and
 * „Podstrony” never disagree. It asks for nothing a publisher is refused.
 *
 * The site has no address of its own to show or open (ADR-079 pkt 29): no
 * host serves the workspace's builder site, and what it publishes is shown
 * by the product's own pages — on the host this panel is on, where the
 * product has such pages.
 */
type Loaded =
  | { site: null }
  | {
      site: SiteSummary;
      pages: PageListItem[];
      domains: SiteDomain[];
      published: SitePublication | null;
      collections: ContentCollection[];
      languages: CompanyLocale[];
    };

async function read(): Promise<Loaded> {
  // One site: the workspace's quota is one (`sites.max`, ADR-077 pkt 2).
  const site = (await listSites()).items[0];
  if (!site) return { site: null };
  const [pages, domains, publications, collections, locales] =
    await Promise.all([
      listSitePages(site.id),
      listSiteDomains(site.id),
      listSitePublications(site.id),
      listContentCollections(site.id),
      getPublicLocales(),
    ]);
  return {
    site,
    pages: pages.items,
    domains: domains.items,
    published:
      publications.items.find(
        (item) => item.id === site.current_publication_id,
      ) ?? null,
    collections,
    languages: companyLocales(locales, [site.default_locale]),
  };
}

/** A page whose saved content is not what readers see: the pages list's rule. */
function waits(page: PageListItem): boolean {
  return (
    page.published_version == null || page.version > page.published_version
  );
}

export function SiteState() {
  const t = useTranslations("SiteState");
  const sites = useTranslations("Sites");
  const format = useFormatter();
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
          <Link className={buttonVariants()} href="/panel/sites">
            {t("emptyAction")}
            <ArrowRightIcon aria-hidden="true" />
          </Link>
        </CardContent>
      </Card>
    );

  const { site, pages, domains, published, collections, languages } = state;
  // The product's own host: the panel stands on it, port included.
  const host = productSite ? window.location.host : "";
  const waiting = pages.filter(waits).length;
  // Never published — in the words of the site's own line on „Podstrony” —
  // then, as its pages are named there: changes waiting, or what readers see.
  const status = !site.current_publication_id
    ? (["neutral", "draftOnly"] as const)
    : waiting > 0
      ? (["warning", "pagesList.statusChanged"] as const)
      : (["success", "pagesList.statusPublished"] as const);
  // A domain of the publisher's own that does not answer yet: the one thing
  // on this card that waits for somebody outside the panel (DNS).
  const unverified = domains.find(
    (item) =>
      item.kind === "custom" &&
      (item.status === "pending" || item.status === "failed"),
  );

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h2 className="min-w-0 break-words">{site.name}</h2>
          <Badge variant={status[0]}>{sites(status[1])}</Badge>
        </CardTitle>
        <CardDescription>
          {host ? t("shownAt", { host }) : t("noOwnAddress")}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <dl className="grid gap-x-6 gap-y-4 text-sm sm:grid-cols-2 xl:grid-cols-4">
          <Fact label={t("publication")}>
            {published
              ? format.dateTime(new Date(published.created_at), {
                  dateStyle: "medium",
                  timeStyle: "short",
                })
              : t("neverPublished")}
          </Fact>
          <Fact label={t("pages")}>
            {t("pagesCount", { count: pages.length })}
            {waiting > 0 && site.current_publication_id ? (
              <span className="block text-muted-foreground">
                {t("pagesWaiting", { count: waiting })}
              </span>
            ) : null}
          </Fact>
          <Fact label={t("blog")}>
            {collections.length
              ? collections.map((item) => item.name).join(", ")
              : t("blogNone")}
          </Fact>
          <Fact label={t("languages")}>
            {languages.map((item) => item.name).join(", ")}
          </Fact>
        </dl>
        {unverified ? (
          <p className="mt-4 text-sm text-muted-foreground">
            {t(
              unverified.status === "failed" ? "domainFailed" : "domainPending",
              { hostname: unverified.hostname },
            )}{" "}
            <Link
              className="font-medium text-foreground underline underline-offset-2"
              href="/panel/sites/address"
            >
              {t("domainAction")}
            </Link>
          </p>
        ) : null}
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
