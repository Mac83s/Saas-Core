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
  FileTextIcon,
  NewspaperIcon,
  Globe2Icon,
  PlugZapIcon,
  LockKeyholeIcon,
  PlusIcon,
  RefreshCwIcon,
  RocketIcon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createSitePage,
  setPageAutomationPolicy,
  setPageType,
  getSiteLocalizationReport,
  listSitePages,
  listSitePublications,
  listSites,
  publishSite,
  rollbackSitePublication,
  type PageSummary,
  type PageTypeValue,
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
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import {
  Tabs,
  TabsIndicator,
  TabsList,
  TabsPanel,
  TabsTab,
} from "@saas-core/ui/components/tabs";

import { sitesErrorMessage } from "./problem";
import { slugifyTitle } from "./slug";
import { Link } from "#i18n/navigation";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { AutomationPolicyField } from "./automation-policy";
import { AutomationConnectionsPanel } from "./connections-panel";
import { BlogPanel } from "./blog-panel";
import { DomainPanel } from "./domain-panel";
import { NavigationEditor } from "./navigation-editor";
import { PageEditor } from "./page-editor";
import { SiteRedirectsCard } from "./page-url";
import { PublicationHistory } from "./publication-history";
import { SiteOnboardingWizard } from "./site-onboarding";

type PageValues = { name: string; key: string };

/** The eight types W9.6.2 fixes, in the order an operator thinks about a
 *  site: the front page first, the legal pages last. */
const PAGE_TYPES: readonly PageTypeValue[] = [
  "homepage",
  "landing",
  "service",
  "about",
  "contact",
  "article_index",
  "article",
  "legal",
];

