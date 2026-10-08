"use client";

/** The panel side of ADR-035 §7: a collection is a surface with its own address
 *  space, and the blog is the first one. Everything here runs against the same
 *  endpoints an integration uses, so what an operator can do by hand and what
 *  SeoContentRank can do over the API stay the same set of operations. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  useForm,
  useWatch,
  type FieldValues,
  type Path,
  type PathValue,
  type SubmitHandler,
  type UseFormReturn,
} from "react-hook-form";
import {
  EyeOffIcon,
  PencilIcon,
  PlusIcon,
  RefreshCwIcon,
  SendIcon,
  SettingsIcon,
} from "lucide-react";
import { z } from "zod";

import {
  createContentCollection,
  createContentEntry,
  listContentCollections,
  listContentEntries,
  publishContentEntry,
  setCollectionAutomationPolicy,
  setCollectionNavigation,
  withdrawContentEntry,
  type ContentCollection,
  type ContentEntry,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
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
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@saas-core/ui/components/input-group";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { Link } from "#i18n/navigation";
import { nativeName, useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { AutomationPolicyField } from "./automation-policy";
import {
  CollectionPaths,
  SECTION_PATH,
  namedPaths,
  sectionPathErrors,
  siteHost,
} from "./collection-paths";
import { contentTypeHref, contentTypesHref } from "./content-types-panel";
import { EntryEditor } from "./entry-editor";
import { EntryMetadata } from "./entry-metadata";
import { EntrySchedule } from "./entry-schedule";
import { EntryTags } from "./entry-tags";
import { EntryTranslations } from "./entry-translations";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";
import { slugFromTitle } from "./slug";

type CollectionValues = {
  name: string;
  base_path: string;
  /** The blog's name in other languages' addresses; empty follows the
   *  site's own (ADR-071 pkt 14). */
  locale_paths: Record<string, string>;
};
type EntryValues = { title: string; slug: string; locale: string };

