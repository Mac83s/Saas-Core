"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useForm,
  useWatch,
  type FieldValues,
  type Path,
  type SubmitHandler,
  type UseFormReturn,
} from "react-hook-form";
import {
  ArrowRightIcon,
  ExternalLinkIcon,
  Globe2Icon,
  LockKeyholeIcon,
  PlusIcon,
  RefreshCwIcon,
  RocketIcon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createSitePage,
  getSiteLocalizationReport,
  listSiteDomains,
  listSitePages,
  listSitePublications,
  listSites,
  publishSite,
  rollbackSitePublication,
  type PageListItem,
  type ContentCollection,
  type SiteDomain,
  type SiteLocalizationReport,
  type SitePublication,
  type SiteSummary,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import { buttonVariants } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";
import {
  Combobox,
  ComboboxContent,
  ComboboxEmpty,
  ComboboxInput,
  ComboboxItem,
  ComboboxList,
} from "@saas-core/ui/components/combobox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";

import { usePublisher } from "#components/panel/panel-access";
import { PanelPage } from "#components/panel/panel-page";

import { sitesErrorMessage } from "./problem";
import { publicSiteUrl } from "./public-site-url";
import { slugifyTitle } from "./slug";
import { Link, useRouter } from "#i18n/navigation";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { AutomationConnectionsPanel } from "./connections-panel";
import { BlogPanel } from "./blog-panel";
import { ContentTypeSettings } from "./content-type-settings";
import {
  ContentTypesPanel,
  CreateContentTypeDialog,
  contentTypeHref,
  contentTypesHref,
} from "./content-types-panel";
import { DomainPanel } from "./domain-panel";
import { NavigationEditor } from "./navigation-editor";
import { PageStudio } from "./page-studio";
import { PublishDialog } from "./publish-dialog";
import { CreateCategoryDialog, TermListPanel } from "./term-list-panel";
import { useCompanyLocales } from "#lib/company-locales";
import { ProposalsQueue } from "./proposals-queue";
import { SiteRedirectsCard } from "./page-url";
import { PublicationHistory } from "./publication-history";
import { TranslationTabs } from "../translation/translation-tabs";
import { PublisherStart } from "./publisher-start";
import { SiteOnboardingWizard } from "./site-onboarding";
import { SitePagesTable } from "./site-pages-table";
import {
  TranslateSiteAction,
  TranslationsOverview,
} from "./translations-overview";

type PageValues = { name: string; key: string };

/** The pages of "Strona internetowa" (ADR-057): each one an address and an
 *  entry in PANEL_SECTIONS, sharing the site they work on. */
export type SitesSection =
  | "pages"
  | "page"
  | "menu"
  | "blog"
  // „Treści” (ADR-079 pkt 25): the list of content types, one type's
  // entries, one type's settings.
  | "content"
  | "contentType"
  | "contentTypeSettings"
  // A type's categories, and the site's tags as that type shows them (CT2).
  | "contentTypeCategories"
  | "contentTypeTags"
  | "translations"
  | "publication"
  | "address"
  | "integrations";

// Several sites are rare; which one the pages work on survives moving
// between them, per browser (a convenience, so a failed read is no loss).
// The address outranks it: `?site=<id>` on a section page, and a page's own
// site in the editor — a link, a second tab or the assistant's link must
// open the right site whatever was chosen last (UX-086).
const SELECTED_SITE_KEY = "saas-core.sites.selected";
const SITE_PARAM = "site";

function askedSiteId(): string | undefined {
  try {
    return (
      new URLSearchParams(globalThis.location?.search).get(SITE_PARAM) ??
      undefined
    );
  } catch {
    return undefined;
  }
}

/** Puts the chosen site in the address without a navigation, so copying
 *  the address carries it. */
function writeSiteToAddress(siteId: string) {
  try {
    const address = new URL(globalThis.location.href);
    address.searchParams.set(SITE_PARAM, siteId);
    globalThis.history?.replaceState(globalThis.history.state, "", address);
  } catch {
    // No address to write to: the choice still stands for this visit.
  }
}

/** The site a page belongs to, asking the likeliest site first. */
async function siteOfPage(
  pageId: string,
  siteIds: readonly string[],
): Promise<string | undefined> {
  for (const siteId of siteIds) {
    try {
      const pages = await listSitePages(siteId);
      if (pages.items.some((page) => page.id === pageId)) return siteId;
    } catch {
      // A site that will not list its pages cannot be the page's home here.
    }
  }
  return undefined;
}

function rememberedSiteId(): string | undefined {
  try {
    return globalThis.localStorage?.getItem(SELECTED_SITE_KEY) ?? undefined;
  } catch {
    return undefined;
  }
}

function rememberSiteId(siteId: string) {
  try {
    globalThis.localStorage?.setItem(SELECTED_SITE_KEY, siteId);
  } catch {
    // Storage blocked: every page starts from the first site.
  }
}

export function SitesPanel({
  canManageBilling = false,
  section = "pages",
  pageId,
  typeId,
  previewOnOpen = false,
  contentTypesOffered = true,
}: {
  canManageBilling?: boolean;
  section?: SitesSection;
  /** The page the "page" section edits. */
  pageId?: string;
  /** The content type the "contentType" sections work on. */
  typeId?: string;
  /** The list's "Preview": the editor opens with the draft preview. */
  previewOnOpen?: boolean;
  /** Whether the menu shows „Treści”; where it shows „Blog” instead, the
   *  pages of one type lead back to the blog. */
  contentTypesOffered?: boolean;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const router = useRouter();
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [pages, setPages] = useState<PageListItem[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string>();
  // The page the editor shows: its address names it, and a switch inside
  // the studio (its pages tool) swaps it without leaving the studio.
  const [selectedPageId, setSelectedPageId] = useState(pageId);
  const [report, setReport] = useState<SiteLocalizationReport>();
  const [domains, setDomains] = useState<SiteDomain[]>([]);
  // Where the site answers for its readers — what these screens write in
  // front of an address and open in a new tab. The platform's own workspace
  // has no such place (ADR-079 pkt 29): its builder site answers at no host
  // and its entries are shown by the product's own pages, so the publisher's
  // panel names no address of the site and links to none.
  const publisher = usePublisher();
  const siteAddress =
    !publisher && domains.length ? publicSiteUrl(domains) : null;
  const [publications, setPublications] = useState<SitePublication[]>([]);
  // The API pages publications by cursor; null once the oldest one is loaded.
  const [publicationsCursor, setPublicationsCursor] = useState<string | null>(
    null,
  );
  const [publication, setPublication] = useState<SitePublication>();
  const [loading, setLoading] = useState(true);
  // The translations list is asked for again: the page's refresh, or an
  // order from its header that ended.
  const [translationsReload, setTranslationsReload] = useState(0);
  // The content type a type's page shows, for its title; and the list of
  // types asked for again after one was added from the header.
  const [contentType, setContentType] = useState<ContentCollection>();
  const [contentTypesReload, setContentTypesReload] = useState(0);
  // The categories asked for again after one was added from the header.
  const [categoriesReload, setCategoriesReload] = useState(0);
  const [translationsDecided, setTranslationsDecided] = useState(0);
  // Which site the pages, report and domains on screen belong to: until they
  // arrive the list is loading, not empty, and a page is not yet "gone".
  const [detailsFor, setDetailsFor] = useState<string>();
  const [problem, setProblem] = useState<string>();
  const [requiresPlan, setRequiresPlan] = useState(false);
  const [planAttention, setPlanAttention] = useState(false);
  const pageReceipt = useRef<MutationReceipt | undefined>(undefined);
  const publishReceipt = useRef<MutationReceipt | undefined>(undefined);
  const rollbackReceipt = useRef<MutationReceipt | undefined>(undefined);
  // Which site an older page of publications may still be appended to.
  const selectedSiteIdRef = useRef<string | undefined>(undefined);
  useEffect(() => {
    selectedSiteIdRef.current = selectedSiteId;
  }, [selectedSiteId]);

  const selectedSite = sites.find((site) => site.id === selectedSiteId) ?? null;
  const selectedPage = pages.find((page) => page.id === selectedPageId) ?? null;

  const loadSites = useCallback(
    async (preferredSiteId?: string) => {
      setLoading(true);
      setProblem(undefined);
      try {
        const result = await listSites();
        setRequiresPlan(false);
        const nextSiteId =
          preferredSiteId &&
          result.items.some((item) => item.id === preferredSiteId)
            ? preferredSiteId
            : selectedSiteId &&
                result.items.some((item) => item.id === selectedSiteId)
              ? selectedSiteId
              : result.items[0]?.id;
        setSites(result.items);
        if (nextSiteId !== selectedSiteId) {
          setPages([]);
          setReport(undefined);
          setDomains([]);
          setPublications([]);
          setPublicationsCursor(null);
          setPublication(undefined);
          setSelectedPageId(undefined);
        }
        setSelectedSiteId(nextSiteId);
      } catch (error) {
        if (requiresBillingPlan(error)) {
          setPlanAttention(true);
          setProblem(undefined);
        } else setProblem(sitesErrorMessage(error, t));
      } finally {
        setLoading(false);
      }
    },
    [selectedSiteId, t],
  );

  const loadSiteDetails = useCallback(
    async (siteId: string, preferredPageId?: string) => {
      setLoading(true);
      setProblem(undefined);
      try {
        const [pageResult, localization, publicationResult, domainResult] =
          await Promise.all([
            listSitePages(siteId),
            getSiteLocalizationReport(siteId),
            listSitePublications(siteId),
            listSiteDomains(siteId),
          ]);
        setPages(pageResult.items);
        setReport(localization);
        setPublications(publicationResult.items);
        setPublicationsCursor(publicationResult.next_cursor);
        setDomains(domainResult.items);
        setSelectedPageId((current) => {
          if (
            preferredPageId &&
            pageResult.items.some((item) => item.id === preferredPageId)
          ) {
            return preferredPageId;
          }
          // A page that is gone stays named, so the editor says so rather
          // than quietly opening another one.
          return current;
        });
      } catch (error) {
        if (requiresBillingPlan(error)) {
          setPlanAttention(true);
          setProblem(undefined);
        } else {
          setPages([]);
          setReport(undefined);
          setDomains([]);
          setPublications([]);
          setPublicationsCursor(null);
          setProblem(sitesErrorMessage(error, t));
        }
      } finally {
        setDetailsFor(siteId);
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    let mounted = true;
    void listSites()
      .then(async (result) => {
        if (!mounted) return;
        setRequiresPlan(false);
        setSites(result.items);
        const known = (id?: string) =>
          result.items.some((item) => item.id === id);
        const asked = askedSiteId();
        const remembered = rememberedSiteId();
        let chosen = known(asked)
          ? asked
          : known(remembered)
            ? remembered
            : result.items[0]?.id;
        // The editor's address names a page, and the page names its site.
        if (pageId && result.items.length > 1) {
          const home = await siteOfPage(pageId, [
            ...(chosen ? [chosen] : []),
            ...result.items
              .map((item) => item.id)
              .filter((id) => id !== chosen),
          ]);
          if (!mounted) return;
          chosen = home ?? chosen;
        }
        setSelectedSiteId(chosen);
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        if (requiresBillingPlan(error)) {
          setRequiresPlan(true);
          setProblem(undefined);
        } else setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [pageId, t]);

  useEffect(() => {
    if (!selectedSiteId) return;
    let mounted = true;
    void Promise.all([
      listSitePages(selectedSiteId),
      getSiteLocalizationReport(selectedSiteId),
      listSitePublications(selectedSiteId),
      listSiteDomains(selectedSiteId),
    ])
      .then(([pageResult, localization, publicationResult, domainResult]) => {
        if (!mounted) return;
        setPages(pageResult.items);
        setReport(localization);
        setPublications(publicationResult.items);
        setPublicationsCursor(publicationResult.next_cursor);
        setDomains(domainResult.items);
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        if (requiresBillingPlan(error)) {
          setPlanAttention(true);
          setProblem(undefined);
        } else {
          setPages([]);
          setReport(undefined);
          setDomains([]);
          setPublications([]);
          setPublicationsCursor(null);
          setProblem(sitesErrorMessage(error, t));
        }
      })
      .finally(() => {
        if (!mounted) return;
        setDetailsFor(selectedSiteId);
        setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [selectedSiteId, t]);

  /** Rejects with the server's problem; the dialog that asked says it. */
  async function createPage(values: PageValues) {
    if (!selectedSiteId) return;
    const created = await createSitePage(
      selectedSiteId,
      values,
      mutationKey(pageReceipt, `page-create-${selectedSiteId}`, values),
    );
    pageReceipt.current = undefined;
    setPlanAttention(false);
    // A new page is there to be filled: its editor opens at once.
    router.push(`/panel/sites/pages/${created.id}`);
  }

  // Swapping pages inside the studio keeps it open: the address follows
  // without a navigation, which would close and reload it.
  function switchPage(nextPageId: string) {
    setSelectedPageId(nextPageId);
    window.history.replaceState(
      window.history.state,
      "",
      window.location.pathname.replace(/[^/]+\/?$/, nextPageId),
    );
  }

  async function publishSelectedSite() {
    if (!selectedSiteId) return;
    setProblem(undefined);
    try {
      const created = await publishSite(
        selectedSiteId,
        mutationKey(publishReceipt, `site-publish-${selectedSiteId}`, {
          site_id: selectedSiteId,
          page_versions: pages.map((page) => [page.id, page.version]),
        }),
      );
      publishReceipt.current = undefined;
      setPlanAttention(false);
      setPublication(created);
      await Promise.all([
        loadSites(selectedSiteId),
        loadSiteDetails(selectedSiteId),
      ]);
    } catch (error) {
      if (requiresBillingPlan(error)) {
        setPlanAttention(true);
        setProblem(undefined);
      } else setProblem(sitesErrorMessage(error, t));
    }
  }

  async function loadOlderPublications(cursor: string) {
    if (!selectedSiteId) return;
    const siteId = selectedSiteId;
    try {
      const older = await listSitePublications(siteId, cursor);
      // Another site may have been chosen while the page was on its way.
      if (siteId !== selectedSiteIdRef.current) return;
      setPublications((current) => [...current, ...older.items]);
      setPublicationsCursor(older.next_cursor);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  }

  async function rollbackPublication(target: SitePublication) {
    if (!selectedSiteId) return;
    setProblem(undefined);
    setLoading(true);
    try {
      const restored = await rollbackSitePublication(
        selectedSiteId,
        target.id,
        mutationKey(rollbackReceipt, `site-rollback-${selectedSiteId}`, {
          publication_id: target.id,
        }),
      );
      rollbackReceipt.current = undefined;
      setPlanAttention(false);
      setPublication(restored);
      await Promise.all([
        loadSites(selectedSiteId),
        loadSiteDetails(selectedSiteId, selectedPageId),
      ]);
    } catch (error) {
      if (requiresBillingPlan(error)) {
        setPlanAttention(true);
        setProblem(undefined);
      } else setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    setTranslationsReload((value) => value + 1);
    await loadSites(selectedSiteId);
    if (selectedSiteId) await loadSiteDetails(selectedSiteId, selectedPageId);
  }

  // Until the sites arrive the page is the section's, not the onboarding's.
  const hasSite = sites.length > 0 || loading;
  const detailsLoading = loading || detailsFor !== selectedSiteId;
  // A page of one content type stands under „Treści”, named after the type.
  // „Kategorie” and „Tagi” are named for themselves; the type is the eyebrow
  // that leads back to its entries.
  const ofTermList =
    section === "contentTypeCategories" || section === "contentTypeTags";
  const ofContentType =
    section === "contentType" ||
    section === "contentTypeSettings" ||
    ofTermList;
  // What these screens are the parts of: a company's site — or, in the
  // platform's own workspace, its content, which no site shows (ADR-079
  // pkt 29).
  const siteTitle = t(publisher ? "titlePublisher" : "title");
  const heading = (
    <PanelPage
      actions={
        <>
          {section === "pages" && selectedSite ? (
            <CreatePageDialog
              onCreate={createPage}
              onPlanRequired={() => setPlanAttention(true)}
            />
          ) : null}
          {section === "content" && selectedSiteId ? (
            <CreateContentTypeDialog
              address={siteAddress}
              defaultLocale={selectedSite?.default_locale}
              key={selectedSiteId}
              onCreated={(created) => {
                setContentTypesReload((value) => value + 1);
                router.push(contentTypeHref(selectedSiteId, created.id));
              }}
              siteId={selectedSiteId}
            />
          ) : null}
          {section === "contentTypeCategories" && selectedSiteId && typeId ? (
            <CreateCategoryDialog
              key={`${selectedSiteId}-${typeId}`}
              onCreated={() => setCategoriesReload((value) => value + 1)}
              typeId={typeId}
            />
          ) : null}
          {section === "translations" && selectedSiteId ? (
            <TranslateSiteAction
              key={selectedSiteId}
              onDone={() => setTranslationsReload((value) => value + 1)}
              onOrdered={() => setTranslationsReload((value) => value + 1)}
              siteId={selectedSiteId}
            />
          ) : null}
          <Button
            aria-label={common("refresh")}
            disabled={loading}
            onClick={() => void refresh()}
            size="icon"
            variant="outline"
          >
            <RefreshCwIcon
              aria-hidden="true"
              className={loading ? "animate-spin" : ""}
            />
          </Button>
        </>
      }
      description={
        !hasSite
          ? t(publisher ? "descriptionPublisher" : "description")
          : section === "page"
            ? t("sections.page.description")
            : // A platform workspace's content is no site's: where a screen's
              // line speaks of the site, it has one of its own.
              publisher && t.has(`sections.${section}.descriptionPublisher`)
              ? t(`sections.${section}.descriptionPublisher`)
              : t(`sections.${section}.description`)
      }
      eyebrow={
        !hasSite
          ? publisher
            ? siteTitle
            : t("panelEyebrow")
          : section === "page"
            ? t("sections.pages.title")
            : ofTermList
              ? (contentType?.name ??
                t(
                  contentTypesOffered
                    ? "sections.content.title"
                    : "sections.blog.title",
                ))
              : ofContentType
                ? t("sections.content.title")
                : siteTitle
      }
      eyebrowHref={
        !hasSite
          ? undefined
          : section === "page"
            ? "/panel/sites"
            : ofTermList && selectedSiteId && typeId
              ? // Back to the type's entries — which, where the menu says
                // „Blog”, is the blog screen.
                contentTypesOffered
                ? contentTypeHref(selectedSiteId, typeId)
                : `/panel/sites/blog?site=${selectedSiteId}`
              : ofContentType
                ? selectedSiteId
                  ? contentTypesHref(selectedSiteId)
                  : "/panel/sites/content"
                : undefined
      }
      title={
        !hasSite
          ? siteTitle
          : section === "page"
            ? (selectedPage?.name ?? t("sections.page.title"))
            : ofContentType && !ofTermList
              ? (contentType?.name ?? t(`sections.${section}.title`))
              : t(`sections.${section}.title`)
      }
      titleId="sites-heading"
    />
  );

  const publishedSiteUrl = selectedSite?.current_publication_id
    ? siteAddress
    : null;

  if (requiresPlan) {
    return (
      <section className="space-y-6" aria-labelledby="sites-heading">
        {heading}
        <Card className="overflow-hidden border-primary/25 bg-gradient-to-br from-primary/10 via-background to-background">
          <CardHeader className="max-w-3xl space-y-3 p-7 sm:p-10">
            <span className="flex size-12 items-center justify-center rounded-2xl bg-primary text-primary-foreground shadow-sm">
              <LockKeyholeIcon aria-hidden="true" className="size-5" />
            </span>
            <CardTitle className="text-2xl">
              <h2>{t("planRequiredTitle")}</h2>
            </CardTitle>
            <CardDescription className="text-base leading-7">
              {t(
                canManageBilling
                  ? "planRequiredDescription"
                  : "planRequiredOwnerDescription",
              )}
            </CardDescription>
          </CardHeader>
          {canManageBilling ? (
            <CardContent className="px-7 pb-7 sm:px-10 sm:pb-10">
              <Link
                className={buttonVariants({
                  className: "rounded-xl",
                  size: "lg",
                })}
                href="/panel/settings/billing"
              >
                {t("choosePlan")}
                <ArrowRightIcon aria-hidden="true" />
              </Link>
            </CardContent>
          ) : null}
        </Card>
      </section>
    );
  }

  if (loading && sites.length === 0) {
    return (
      <section className="space-y-6" aria-labelledby="sites-heading">
        {heading}
        <Card aria-busy="true">
          <CardContent className="py-12 text-center text-sm text-muted-foreground">
            {t("onboardingLoading")}
          </CardContent>
        </Card>
      </section>
    );
  }

  if (sites.length === 0) {
    return (
      <section className="space-y-6" aria-labelledby="sites-heading">
        {heading}
        {problem ? (
          <div
            className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
            role="alert"
          >
            {problem}
          </div>
        ) : null}
        {/* A company starts with its site's address and name. The platform's
            workspace has no site anybody opens (ADR-079 pkt 29): it starts
            with the language it writes in, and nothing else. */}
        {publisher ? (
          <PublisherStart onCompleted={(created) => loadSites(created.id)} />
        ) : (
          <SiteOnboardingWizard
            onCompleted={(created) => loadSites(created.id)}
          />
        )}
      </section>
    );
  }

  return (
    <section className="space-y-6" aria-labelledby="sites-heading">
      {heading}
      {section === "translations" ? (
        // Asked again when what waits may have changed: a result accepted in
        // the overview, an order placed or ended.
        <TranslationTabs key={`${translationsDecided}|${translationsReload}`} />
      ) : null}

      {problem && (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </div>
      )}

      {planAttention && (
        <div
          className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-warning-foreground/30 bg-warning p-4 text-sm"
          role="alert"
        >
          <div className="flex min-w-0 items-start gap-3">
            <LockKeyholeIcon
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-warning-foreground"
            />
            <div>
              <p className="font-medium">{t("planAttentionTitle")}</p>
              <p className="mt-1 text-muted-foreground">
                {t(
                  canManageBilling
                    ? "planAttentionDescription"
                    : "planAttentionOwnerDescription",
                )}
              </p>
            </div>
          </div>
          {canManageBilling ? (
            <Link
              className={buttonVariants({ size: "sm", variant: "outline" })}
              href="/panel/settings/billing"
            >
              {t("reviewPlan")}
              <ArrowRightIcon aria-hidden="true" />
            </Link>
          ) : null}
        </div>
      )}

      {/* The site's own line: its name, which languages are on the site and
          whether it is published — all of it the builder site's state, which
          a platform workspace's content has none of (ADR-079 pkt 29). */}
      {selectedSite && !publisher && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border p-4">
          <Globe2Icon
            aria-hidden="true"
            className="size-5 shrink-0 text-muted-foreground"
          />
          <span className="font-medium">{selectedSite.name}</span>
          {/* The same languages and states as the readiness below (W8). */}
          {(report?.site_id === selectedSite.id
            ? report.languages
            : [
                {
                  locale: selectedSite.default_locale,
                  is_source: true,
                  live: Boolean(selectedSite.current_publication_id),
                },
              ]
          ).map((language) => (
            <Badge
              key={language.locale}
              variant={
                language.is_source
                  ? "neutral"
                  : language.live
                    ? "success"
                    : "warning"
              }
            >
              {t(
                language.is_source
                  ? "siteLanguageSource"
                  : language.live
                    ? "siteLanguageLive"
                    : "siteLanguageNotLive",
                { locale: language.locale.toUpperCase() },
              )}
            </Badge>
          ))}
          <Badge
            variant={
              selectedSite.current_publication_id ? "default" : "secondary"
            }
          >
            {t(selectedSite.current_publication_id ? "published" : "draftOnly")}
          </Badge>
          {publishedSiteUrl && (
            <a
              className={buttonVariants({
                className: sites.length > 1 ? "" : "sm:ml-auto",
                size: "sm",
                variant: "outline",
              })}
              href={publishedSiteUrl}
              rel="noreferrer"
              target="_blank"
            >
              {t("openPublishedSite")}
              <ExternalLinkIcon aria-hidden="true" />
            </a>
          )}
          {/* A picker for a single site is a control that can only be set to
              what it already shows, so it appears once there is a choice. */}
          {sites.length > 1 && (
            <Field className="ml-auto w-full sm:w-72">
              <FieldLabel className="sr-only" htmlFor="site-picker">
                {t("chooseSite")}
              </FieldLabel>
              <Combobox
                isItemEqualToValue={(item, value) => item.id === value.id}
                itemToStringLabel={(item) => item.name}
                itemToStringValue={(item) => item.id}
                items={sites}
                onValueChange={(item) => {
                  setPublication(undefined);
                  if (!item) {
                    setPages([]);
                    setReport(undefined);
                    setDomains([]);
                    setPublications([]);
                    setPublicationsCursor(null);
                    setSelectedPageId(undefined);
                    setSelectedSiteId(undefined);
                    setLoading(false);
                    return;
                  }
                  if (item.id === selectedSiteId) return;
                  setPages([]);
                  setReport(undefined);
                  setDomains([]);
                  setPublications([]);
                  setPublicationsCursor(null);
                  setSelectedPageId(undefined);
                  setLoading(true);
                  rememberSiteId(item.id);
                  writeSiteToAddress(item.id);
                  setSelectedSiteId(item.id);
                }}
                value={selectedSite}
              >
                <ComboboxInput
                  className="w-full"
                  disabled={loading}
                  id="site-picker"
                  placeholder={t("searchSites")}
                />
                <ComboboxContent>
                  <ComboboxEmpty>{t("noSites")}</ComboboxEmpty>
                  <ComboboxList>
                    {sites.map((site) => (
                      <ComboboxItem key={site.id} value={site}>
                        <Globe2Icon aria-hidden="true" />
                        <span className="flex-1 truncate">{site.name}</span>
                        <span className="text-xs text-muted-foreground">
                          /{site.slug}
                        </span>
                      </ComboboxItem>
                    ))}
                  </ComboboxList>
                </ComboboxContent>
              </Combobox>
            </Field>
          )}
        </div>
      )}

      {/* ADR-031 splits the work into modes rather than stacking every job on
          one screen; ADR-057 makes each mode its own address in the menu. */}
      {section === "pages" && selectedSiteId && selectedSite ? (
        <SitePagesTable
          defaultLocale={selectedSite.default_locale}
          key={selectedSiteId}
          loading={detailsLoading}
          onChanged={() => loadSiteDetails(selectedSiteId)}
          onEdit={(page) => router.push(`/panel/sites/pages/${page.id}`)}
          onPreview={(page) =>
            router.push(`/panel/sites/pages/${page.id}?preview=1`)
          }
          pages={pages}
          publicBaseUrl={publishedSiteUrl}
          siteId={selectedSiteId}
        />
      ) : null}

      {section === "page" ? (
        selectedPage ? (
          <div className="flex flex-wrap gap-2">
            <PageStudio
              key={selectedSiteId}
              onChanged={() =>
                selectedSiteId
                  ? loadSiteDetails(selectedSiteId, selectedPage.id)
                  : Promise.resolve()
              }
              onClose={() => router.push("/panel/sites")}
              onSelectPage={switchPage}
              page={selectedPage}
              pages={pages}
              previewOnOpen={previewOnOpen}
            />
            <Link
              className={buttonVariants({ variant: "outline" })}
              href="/panel/sites"
            >
              {t("backToPageList")}
            </Link>
          </div>
        ) : detailsLoading ? null : (
          <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
            {t("pageNotFound")}{" "}
            <Link
              className="font-medium text-primary underline"
              href="/panel/sites"
            >
              {t("backToPageList")}
            </Link>
          </p>
        )
      ) : null}

      {section === "menu" && selectedSiteId ? (
        <NavigationEditor
          key={selectedSiteId}
          pages={pages}
          siteId={selectedSiteId}
        />
      ) : null}

      {section === "blog" && selectedSiteId ? (
        <BlogPanel
          address={siteAddress}
          defaultLocale={selectedSite?.default_locale}
          key={selectedSiteId}
          siteId={selectedSiteId}
        />
      ) : null}

      {section === "content" && selectedSiteId ? (
        <ContentTypesPanel
          key={selectedSiteId}
          reloads={contentTypesReload}
          siteId={selectedSiteId}
        />
      ) : null}

      {section === "contentType" && selectedSiteId && typeId ? (
        <BlogPanel
          address={siteAddress}
          defaultLocale={selectedSite?.default_locale}
          key={`${selectedSiteId}-${typeId}`}
          onLoaded={setContentType}
          siteId={selectedSiteId}
          typeId={typeId}
        />
      ) : null}

      {section === "contentTypeSettings" && selectedSiteId && typeId ? (
        <ContentTypeSettings
          address={siteAddress}
          key={`${selectedSiteId}-${typeId}`}
          onLoaded={setContentType}
          onSwitchedOff={() => router.push(contentTypesHref(selectedSiteId))}
          siteId={selectedSiteId}
          typeId={typeId}
        />
      ) : null}

      {(section === "contentTypeCategories" || section === "contentTypeTags") &&
      selectedSiteId &&
      typeId ? (
        <TermListPanel
          address={siteAddress}
          key={`${selectedSiteId}-${typeId}-${section}`}
          kind={section === "contentTypeTags" ? "tags" : "categories"}
          onLoaded={setContentType}
          reloads={categoriesReload}
          siteId={selectedSiteId}
          typeId={typeId}
        />
      ) : null}

      {section === "translations" && selectedSiteId ? (
        <TranslationsOverview
          key={selectedSiteId}
          onReviewChanged={() => setTranslationsDecided((value) => value + 1)}
          // An article is public by itself, so the address does not wait for
          // the site's own publication.
          publicBaseUrl={siteAddress}
          reloadKey={translationsReload}
          siteId={selectedSiteId}
        />
      ) : null}

      {section === "publication" ? (
        <div className="space-y-6">
          <ReadinessCard
            loading={loading}
            onPublish={() => void publishSelectedSite()}
            publication={publication}
            report={report}
            siteId={selectedSiteId}
          />
          <PublicationHistory
            currentPublicationId={selectedSite?.current_publication_id}
            loading={loading}
            onLoadOlder={
              publicationsCursor
                ? () => void loadOlderPublications(publicationsCursor)
                : undefined
            }
            onRollback={(target) => void rollbackPublication(target)}
            publications={publications}
          />
        </div>
      ) : null}

      {section === "address" && selectedSiteId ? (
        <div className="space-y-6">
          <DomainPanel key={selectedSiteId} siteId={selectedSiteId} />
          <SiteRedirectsCard
            key={`redirects-${selectedSiteId}`}
            siteId={selectedSiteId}
          />
        </div>
      ) : null}

      {section === "integrations" ? (
        <div className="space-y-6">
          <ProposalsQueue />
          <AutomationConnectionsPanel />
        </div>
      ) : null}
    </section>
  );
}

function requiresBillingPlan(error: unknown) {
  return (
    error instanceof ApiProblemError &&
    error.problem.code === "entitlement_required"
  );
}

/** Adding a page: its name and key; the editor opens right after. */
function CreatePageDialog({
  onCreate,
  onPlanRequired,
}: {
  onCreate: (values: PageValues) => Promise<void>;
  onPlanRequired: () => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string>();
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().min(2, t("required")),
        key: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidKey")),
      }),
    [t],
  );
  const form = useForm<PageValues>({
    resolver: zodResolver(schema),
    defaultValues: { name: "", key: "" },
  });
  // The address follows the title until someone edits it by hand; from then on
  // it is theirs, because a key that keeps rewriting itself under an editor is
  // worse than one they have to think about once.
  const [keyEdited, setKeyEdited] = useState(false);
  const name = useWatch({ control: form.control, name: "name" });

  useEffect(() => {
    if (keyEdited) return;
    const suggestion = slugifyTitle(name ?? "");
    if (suggestion !== form.getValues("key")) {
      form.setValue("key", suggestion, { shouldValidate: false });
    }
  }, [form, keyEdited, name]);

  const submit: SubmitHandler<PageValues> = async (values) => {
    setProblem(undefined);
    try {
      await onCreate(values);
      form.reset();
      setKeyEdited(false);
      setOpen(false);
    } catch (error) {
      if (requiresBillingPlan(error)) {
        setOpen(false);
        onPlanRequired();
      } else setProblem(sitesErrorMessage(error, t));
    }
  };

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && form.formState.isSubmitting) return;
        setOpen(next);
        if (next) setProblem(undefined);
      }}
      open={open}
    >
      <DialogTrigger render={<Button type="button" />}>
        <PlusIcon aria-hidden="true" />
        {t("createPage")}
      </DialogTrigger>
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>{t("createPage")}</DialogTitle>
          <DialogDescription>{t("createPageDescription")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={form.handleSubmit(submit)}>
          <FieldGroup>
            <TextField
              form={form}
              id="page-name"
              label={t("name")}
              name="name"
            />
            <TextField
              description={keyEdited ? undefined : t("pageKeyFollowsName")}
              form={form}
              id="page-key"
              label={t("pageKey")}
              name="key"
              onInput={() => setKeyEdited(true)}
            />
          </FieldGroup>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <Button disabled={form.formState.isSubmitting} type="submit">
            <PlusIcon aria-hidden="true" />
            {form.formState.isSubmitting ? t("creating") : t("createPage")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function ReadinessCard({
  loading,
  onPublish,
  publication,
  report,
  siteId,
}: {
  loading: boolean;
  onPublish: () => void;
  publication?: SitePublication;
  report?: SiteLocalizationReport;
  siteId?: string;
}) {
  const t = useTranslations("Sites");
  const locales = useCompanyLocales(["pl", "en"]);
  // The other languages are a decision of the publish dialog, which says
  // what each would carry (TL15); the card answers for the site's own.
  const [confirming, setConfirming] = useState(false);
  const otherLanguages = (report?.languages.length ?? 0) > 1;
  const leftovers = report?.pages.some(
    (page) => page.placeholders > 0 || page.template_contact,
  );
  const deadLinks = report?.pages.some((page) => page.missing_pages.length > 0);
  const unfinished = leftovers || deadLinks;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("readiness")}</CardTitle>
        <CardDescription>{t("readinessDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {!report ? (
          <p className="text-sm text-muted-foreground">
            {t("chooseSitePrompt")}
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-2">
              {/* Slots and the template's contact are not „ready” (UX-038):
                  they may go out, but the card says what a visitor misses. */}
              <Badge
                variant={
                  !report.ready_to_publish
                    ? "destructive"
                    : unfinished
                      ? "warning"
                      : "success"
                }
              >
                {t(
                  !report.ready_to_publish
                    ? "notReady"
                    : unfinished
                      ? "readyUnfinished"
                      : "ready",
                )}
              </Badge>
              <span className="text-sm text-muted-foreground">
                {t("pageCount", { count: report.pages.length })}
              </span>
            </div>
            <div className="space-y-2">
              {report.pages.map((page) => (
                <div
                  className="flex flex-wrap items-center justify-between gap-2 rounded-lg border p-3"
                  key={page.page_id}
                >
                  <span className="font-medium">{page.page_name}</span>
                  {page.placeholders || page.template_contact ? (
                    <span className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 text-sm text-warning-foreground">
                      {[
                        page.placeholders
                          ? t("unfinishedSlots", { count: page.placeholders })
                          : "",
                        page.template_contact ? t("unfinishedContact") : "",
                      ]
                        .filter(Boolean)
                        .join(" · ")}
                      <Link
                        className="text-primary underline"
                        href={`/panel/sites/pages/${page.page_id}`}
                      >
                        {t("unfinishedShow", { page: page.page_name })}
                      </Link>
                    </span>
                  ) : null}
                  {/* A link to a record's own page that is not there: a
                      document nobody approved yet, a unit no longer shown. */}
                  {page.missing_pages.length ? (
                    <span className="flex basis-full flex-wrap items-center gap-x-3 gap-y-1 text-sm text-warning-foreground">
                      {t("unfinishedPages", {
                        count: page.missing_pages.length,
                        paths: page.missing_pages.join(", "),
                      })}
                      {page.missing_pages.some((path) =>
                        path.startsWith("/documents/"),
                      ) ? (
                        <Link
                          className="text-primary underline"
                          href="/panel/settings/documents"
                        >
                          {t("unfinishedDocuments")}
                        </Link>
                      ) : null}
                    </span>
                  ) : null}
                  <div className="flex flex-wrap gap-1">
                    {/* Only the site's own language holds the publication
                        back; another one says what it is, in amber (W8). */}
                    {page.locales
                      .filter(
                        (locale) => locale.locale === report.default_locale,
                      )
                      .map((locale) => (
                        <Badge
                          key={locale.locale}
                          variant={
                            locale.blocks_publication
                              ? "destructive"
                              : locale.state === "published" ||
                                  (locale.locale === report.default_locale &&
                                    locale.state === "complete")
                                ? "success"
                                : "warning"
                          }
                        >
                          {locale.locale.toUpperCase()}:{" "}
                          {t(
                            locale.locale === report.default_locale
                              ? `languageStates.source_${locale.state}`
                              : `languageStates.${locale.state}`,
                          )}
                        </Badge>
                      ))}
                  </div>
                </div>
              ))}
            </div>
            {report.ready_to_publish && leftovers ? (
              <p className="text-sm">{t("unfinishedPublish")}</p>
            ) : null}
            {report.ready_to_publish && deadLinks ? (
              <p className="text-sm">{t("unfinishedPagesPublish")}</p>
            ) : null}
            {otherLanguages && (
              <p className="text-sm text-muted-foreground">
                {t("publishDialog.sourceOnly")}
              </p>
            )}
            <Button
              disabled={loading || !report.ready_to_publish}
              onClick={() =>
                otherLanguages && siteId ? setConfirming(true) : onPublish()
              }
              type="button"
            >
              <RocketIcon aria-hidden="true" />
              {loading ? t("publishing") : t("publish")}
            </Button>
            {siteId && (
              <PublishDialog
                open={confirming}
                onOpenChange={setConfirming}
                siteId={siteId}
                report={report}
                locales={locales}
                publishing={loading}
                onConfirm={() => {
                  setConfirming(false);
                  onPublish();
                }}
              />
            )}
            {publication && (
              <p className="text-sm text-success-foreground" role="status">
                {t("publishedSequence", { sequence: publication.sequence })}
              </p>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}

function TextField<T extends FieldValues>({
  description,
  disabled,
  form,
  id,
  label,
  name,
  onInput,
}: {
  description?: string;
  disabled?: boolean;
  form: UseFormReturn<T>;
  id: string;
  label: string;
  name: Path<T>;
  onInput?: () => void;
}) {
  const fieldError = form.getFieldState(name, form.formState).error?.message;
  const error = typeof fieldError === "string" ? fieldError : undefined;
  const registration = form.register(name);
  const descriptionId = description ? `${id}-description` : undefined;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-describedby={descriptionId}
        aria-invalid={Boolean(error)}
        disabled={disabled}
        id={id}
        {...registration}
        onChange={(event) => {
          onInput?.();
          return registration.onChange(event);
        }}
      />
      {description ? (
        <p className="text-xs text-muted-foreground" id={descriptionId}>
          {description}
        </p>
      ) : null}
      <FieldError>{error}</FieldError>
    </Field>
  );
}