export function SitesPanel({
  canManageBilling = false,
}: {
  canManageBilling?: boolean;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [sites, setSites] = useState<SiteSummary[]>([]);
  const [pages, setPages] = useState<PageSummary[]>([]);
  const [selectedSiteId, setSelectedSiteId] = useState<string>();
  const [selectedPageId, setSelectedPageId] = useState<string>();
  const [report, setReport] = useState<SiteLocalizationReport>();
  const [publications, setPublications] = useState<SitePublication[]>([]);
  const [publication, setPublication] = useState<SitePublication>();
  const [loading, setLoading] = useState(true);
  const [problem, setProblem] = useState<string>();
  const [requiresPlan, setRequiresPlan] = useState(false);
  const [planAttention, setPlanAttention] = useState(false);
  const pageReceipt = useRef<MutationReceipt | undefined>(undefined);
  const publishReceipt = useRef<MutationReceipt | undefined>(undefined);
  const rollbackReceipt = useRef<MutationReceipt | undefined>(undefined);

  const pageSchema = useMemo(
    () =>
      z.object({
        name: z.string().min(2, t("required")),
        key: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidKey")),
      }),
    [t],
  );
  const pageForm = useForm<PageValues>({
    resolver: zodResolver(pageSchema),
    defaultValues: { name: "", key: "" },
  });

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
          setPublications([]);
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
        const [pageResult, localization, publicationResult] = await Promise.all(
          [
            listSitePages(siteId),
            getSiteLocalizationReport(siteId),
            listSitePublications(siteId),
          ],
        );
        setPages(pageResult.items);
        setReport(localization);
        setPublications(publicationResult.items);
        setSelectedPageId((current) => {
          if (
            preferredPageId &&
            pageResult.items.some((item) => item.id === preferredPageId)
          ) {
            return preferredPageId;
          }
          if (current && pageResult.items.some((item) => item.id === current)) {
            return current;
          }
          return pageResult.items[0]?.id;
        });
      } catch (error) {
        if (requiresBillingPlan(error)) {
          setPlanAttention(true);
          setProblem(undefined);
        } else {
          setPages([]);
          setReport(undefined);
          setPublications([]);
          setProblem(sitesErrorMessage(error, t));
        }
      } finally {
        setLoading(false);
      }
    },
    [t],
  );

  useEffect(() => {
    let mounted = true;
    void listSites()
      .then((result) => {
        if (!mounted) return;
        setRequiresPlan(false);
        setSites(result.items);
        setSelectedSiteId(result.items[0]?.id);
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
  }, [t]);

  useEffect(() => {
    if (!selectedSiteId) return;
    let mounted = true;
    void Promise.all([
      listSitePages(selectedSiteId),
      getSiteLocalizationReport(selectedSiteId),
      listSitePublications(selectedSiteId),
    ])
      .then(([pageResult, localization, publicationResult]) => {
        if (!mounted) return;
        setPages(pageResult.items);
        setReport(localization);
        setPublications(publicationResult.items);
        setSelectedPageId(pageResult.items[0]?.id);
      })
      .catch((error: unknown) => {
        if (!mounted) return;
        if (requiresBillingPlan(error)) {
          setPlanAttention(true);
          setProblem(undefined);
        } else {
          setPages([]);
          setReport(undefined);
          setPublications([]);
          setProblem(sitesErrorMessage(error, t));
        }
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [selectedSiteId, t]);

  const submitPage: SubmitHandler<PageValues> = async (values) => {
    if (!selectedSiteId) return;
    setProblem(undefined);
    try {
      const created = await createSitePage(
        selectedSiteId,
        values,
        mutationKey(pageReceipt, `page-create-${selectedSiteId}`, values),
      );
      pageReceipt.current = undefined;
      setPlanAttention(false);
      pageForm.reset();
      await loadSiteDetails(selectedSiteId, created.id);
    } catch (error) {
      if (requiresBillingPlan(error)) {
        setPlanAttention(true);
        setProblem(undefined);
      } else setProblem(sitesErrorMessage(error, t));
    }
  };

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
    await loadSites(selectedSiteId);
    if (selectedSiteId) await loadSiteDetails(selectedSiteId, selectedPageId);
  }

  const heading = (
    <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
      <div>
        <p className="text-sm font-medium text-primary">{t("eyebrow")}</p>
        <h1
          className="text-3xl font-semibold tracking-tight"
          id="sites-heading"
        >
          {t("title")}
        </h1>
        <p className="text-muted-foreground">{t("description")}</p>
      </div>
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
    </div>
  );

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
        <SiteOnboardingWizard
          onCompleted={(created) => loadSites(created.id)}
        />
      </section>
    );
  }

  return (
    <section className="space-y-6" aria-labelledby="sites-heading">
      {heading}

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
          className="flex flex-wrap items-start justify-between gap-4 rounded-2xl border border-amber-500/30 bg-amber-500/5 p-4 text-sm"
          role="alert"
        >
          <div className="flex min-w-0 items-start gap-3">
            <LockKeyholeIcon
              aria-hidden="true"
              className="mt-0.5 size-5 shrink-0 text-amber-700"
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

      {selectedSite && (
        <div className="flex flex-wrap items-center gap-3 rounded-lg border p-4">
          <Globe2Icon
            aria-hidden="true"
            className="size-5 shrink-0 text-muted-foreground"
          />
          <span className="font-medium">{selectedSite.name}</span>
          <Badge variant="outline">
            {selectedSite.default_locale.toUpperCase()}
          </Badge>
          <Badge
            variant={
              selectedSite.current_publication_id ? "default" : "secondary"
            }
          >
            {t(selectedSite.current_publication_id ? "published" : "draftOnly")}
          </Badge>
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
                    setPublications([]);
                    setSelectedPageId(undefined);
                    setSelectedSiteId(undefined);
                    setLoading(false);
                    return;
                  }
                  if (item.id === selectedSiteId) return;
                  setPages([]);
                  setReport(undefined);
                  setPublications([]);
                  setSelectedPageId(undefined);
                  setLoading(true);
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

      {/* ADR-031 splits the studio into modes rather than stacking every job on
          one screen. Address and publication history are things done once, so
          they sit behind their own tab instead of below the daily work. */}
      <Tabs defaultValue="pages">
        <TabsList>
          <TabsTab value="pages">
            <FileTextIcon aria-hidden="true" />
            {t("modePages")}
          </TabsTab>
          <TabsTab disabled={!selectedPage} value="content">
            {t("modeContent")}
          </TabsTab>
          <TabsTab value="blog">
            <NewspaperIcon aria-hidden="true" />
            {t("modeBlog")}
          </TabsTab>
          <TabsTab value="publish">
            <RocketIcon aria-hidden="true" />
            {t("modePublish")}
          </TabsTab>
          <TabsTab value="address">
            <Globe2Icon aria-hidden="true" />
            {t("modeAddress")}
          </TabsTab>
          <TabsTab value="integrations">
            <PlugZapIcon aria-hidden="true" />
            {t("modeIntegrations")}
          </TabsTab>
          <TabsIndicator />
        </TabsList>

        <TabsPanel value="pages">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
            <Card>
              <CardHeader>
                <CardTitle>{t("pages")}</CardTitle>
                <CardDescription>{t("pagesDescription")}</CardDescription>
              </CardHeader>
              <CardContent className="space-y-5">
                <Field>
                  <FieldLabel htmlFor="page-picker">
                    {t("choosePage")}
                  </FieldLabel>
                  <Combobox
                    disabled={!selectedSite}
                    isItemEqualToValue={(item, value) => item.id === value.id}
                    itemToStringLabel={(item) => item.name}
                    itemToStringValue={(item) => item.id}
                    items={pages}
                    onValueChange={(item) => setSelectedPageId(item?.id)}
                    value={selectedPage}
                  >
                    <ComboboxInput
                      className="w-full"
                      disabled={!selectedSite || loading}
                      id="page-picker"
                      placeholder={t("searchPages")}
                    />
                    <ComboboxContent>
                      <ComboboxEmpty>{t("noPages")}</ComboboxEmpty>
                      <ComboboxList>
                        {pages.map((page) => (
                          <ComboboxItem key={page.id} value={page}>
                            <FileTextIcon aria-hidden="true" />
                            <span className="flex-1 truncate">{page.name}</span>
                            <span className="text-xs text-muted-foreground">
                              {page.key}
                            </span>
                          </ComboboxItem>
                        ))}
                      </ComboboxList>
                    </ComboboxContent>
                  </Combobox>
                </Field>
                {selectedPage && (
                  <div className="grid gap-3 rounded-lg border p-3 sm:grid-cols-3">
                    <Summary label={t("pageKey")} value={selectedPage.key} />
                    <Summary
                      label={t("version")}
                      value={String(selectedPage.version)}
                    />
                    <Summary
                      label={t("draft")}
                      value={
                        selectedPage.current_draft_id
                          ? t("available")
                          : t("missing")
                      }
                    />
                  </div>
                )}
                {selectedPage && (
                  <PageTypeField
                    onChanged={(updated) =>
                      setPages((current) =>
                        current.map((item) =>
                          item.id === updated.id ? updated : item,
                        ),
                      )
                    }
                    page={selectedPage}
                  />
                )}
                {selectedPage && (
                  <PageAutomationSwitch
                    onChanged={(updated) =>
                      setPages((current) =>
                        current.map((item) =>
                          item.id === updated.id ? updated : item,
                        ),
                      )
                    }
                    page={selectedPage}
                  />
                )}
              </CardContent>
            </Card>

            <div className="space-y-6">
              <CreatePageCard
                disabled={!selectedSite}
                form={pageForm}
                onSubmit={submitPage}
              />
              {selectedSiteId && (
                <NavigationEditor
                  key={selectedSiteId}
                  pages={pages}
                  siteId={selectedSiteId}
                />
              )}
            </div>
          </div>
        </TabsPanel>

        <TabsPanel value="content">
          {selectedPage ? (
            <PageEditor
              key={selectedPage.id}
              onChanged={() =>
                selectedSiteId
                  ? loadSiteDetails(selectedSiteId, selectedPage.id)
                  : Promise.resolve()
              }
              page={selectedPage}
            />
          ) : (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {t("choosePageFirst")}
            </p>
          )}
        </TabsPanel>

        <TabsPanel value="blog">
          {selectedSiteId ? (
            <BlogPanel key={selectedSiteId} siteId={selectedSiteId} />
          ) : (
            <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
              {t("chooseSitePrompt")}
            </p>
          )}
        </TabsPanel>

        <TabsPanel className="space-y-6" value="publish">
          <ReadinessCard
            loading={loading}
            onPublish={() => void publishSelectedSite()}
            publication={publication}
            report={report}
          />
          <PublicationHistory
            currentPublicationId={selectedSite?.current_publication_id}
            loading={loading}
            onRollback={(target) => void rollbackPublication(target)}
            publications={publications}
          />
        </TabsPanel>

        <TabsPanel className="space-y-6" value="integrations">
          <AutomationConnectionsPanel />
        </TabsPanel>

        <TabsPanel className="space-y-6" value="address">
          {selectedSiteId && (
            <>
              <DomainPanel key={selectedSiteId} siteId={selectedSiteId} />
              <SiteRedirectsCard
                key={`redirects-${selectedSiteId}`}
                siteId={selectedSiteId}
              />
            </>
          )}
        </TabsPanel>
      </Tabs>
    </section>
  );
}

/** What kind of page this is, in the vocabulary SEO tooling uses.
 *
 *  Nothing about the page renders differently — the type is what an optimiser
 *  reasons about, and one told that the contact page is a landing page will
 *  rewrite it like one. */
function PageTypeField({
  onChanged,
  page,
}: {
  onChanged: (page: PageSummary) => void;
  page: PageSummary;
}) {
  const t = useTranslations("Sites");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  return (
    <div className="space-y-2 rounded-lg border p-3">
      <Field>
        <FieldLabel htmlFor="page-type">{t("pageTypeLabel")}</FieldLabel>
        <NativeSelect
          disabled={busy}
          id="page-type"
          onChange={(event) => {
            const next = event.target.value as PageTypeValue;
            setBusy(true);
            setProblem(undefined);
            void setPageType(page.id, next)
              .then(onChanged)
              .catch((error: unknown) => {
                setProblem(sitesErrorMessage(error, t));
              })
              .finally(() => {
                setBusy(false);
              });
          }}
          value={page.page_type}
        >
          {PAGE_TYPES.map((value) => (
            <option key={value} value={value}>
              {t(`pageType_${value}`)}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <p className="text-sm text-muted-foreground">{t("pageTypeHint")}</p>
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

/** ADR-035 §4a: what an automation may do with this page is a person's
 *  decision. The endpoint behind the field refuses API keys, so the field is
 *  the only way the value changes. */
function PageAutomationSwitch({
  onChanged,
  page,
}: {
  onChanged: (page: PageSummary) => void;
  page: PageSummary;
}) {
  const t = useTranslations("Sites");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  return (
    <div className="space-y-2">
      <AutomationPolicyField
        busy={busy}
        id="page-policy"
        onChange={(policy) => {
          setBusy(true);
          setProblem(undefined);
          void setPageAutomationPolicy(page.id, policy)
            .then(onChanged)
            .catch((error: unknown) => {
              setProblem(sitesErrorMessage(error, t));
            })
            .finally(() => {
              setBusy(false);
            });
        }}
        value={page.automation_policy}
      />
      {page.draft_author === "automation" && (
        <p className="text-sm" role="status">
          {t("pageProposalWaiting")}
        </p>
      )}
      {problem && (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      )}
    </div>
  );
}

function requiresBillingPlan(error: unknown) {
  return (
    error instanceof ApiProblemError &&
    error.problem.code === "entitlement_required"
  );
}

function CreatePageCard({
  disabled,
  form,
  onSubmit,
}: {
  disabled: boolean;
  form: UseFormReturn<PageValues>;
  onSubmit: SubmitHandler<PageValues>;
}) {
  const t = useTranslations("Sites");
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

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("createPage")}</CardTitle>
        <CardDescription>{t("createPageDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <FieldGroup>
            <TextField
              disabled={disabled}
              form={form}
              id="page-name"
              label={t("name")}
              name="name"
            />
            <TextField
              description={keyEdited ? undefined : t("pageKeyFollowsName")}
              disabled={disabled}
              form={form}
              id="page-key"
              label={t("pageKey")}
              name="key"
              onInput={() => setKeyEdited(true)}
            />
          </FieldGroup>
          <Button
            disabled={disabled || form.formState.isSubmitting}
            type="submit"
          >
            <PlusIcon aria-hidden="true" />
            {form.formState.isSubmitting ? t("creating") : t("createPage")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}

function ReadinessCard({
  loading,
  onPublish,
  publication,
  report,
}: {
  loading: boolean;
  onPublish: () => void;
  publication?: SitePublication;
  report?: SiteLocalizationReport;
}) {
  const t = useTranslations("Sites");
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
              <Badge
                variant={report.ready_to_publish ? "default" : "destructive"}
              >
                {t(report.ready_to_publish ? "ready" : "notReady")}
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
                  <div className="flex flex-wrap gap-1">
                    {page.locales.map((locale) => (
                      <Badge
                        key={locale.locale}
                        variant={locale.complete ? "outline" : "destructive"}
                      >
                        {locale.locale.toUpperCase()}:{" "}
                        {t(locale.complete ? "complete" : "incomplete")}
                      </Badge>
                    ))}
                  </div>
                </div>
              ))}
            </div>
            <Button
              disabled={loading || !report.ready_to_publish}
              onClick={onPublish}
              type="button"
            >
              <RocketIcon aria-hidden="true" />
              {loading ? t("publishing") : t("publish")}
            </Button>
            {publication && (
              <p className="text-sm text-emerald-700" role="status">
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

function Summary({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="font-medium">{value}</p>
    </div>
  );
}