export function BlogPanel({
  siteId,
  address,
  defaultLocale,
  typeId,
  onLoaded,
}: {
  siteId: string;
  /** The site's public address, before the blog's own part of it. */
  address?: string | null;
  /** The site's own language: its addresses carry no language prefix. */
  defaultLocale?: string;
  /** One content type's entries (ADR-079 pkt 25, `/panel/sites/content/<typ>`):
   *  no choice of section and no first-blog form, and what the type is —
   *  its address, menu, automation — lives on its settings page. Without
   *  it this is the blog screen as it has always been. */
  typeId?: string;
  /** The type shown, for the page's title. */
  onLoaded?: (collection: ContentCollection) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const [collections, setCollections] = useState<ContentCollection[]>([]);
  const [collectionId, setCollectionId] = useState<string>();
  const [entries, setEntries] = useState<ContentEntry[]>([]);
  // The API pages entries by cursor; null once the oldest one is loaded.
  const [entriesCursor, setEntriesCursor] = useState<string | null>(null);
  const [entryId, setEntryId] = useState<string>();
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const collectionReceipt = useRef<MutationReceipt | undefined>(undefined);
  const entryReceipt = useRef<MutationReceipt | undefined>(undefined);
  const publishReceipt = useRef<MutationReceipt | undefined>(undefined);

  const collection =
    collections.find((item) => item.id === collectionId) ?? null;
  const entry = entries.find((item) => item.id === entryId) ?? null;

  const collectionForm = useForm<CollectionValues>({
    resolver: zodResolver(
      z.object({
        name: z.string().min(2, t("required")),
        base_path: z
          .string()
          .regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
        locale_paths: z.record(
          z.string(),
          z
            .string()
            .refine(
              (value) => !value.trim() || SECTION_PATH.test(value.trim()),
              t("invalidSlug"),
            ),
        ),
      }),
    ),
    defaultValues: { name: "", base_path: "blog", locale_paths: {} },
  });
  const entryForm = useForm<EntryValues>({
    resolver: zodResolver(
      z.object({
        title: z.string().min(2, t("required")),
        slug: z.string().regex(/^[a-z0-9]+(?:-[a-z0-9]+)*$/, t("invalidSlug")),
        locale: z.string().min(2),
      }),
    ),
    defaultValues: { title: "", slug: "", locale: "pl" },
  });
  // An article is written in one of the company's languages (ADR-071 pkt 5).
  const entryLocales = useCompanyLocales(["pl", "en"]);
  useEffect(() => {
    const first = entryLocales[0]?.code;
    if (
      first &&
      !entryLocales.some((item) => item.code === entryForm.getValues("locale"))
    ) {
      entryForm.setValue("locale", first);
    }
  }, [entryForm, entryLocales]);

  // The company's other languages: each may name the blog its own way.
  const otherLocales = defaultLocale
    ? entryLocales.filter((item) => item.code !== defaultLocale)
    : [];
  const newBasePath = useWatch({
    control: collectionForm.control,
    name: "base_path",
  });

  const [pathEdited, setPathEdited] = useState(false);
  const [slugEdited, setSlugEdited] = useState(false);
  // „blog” until a name says otherwise: the address is never empty (UX-047).
  useSlugSuggestion(collectionForm, "name", "base_path", pathEdited, "blog");
  useSlugSuggestion(entryForm, "title", "slug", slugEdited);

  const loadEntries = useCallback(async (targetId: string) => {
    const result = await listContentEntries(targetId);
    setEntries(result.items);
    setEntriesCursor(result.next_cursor);
    return result.items;
  }, []);

  const loadMoreEntries = async () => {
    if (!collectionId || !entriesCursor) return;
    try {
      const more = await listContentEntries(collectionId, entriesCursor);
      setEntries((current) => [...current, ...more.items]);
      setEntriesCursor(more.next_cursor);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    }
  };

  const load = useCallback(async () => {
    setLoading(true);
    setProblem(undefined);
    try {
      const found = shown(await listContentCollections(siteId), typeId);
      setCollections(found);
      const next = found[0]?.id;
      setCollectionId(next);
      if (next) await loadEntries(next);
      else {
        setEntries([]);
        setEntriesCursor(null);
      }
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setLoading(false);
    }
  }, [loadEntries, siteId, t, typeId]);

  // The first load runs from the effect without setting `loading` up front: it
  // already starts true, and setting it again synchronously would queue a
  // cascading render.
  useEffect(() => {
    let mounted = true;
    void listContentCollections(siteId)
      .then(async (all) => {
        if (!mounted) return;
        const found = shown(all, typeId);
        setCollections(found);
        const next = found[0]?.id;
        setCollectionId(next);
        if (found[0]) onLoaded?.(found[0]);
        if (next) await loadEntries(next);
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
    // `onLoaded` is the page's own setter: asking again when it changes
    // identity would load the list on every render of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadEntries, siteId, t, typeId]);

  /** Every mutation follows the same shape: run it, refresh the list, surface a
   *  Problem Details message. Sharing it keeps a forgotten refresh from showing
   *  the operator a state the server no longer holds. */
  const run = useCallback(
    async (action: () => Promise<void>) => {
      setBusy(true);
      setProblem(undefined);
      try {
        await action();
      } catch (error) {
        setProblem(sitesErrorMessage(error, t));
      } finally {
        setBusy(false);
      }
    },
    [t],
  );

  const submitCollection: SubmitHandler<CollectionValues> = (values) =>
    void run(async () => {
      const named = namedPaths(values.locale_paths);
      const input = {
        key: values.base_path,
        name: values.name,
        kind: "blog" as const,
        base_path: values.base_path,
        // Only when a language got a name of its own.
        ...(Object.keys(named).length > 0 ? { locale_paths: named } : {}),
      };
      let created: ContentCollection;
      try {
        created = await createContentCollection(
          siteId,
          input,
          mutationKey(collectionReceipt, `collection-${siteId}`, input),
        );
      } catch (error) {
        // A name the server refuses is said at its field, not above the form.
        const refused = Object.entries(sectionPathErrors(error, t));
        if (refused.length === 0) throw error;
        for (const [field, message] of refused) {
          collectionForm.setError(
            field as "base_path" | `locale_paths.${string}`,
            { message },
          );
        }
        return;
      }
      collectionForm.reset({ name: "", base_path: "", locale_paths: {} });
      setCollections((current) => [...current, created]);
      setCollectionId(created.id);
      await loadEntries(created.id);
    });

  const submitEntry: SubmitHandler<EntryValues> = (values) =>
    void run(async () => {
      if (!collectionId) return;
      const created = await createContentEntry(
        collectionId,
        values,
        mutationKey(entryReceipt, `entry-${collectionId}`, values),
      );
      entryForm.reset({ title: "", slug: "", locale: values.locale });
      await loadEntries(collectionId);
      setEntryId(created.id);
    });

  function publish(target: ContentEntry) {
    if (busy) return;
    void run(async () => {
      await publishContentEntry(
        target.id,
        // Keyed on the live publication too: pressing the button twice in a
        // row is one publication, pressing it again after the first has landed
        // is a second, which is exactly what republishing means.
        mutationKey(publishReceipt, `publish-${target.id}`, {
          version: target.version,
          publication: target.publication_id,
        }),
      );
      if (collectionId) await loadEntries(collectionId);
    });
  }

  function withdraw(target: ContentEntry) {
    if (busy) return;
    void run(async () => {
      await withdrawContentEntry(target.id);
      if (collectionId) await loadEntries(collectionId);
    });
  }

  const stateLabel = (item: ContentEntry) =>
    t(item.state === "published" ? "blogStatePublished" : "blogStateDraft");
  const columns: ColumnDef<ContentEntry, unknown>[] = [
    {
      id: "title",
      accessorKey: "title",
      header: t("blogEntryTitle"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <div className="flex flex-wrap items-center gap-2">
          <span className="font-medium wrap-anywhere">{item.title}</span>
          {item.draft_author === "automation" && (
            <Badge variant="outline">{t("blogProposal")}</Badge>
          )}
          {/* The entry open in the editor below. */}
          {item.id === entryId && <Badge>{t("lists.editing")}</Badge>}
        </div>
      ),
    },
    // Which language an article is in, once there is more than one to be in:
    // its versions are rows of their own.
    ...(entryLocales.length > 1 ||
    entries.some((item) => item.locale !== entryLocales[0]?.code)
      ? [
          {
            id: "locale",
            accessorFn: (item: ContentEntry) =>
              entryLocales.find((option) => option.code === item.locale)
                ?.name ?? nativeName(item.locale),
            header: t("blogEntryLocale"),
          },
        ]
      : []),
    {
      id: "state",
      accessorFn: stateLabel,
      header: t("lists.state"),
      cell: ({ row: { original: item } }) => (
        <span className="flex flex-wrap items-center gap-1.5">
          <Badge variant={item.state === "published" ? "default" : "secondary"}>
            {stateLabel(item)}
          </Badge>
          {/* A schedule shows in the list, not only inside the opened article:
              one that did not publish must not pass unnoticed (03.10). */}
          {item.state !== "published" && item.schedule_state === "pending" && (
            <Badge variant="neutral">{t("scheduleStatePending")}</Badge>
          )}
          {item.state !== "published" && item.schedule_state === "failed" && (
            <Badge variant="destructive">{t("scheduleStateFailed")}</Badge>
          )}
        </span>
      ),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      cell: ({ row: { original: item } }) =>
        collection?.archived ? (
          // A switched-off type's entry takes one thing: being withdrawn,
          // so that it does not return with the type (ADR-079 pkt 23).
          item.state === "published" ? (
            <RowActions
              items={[
                {
                  label: t("blogWithdraw", { title: item.title }),
                  icon: <EyeOffIcon aria-hidden="true" />,
                  inline: true,
                  destructive: true,
                  onSelect: () => withdraw(item),
                },
              ]}
              label={t("lists.blogActionsFor", { title: item.title })}
            />
          ) : null
        ) : (
          <RowActions
            items={[
              {
                label: t("blogEdit", { title: item.title }),
                icon: <PencilIcon aria-hidden="true" />,
                inline: true,
                main: true,
                onSelect: () => setEntryId(item.id),
              },
              ...(item.state === "published"
                ? [
                    {
                      label: t("blogRepublish", { title: item.title }),
                      icon: <SendIcon aria-hidden="true" />,
                      inline: true,
                      onSelect: () => publish(item),
                    },
                    {
                      label: t("blogWithdraw", { title: item.title }),
                      icon: <EyeOffIcon aria-hidden="true" />,
                      // Takes the article off the site: behind "…".
                      destructive: true,
                      onSelect: () => withdraw(item),
                    },
                  ]
                : [
                    {
                      label: t("blogPublish", { title: item.title }),
                      icon: <SendIcon aria-hidden="true" />,
                      inline: true,
                      onSelect: () => publish(item),
                    },
                  ]),
            ]}
            label={t("lists.blogActionsFor", { title: item.title })}
          />
        ),
    },
  ];

  return (
    <div className="space-y-6">
      {problem && (
        <div
          className="rounded-lg border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          role="alert"
        >
          {problem}
        </div>
      )}

      {typeId && collections.length === 0 && !loading && !problem ? (
        <div className="space-y-3 text-sm">
          <p role="alert">{t("contentTypes.notFound")}</p>
          <Link className="underline" href={contentTypesHref(siteId)}>
            {t("contentTypes.backToList")}
          </Link>
        </div>
      ) : null}

      {!typeId && collections.length === 0 && !loading ? (
        <Card>
          <CardHeader>
            <CardTitle>{t("blogCreateTitle")}</CardTitle>
            <CardDescription>{t("blogCreateDescription")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form
              className="space-y-4"
              onSubmit={(event) => {
                void collectionForm.handleSubmit(submitCollection)(event);
              }}
            >
              <FieldGroup>
                <Field
                  data-invalid={Boolean(
                    collectionForm.formState.errors.name?.message,
                  )}
                >
                  <FieldLabel htmlFor="collection-name">
                    {t("blogName")}
                  </FieldLabel>
                  <Input
                    id="collection-name"
                    placeholder={t("blogNameExample")}
                    {...collectionForm.register("name")}
                  />
                  <FieldError>
                    {collectionForm.formState.errors.name?.message}
                  </FieldError>
                </Field>
                <Field
                  data-invalid={Boolean(
                    collectionForm.formState.errors.base_path?.message,
                  )}
                >
                  <FieldLabel htmlFor="collection-path">
                    {t("blogBasePath")}
                  </FieldLabel>
                  {/* Where the part goes on the site: „studio.pl/blog/” (UX-047). */}
                  <InputGroup>
                    <InputGroupAddon>
                      <InputGroupText className="max-w-48 truncate">
                        {`${(address ?? "").replace(/^https?:\/\//, "")}/`}
                      </InputGroupText>
                    </InputGroupAddon>
                    <InputGroupInput
                      id="collection-path"
                      {...collectionForm.register("base_path")}
                      onInput={() => setPathEdited(true)}
                    />
                    <InputGroupAddon align="inline-end">
                      <InputGroupText>/</InputGroupText>
                    </InputGroupAddon>
                  </InputGroup>
                  <FieldError>
                    {collectionForm.formState.errors.base_path?.message}
                  </FieldError>
                </Field>
                {/* The blog's own name in another language of the company:
                    „/en/journal/” beside „/blog/”. Empty follows the site's. */}
                {otherLocales.length > 0 && (
                  <fieldset className="space-y-3">
                    <legend className="text-sm font-medium">
                      {t("blogPathsOtherLegend")}
                    </legend>
                    <p className="text-sm text-muted-foreground">
                      {t("blogPathsFollow")}
                    </p>
                    {otherLocales.map((item) => (
                      <Field
                        data-invalid={Boolean(
                          collectionForm.formState.errors.locale_paths?.[
                            item.code
                          ],
                        )}
                        key={item.code}
                      >
                        <FieldLabel htmlFor={`collection-path-${item.code}`}>
                          {t("blogPathsLocaleLabel", { language: item.name })}
                        </FieldLabel>
                        <InputGroup>
                          <InputGroupAddon>
                            {/* The host may be cut short; the language's
                                part never is. */}
                            <InputGroupText className="gap-0">
                              <span className="max-w-36 truncate">
                                {siteHost(address)}
                              </span>
                              <span>{`/${item.code}/`}</span>
                            </InputGroupText>
                          </InputGroupAddon>
                          <InputGroupInput
                            id={`collection-path-${item.code}`}
                            placeholder={newBasePath}
                            {...collectionForm.register(
                              `locale_paths.${item.code}`,
                            )}
                          />
                          <InputGroupAddon align="inline-end">
                            <InputGroupText>/</InputGroupText>
                          </InputGroupAddon>
                        </InputGroup>
                        <FieldError>
                          {
                            collectionForm.formState.errors.locale_paths?.[
                              item.code
                            ]?.message
                          }
                        </FieldError>
                      </Field>
                    ))}
                  </fieldset>
                )}
              </FieldGroup>
              <Button disabled={busy} type="submit">
                <PlusIcon aria-hidden="true" />
                {t("blogCreate")}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {collection?.archived ? (
        <div className="space-y-3 text-sm">
          <p className="rounded-lg border bg-muted/40 p-3">
            {t("contentTypes.isOff")}
          </p>
          <Link className="underline" href={contentTypesHref(siteId)}>
            {t("contentTypes.backToList")}
          </Link>
          {entries.length > 0 ? (
            <DataTable
              caption={t("contentTypes.entriesCaption", {
                name: collection.name,
              })}
              columns={columns}
              data={entries}
              getRowId={(item) => item.id}
              labels={labels}
              loading={loading}
            />
          ) : null}
        </div>
      ) : null}

      {collection && !collection.archived && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
          <Card>
            <CardHeader>
              <CardTitle>{collection.name}</CardTitle>
              <CardDescription>
                {t("blogEntriesDescription", {
                  // The site's own language: the first the server lists.
                  path: (
                    Object.values(collection.paths ?? {})[0] ??
                    `/${collection.base_path}/`
                  ).replace(/^\/|\/$/g, ""),
                })}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {typeId ? (
                <Link
                  className={buttonVariants({ size: "sm", variant: "outline" })}
                  href={contentTypeHref(siteId, typeId, "/settings")}
                >
                  <SettingsIcon aria-hidden="true" />
                  {t("contentTypes.typeSettings")}
                </Link>
              ) : null}

              {!typeId && collections.length > 1 && (
                <Field>
                  <FieldLabel htmlFor="collection-picker">
                    {t("blogChoose")}
                  </FieldLabel>
                  <NativeSelect
                    id="collection-picker"
                    onChange={(event) => {
                      const next = event.target.value;
                      setCollectionId(next);
                      setEntryId(undefined);
                      void run(async () => {
                        await loadEntries(next);
                      });
                    }}
                    value={collection.id}
                  >
                    {collections.map((item) => (
                      <option key={item.id} value={item.id}>
                        {item.name}
                      </option>
                    ))}
                  </NativeSelect>
                </Field>
              )}

              {!typeId && (
                <CollectionPaths
                  address={address}
                  collection={collection}
                  key={collection.id}
                  onSaved={(updated) =>
                    setCollections((current) =>
                      current.map((item) =>
                        item.id === updated.id ? updated : item,
                      ),
                    )
                  }
                />
              )}

              {/* The menu a visitor sees comes from the last publication, so
                  the change lands when the site is published — the same rule
                  every other content change follows. */}
              {!typeId && (
                <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                  <input
                    checked={collection.show_in_navigation}
                    className="mt-1"
                    disabled={busy}
                    onChange={(event) => {
                      const show = event.target.checked;
                      void run(async () => {
                        const updated = await setCollectionNavigation(
                          collection.id,
                          show,
                        );
                        setCollections((current) =>
                          current.map((item) =>
                            item.id === updated.id ? updated : item,
                          ),
                        );
                      });
                    }}
                    type="checkbox"
                  />
                  <span>
                    <span className="font-medium">{t("blogInMenu")}</span>
                    <span className="block text-muted-foreground">
                      {t("blogInMenuHint")}
                    </span>
                  </span>
                </label>
              )}

              {!typeId && (
                <AutomationPolicyField
                  busy={busy}
                  id="collection-policy"
                  onChange={(policy) =>
                    void run(async () => {
                      const updated = await setCollectionAutomationPolicy(
                        collection.id,
                        policy,
                      );
                      setCollections((current) =>
                        current.map((item) =>
                          item.id === updated.id ? updated : item,
                        ),
                      );
                    })
                  }
                  value={collection.automation_policy}
                />
              )}

              {entries.length === 0 ? (
                <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  {t("blogEmpty")}
                </p>
              ) : (
                <DataTable
                  caption={
                    typeId
                      ? t("contentTypes.entriesCaption", {
                          name: collection.name,
                        })
                      : t("lists.blogCaption")
                  }
                  columns={columns}
                  data={entries}
                  getRowId={(item) => item.id}
                  labels={labels}
                  loading={loading}
                  searchable
                />
              )}
              {entriesCursor ? (
                <Button
                  disabled={loading || busy}
                  onClick={() => void loadMoreEntries()}
                  type="button"
                  variant="outline"
                >
                  {t("lists.moreEntries")}
                </Button>
              ) : null}

              <Button
                disabled={loading || busy}
                onClick={() => void load()}
                type="button"
                variant="ghost"
              >
                <RefreshCwIcon aria-hidden="true" />
                {common("refresh")}
              </Button>
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>{t("blogNewEntry")}</CardTitle>
              <CardDescription>{t("blogNewEntryDescription")}</CardDescription>
            </CardHeader>
            <CardContent>
              <form
                className="space-y-4"
                onSubmit={(event) => {
                  void entryForm.handleSubmit(submitEntry)(event);
                }}
              >
                <FieldGroup>
                  <Field
                    data-invalid={Boolean(
                      entryForm.formState.errors.title?.message,
                    )}
                  >
                    <FieldLabel htmlFor="entry-title">
                      {t("blogEntryTitle")}
                    </FieldLabel>
                    <Input id="entry-title" {...entryForm.register("title")} />
                    <FieldError>
                      {entryForm.formState.errors.title?.message}
                    </FieldError>
                  </Field>
                  <Field
                    data-invalid={Boolean(
                      entryForm.formState.errors.slug?.message,
                    )}
                  >
                    <FieldLabel htmlFor="entry-slug">
                      {t("blogEntrySlug")}
                    </FieldLabel>
                    <Input
                      id="entry-slug"
                      {...entryForm.register("slug")}
                      onInput={() => setSlugEdited(true)}
                    />
                    <FieldError>
                      {entryForm.formState.errors.slug?.message}
                    </FieldError>
                  </Field>
                  <Field>
                    <FieldLabel htmlFor="entry-locale">
                      {t("blogEntryLocale")}
                    </FieldLabel>
                    <NativeSelect
                      id="entry-locale"
                      {...entryForm.register("locale")}
                    >
                      {entryLocales.map((item) => (
                        <option key={item.code} value={item.code}>
                          {item.name}
                        </option>
                      ))}
                    </NativeSelect>
                  </Field>
                </FieldGroup>
                <Button disabled={busy} type="submit">
                  <PlusIcon aria-hidden="true" />
                  {t("blogAddEntry")}
                </Button>
              </form>
            </CardContent>
          </Card>
        </div>
      )}

      {entry && !collection?.archived && (
        <EntryMetadata
          entry={entry}
          key={`metadata-${entry.id}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && !collection?.archived && (
        <EntryTags
          entry={entry}
          key={`tags-${entry.id}-${entry.tags.map((tag) => tag.slug).join(",")}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && !collection?.archived && (
        <EntrySchedule
          entry={entry}
          key={`schedule-${entry.id}-${entry.schedule_state}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && !collection?.archived && (
        <EntryTranslations
          entry={entry}
          key={`translations-${entry.id}`}
          onCreated={() => {
            if (collectionId) void loadEntries(collectionId);
          }}
        />
      )}

      {entry && !collection?.archived && (
        <EntryEditor
          entry={entry}
          key={entry.id}
          locked={collection?.automation_policy === "automated"}
          proposal={entry.draft_author === "automation"}
          onSaved={() => {
            if (collectionId) void loadEntries(collectionId);
          }}
        />
      )}
    </div>
  );
}

/** What the screen works on: the one type asked for, or — on the blog screen
 *  — every section that is switched on (a switched-off one takes no work). */
function shown(
  found: ContentCollection[],
  typeId: string | undefined,
): ContentCollection[] {
  return typeId
    ? found.filter((item) => item.id === typeId)
    : found.filter((item) => !item.archived);
}

/** Titles imply their address, and typing the same words twice is where a
 *  mismatch between the two creeps in. The suggestion stops as soon as the
 *  operator edits the address themselves — an address that keeps rewriting
 *  itself under an editor is worse than one they think about once. */
function useSlugSuggestion<TValues extends FieldValues>(
  form: UseFormReturn<TValues>,
  source: Path<TValues>,
  target: Path<TValues>,
  edited: boolean,
  fallback = "",
): void {
  const value = useWatch({ control: form.control, name: source });
  useEffect(() => {
    if (edited) return;
    const suggestion =
      slugFromTitle(typeof value === "string" ? value : "") || fallback;
    if (suggestion !== form.getValues(target)) {
      form.setValue(target, suggestion as PathValue<TValues, Path<TValues>>, {
        shouldValidate: false,
      });
    }
  }, [edited, fallback, form, target, value]);
}
