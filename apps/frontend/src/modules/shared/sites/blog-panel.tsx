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
import {
  Field,
  FieldError,
  FieldGroup,
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { AutomationPolicyField } from "./automation-policy";
import { EntryEditor } from "./entry-editor";
import { EntryMetadata } from "./entry-metadata";
import { EntrySchedule } from "./entry-schedule";
import { EntryTags } from "./entry-tags";
import { EntryTranslations } from "./entry-translations";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";
import { slugFromTitle } from "./slug";

type CollectionValues = { name: string; base_path: string };
type EntryValues = { title: string; slug: string; locale: string };

export function BlogPanel({ siteId }: { siteId: string }) {
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
      }),
    ),
    defaultValues: { name: "", base_path: "" },
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

  const [pathEdited, setPathEdited] = useState(false);
  const [slugEdited, setSlugEdited] = useState(false);
  useSlugSuggestion(collectionForm, "name", "base_path", pathEdited);
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
      const found = await listContentCollections(siteId);
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
  }, [loadEntries, siteId, t]);

  // The first load runs from the effect without setting `loading` up front: it
  // already starts true, and setting it again synchronously would queue a
  // cascading render.
  useEffect(() => {
    let mounted = true;
    void listContentCollections(siteId)
      .then(async (found) => {
        if (!mounted) return;
        setCollections(found);
        const next = found[0]?.id;
        setCollectionId(next);
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
  }, [loadEntries, siteId, t]);

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
      const input = {
        key: values.base_path,
        name: values.name,
        kind: "blog" as const,
        base_path: values.base_path,
      };
      const created = await createContentCollection(
        siteId,
        input,
        mutationKey(collectionReceipt, `collection-${siteId}`, input),
      );
      collectionForm.reset({ name: "", base_path: "" });
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
    {
      id: "state",
      accessorFn: stateLabel,
      header: t("lists.state"),
      cell: ({ row: { original: item } }) => (
        <Badge variant={item.state === "published" ? "default" : "secondary"}>
          {stateLabel(item)}
        </Badge>
      ),
    },
    {
      id: "actions",
      header: t("lists.actions"),
      meta: { actions: true },
      cell: ({ row: { original: item } }) => (
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

      {collections.length === 0 && !loading ? (
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
                  <Input
                    id="collection-path"
                    {...collectionForm.register("base_path")}
                    onInput={() => setPathEdited(true)}
                  />
                  <FieldError>
                    {collectionForm.formState.errors.base_path?.message}
                  </FieldError>
                </Field>
              </FieldGroup>
              <Button disabled={busy} type="submit">
                <PlusIcon aria-hidden="true" />
                {t("blogCreate")}
              </Button>
            </form>
          </CardContent>
        </Card>
      ) : null}

      {collection && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1.1fr)_minmax(20rem,0.9fr)]">
          <Card>
            <CardHeader>
              <CardTitle>{collection.name}</CardTitle>
              <CardDescription>
                {t("blogEntriesDescription", { path: collection.base_path })}
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              {collections.length > 1 && (
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

              {/* The menu a visitor sees comes from the last publication, so
                  the change lands when the site is published — the same rule
                  every other content change follows. */}
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

              {entries.length === 0 ? (
                <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">
                  {t("blogEmpty")}
                </p>
              ) : (
                <DataTable
                  caption={t("lists.blogCaption")}
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

      {entry && (
        <EntryMetadata
          entry={entry}
          key={`metadata-${entry.id}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && (
        <EntryTags
          entry={entry}
          key={`tags-${entry.id}-${entry.tags.map((tag) => tag.slug).join(",")}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && (
        <EntrySchedule
          entry={entry}
          key={`schedule-${entry.id}-${entry.schedule_state}`}
          onChanged={async () => {
            if (collectionId) await loadEntries(collectionId);
          }}
        />
      )}

      {entry && (
        <EntryTranslations
          entry={entry}
          key={`translations-${entry.id}`}
          onCreated={() => {
            if (collectionId) void loadEntries(collectionId);
          }}
        />
      )}

      {entry && (
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

/** Titles imply their address, and typing the same words twice is where a
 *  mismatch between the two creeps in. The suggestion stops as soon as the
 *  operator edits the address themselves — an address that keeps rewriting
 *  itself under an editor is worse than one they think about once. */
function useSlugSuggestion<TValues extends FieldValues>(
  form: UseFormReturn<TValues>,
  source: Path<TValues>,
  target: Path<TValues>,
  edited: boolean,
): void {
  const value = useWatch({ control: form.control, name: source });
  useEffect(() => {
    if (edited) return;
    const suggestion = slugFromTitle(typeof value === "string" ? value : "");
    if (suggestion !== form.getValues(target)) {
      form.setValue(target, suggestion as PathValue<TValues, Path<TValues>>, {
        shouldValidate: false,
      });
    }
  }, [edited, form, target, value]);
}
