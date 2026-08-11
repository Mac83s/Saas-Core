"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  Controller,
  useForm,
  type FieldValues,
  type Path,
  type SubmitHandler,
  type UseFormReturn,
} from "react-hook-form";
import {
  FileTextIcon,
  Globe2Icon,
  PlusIcon,
  RefreshCwIcon,
  RocketIcon,
} from "lucide-react";
import { z } from "zod";

import {
  createSite,
  createSitePage,
  getSiteLocalizationReport,
  listSitePages,
  listSitePublications,
  listSites,
  publishSite,
  rollbackSitePublication,
  type PageSummary,
  type SiteLocalizationReport,
  type SitePublication,
  type SiteSummary,
} from "@saas-core/api-client";
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@saas-core/ui/components/select";

import { sitesErrorMessage } from "./problem";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { PageEditor } from "./page-editor";
import { PublicationHistory } from "./publication-history";

type SiteValues = {
  name: string;
  slug: string;
  default_locale: "pl" | "en";
};
type PageValues = { name: string; key: string };

export function SitesPanel() {
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
  const siteReceipt = useRef<MutationReceipt | undefined>(undefined);
  const pageReceipt = useRef<MutationReceipt | undefined>(undefined);
  const publishReceipt = useRef<MutationReceipt | undefined>(undefined);
  const rollbackReceipt = useRef<MutationReceipt | undefined>(undefined);

  const siteSchema = useMemo(
    () =>
      z.object({
        name: z.string().min(2, t("required")),
        slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
        default_locale: z.enum(["pl", "en"]),
      }),
    [t],
  );
  const pageSchema = useMemo(
    () =>
      z.object({
        name: z.string().min(2, t("required")),
        key: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidKey")),
      }),
    [t],
  );
  const siteForm = useForm<SiteValues>({
    resolver: zodResolver(siteSchema),
    defaultValues: { name: "", slug: "", default_locale: "pl" },
  });
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
        setProblem(sitesErrorMessage(error, t));
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
        setPages([]);
        setReport(undefined);
        setPublications([]);
        setProblem(sitesErrorMessage(error, t));
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
        setSites(result.items);
        setSelectedSiteId(result.items[0]?.id);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
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
        setPages([]);
        setReport(undefined);
        setPublications([]);
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoading(false);
      });
    return () => {
      mounted = false;
    };
  }, [selectedSiteId, t]);

  const submitSite: SubmitHandler<SiteValues> = async (values) => {
    setProblem(undefined);
    try {
      const created = await createSite(
        values,
        mutationKey(siteReceipt, "site-create", values),
      );
      siteReceipt.current = undefined;
      siteForm.reset();
      await loadSites(created.id);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  };

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
      pageForm.reset();
      await loadSiteDetails(selectedSiteId, created.id);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
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
      setPublication(created);
      await Promise.all([
        loadSites(selectedSiteId),
        loadSiteDetails(selectedSiteId),
      ]);
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
      setPublication(restored);
      await Promise.all([
        loadSites(selectedSiteId),
        loadSiteDetails(selectedSiteId, selectedPageId),
      ]);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }

  async function refresh() {
    await loadSites(selectedSiteId);
    if (selectedSiteId) await loadSiteDetails(selectedSiteId, selectedPageId);
  }

  return (
    <section className="space-y-6" aria-labelledby="sites-heading">
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

      {problem && (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>{t("workspace")}</CardTitle>
              <CardDescription>{t("workspaceDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <Field>
                <FieldLabel htmlFor="site-picker">{t("chooseSite")}</FieldLabel>
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

              {selectedSite && (
                <div className="flex flex-wrap items-center gap-2 rounded-lg border p-3">
                  <span className="font-medium">{selectedSite.name}</span>
                  <Badge variant="outline">
                    {selectedSite.default_locale.toUpperCase()}
                  </Badge>
                  <Badge
                    variant={
                      selectedSite.current_publication_id
                        ? "default"
                        : "secondary"
                    }
                  >
                    {t(
                      selectedSite.current_publication_id
                        ? "published"
                        : "draftOnly",
                    )}
                  </Badge>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("pages")}</CardTitle>
              <CardDescription>{t("pagesDescription")}</CardDescription>
            </CardHeader>
            <CardContent className="space-y-5">
              <Field>
                <FieldLabel htmlFor="page-picker">{t("choosePage")}</FieldLabel>
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
            </CardContent>
          </Card>

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
        </div>

        <div className="space-y-6">
          <CreateSiteCard form={siteForm} onSubmit={submitSite} />
          <CreatePageCard
            disabled={!selectedSite}
            form={pageForm}
            onSubmit={submitPage}
          />
        </div>
      </div>
      {selectedPage && (
        <PageEditor
          key={selectedPage.id}
          onChanged={() =>
            selectedSiteId
              ? loadSiteDetails(selectedSiteId, selectedPage.id)
              : Promise.resolve()
          }
          page={selectedPage}
        />
      )}
    </section>
  );
}

function CreateSiteCard({
  form,
  onSubmit,
}: {
  form: UseFormReturn<SiteValues>;
  onSubmit: SubmitHandler<SiteValues>;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("createSite")}</CardTitle>
        <CardDescription>{t("createSiteDescription")}</CardDescription>
      </CardHeader>
      <CardContent>
        <form className="space-y-4" onSubmit={form.handleSubmit(onSubmit)}>
          <FieldGroup>
            <TextField
              form={form}
              id="site-name"
              label={t("name")}
              name="name"
            />
            <TextField
              form={form}
              id="site-slug"
              label={t("slug")}
              name="slug"
            />
            <Controller
              control={form.control}
              name="default_locale"
              render={({ field, fieldState }) => (
                <Field data-invalid={fieldState.invalid}>
                  <FieldLabel htmlFor="site-default-locale">
                    {t("defaultLocale")}
                  </FieldLabel>
                  <Select onValueChange={field.onChange} value={field.value}>
                    <SelectTrigger
                      aria-invalid={fieldState.invalid}
                      className="w-full"
                      id="site-default-locale"
                    >
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="pl">{common("polish")}</SelectItem>
                      <SelectItem value="en">{common("english")}</SelectItem>
                    </SelectContent>
                  </Select>
                  <FieldError>{fieldState.error?.message}</FieldError>
                </Field>
              )}
            />
          </FieldGroup>
          <Button disabled={form.formState.isSubmitting} type="submit">
            <PlusIcon aria-hidden="true" />
            {form.formState.isSubmitting ? t("creating") : t("createSite")}
          </Button>
        </form>
      </CardContent>
    </Card>
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
              disabled={disabled}
              form={form}
              id="page-key"
              label={t("pageKey")}
              name="key"
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
  disabled,
  form,
  id,
  label,
  name,
}: {
  disabled?: boolean;
  form: UseFormReturn<T>;
  id: string;
  label: string;
  name: Path<T>;
}) {
  const fieldError = form.getFieldState(name, form.formState).error?.message;
  const error = typeof fieldError === "string" ? fieldError : undefined;
  return (
    <Field data-invalid={Boolean(error)}>
      <FieldLabel htmlFor={id}>{label}</FieldLabel>
      <Input
        aria-invalid={Boolean(error)}
        disabled={disabled}
        id={id}
        {...form.register(name)}
      />
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
