"use client";

/** „Treści” (ADR-079 pkt 25): a site's content types on the panel's list
 *  standard (ADR-054, ADR-057) — the blog first, then whatever the company
 *  added beside it. Each row leads to the type's entries and its settings;
 *  switched-off types wait under the „Wyłączone” filter to be switched on
 *  or, when empty, removed. Whether one more type may be added is the
 *  server's word (`limit`), said here in the company's own terms. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";
import {
  ListIcon,
  PlusIcon,
  PowerIcon,
  PowerOffIcon,
  SettingsIcon,
  Trash2Icon,
} from "lucide-react";
import { z } from "zod";

import {
  ApiProblemError,
  createContentCollection,
  deleteContentType,
  listContentTypes,
  previewContentTypeDelete,
  previewContentTypeSwitchOff,
  switchOffContentType,
  switchOnContentType,
  type ContentCollection,
  type ContentSchemaType,
  type ContentSchemaTypeOption,
  type ContentTypeRemoval,
  type ContentTypeRow,
  type ContentTypes,
  type ContentTypesLimit,
  type ContentTypeSwitch,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  DataTableFilter,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import {
  Field,
  FieldDescription,
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
import { useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  SECTION_PATH,
  namedPaths,
  sectionPathErrors,
  siteHost,
} from "./collection-paths";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { refusedWith, sitesErrorMessage } from "./problem";
import { slugFromTitle } from "./slug";

type Translate = ReturnType<typeof useTranslations>;
type Show = "on" | "off";

/** Where a type's screens live; the site travels in the address (UX-086). */
export const contentTypeHref = (
  siteId: string,
  typeId: string,
  page: "" | "/settings" | "/categories" | "/tags" = "",
) => `/panel/sites/content/${typeId}${page}?site=${siteId}`;
export const contentTypesHref = (siteId: string) =>
  `/panel/sites/content?site=${siteId}`;

/** Why one more type is not allowed, in the company's terms — by the
 *  server's code, never by its Polish sentence. */
export function limitMessage(
  limit: Pick<ContentTypesLimit, "code" | "additional_max" | "message">,
  t: Translate,
): string {
  switch (limit.code) {
    case "quota_exceeded":
      return limit.additional_max === null
        ? t("contentTypes.limitQuotaNoNumber")
        : t("contentTypes.limitQuota", { max: limit.additional_max });
    case "plan_access_denied":
      return t("contentTypes.limitPlan");
    case "content_types_not_offered":
      return t("contentTypes.limitNotOffered");
    default:
      return limit.message;
  }
}

/** A choice of what a type's entries are, named in the panel's language. */
export function schemaTypeText(
  option: ContentSchemaTypeOption,
  locale: string,
  part: "title" | "hint",
): string {
  const words = option[part];
  return words[locale] ?? words.en ?? "";
}

export function ContentTypesPanel({
  siteId,
  reloads = 0,
}: {
  siteId: string;
  /** Bumped by the page's header when a type was added there. */
  reloads?: number;
}) {
  const t = useTranslations("Sites");
  const labels = useDataTableLabels();
  const [found, setFound] = useState<ContentTypes>();
  const [show, setShow] = useState<Show>("on");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState("");
  const [problem, setProblem] = useState<string>();
  const [switchingOff, setSwitchingOff] = useState<ContentCollection>();
  const [deleting, setDeleting] = useState<ContentCollection>();
  const [own, setOwn] = useState(0);

  useEffect(() => {
    let current = true;
    listContentTypes(siteId)
      .then((result) => {
        if (current) setFound(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
  }, [siteId, reloads, own, t]);

  const rows = (found?.types ?? []).filter(
    (row) => row.collection.archived === (show === "off"),
  );
  const offCount = (found?.types ?? []).filter(
    (row) => row.collection.archived,
  ).length;

  async function switchOn(collection: ContentCollection) {
    if (busy) return;
    setBusy(true);
    setProblem(undefined);
    setNotice("");
    try {
      await switchOnContentType(collection.id);
      setNotice(t("contentTypes.switchedOn", { name: collection.name }));
      setShow("on");
      setOwn((value) => value + 1);
    } catch (error) {
      setProblem(contentTypeProblem(error, t));
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnDef<ContentTypeRow, unknown>[] = [
    {
      id: "name",
      accessorFn: (row) => row.collection.name,
      header: t("contentTypes.colName"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) =>
        row.collection.archived ? (
          <p className="font-medium wrap-anywhere">{row.collection.name}</p>
        ) : (
          <Link
            className="font-medium underline-offset-4 wrap-anywhere hover:underline"
            href={contentTypeHref(siteId, row.collection.id)}
          >
            {row.collection.name}
          </Link>
        ),
    },
    {
      id: "address",
      accessorFn: (row) => Object.values(row.collection.paths)[0] ?? "",
      header: t("contentTypes.colAddress"),
      cell: ({ row: { original: row } }) => {
        const [first, ...others] = Object.values(row.collection.paths);
        return (
          <>
            <code className="text-sm wrap-anywhere">{first}</code>
            {others
              .filter((path) => path !== first)
              .map((path) => (
                <code
                  className="block text-xs text-muted-foreground wrap-anywhere"
                  key={path}
                >
                  {path}
                </code>
              ))}
          </>
        );
      },
    },
    {
      id: "entries",
      accessorKey: "entries",
      header: t("contentTypes.colEntries"),
      cell: ({ row: { original: row } }) => (
        <>
          <p>{t("contentTypes.entries", { count: row.entries })}</p>
          {row.entries > 0 ? (
            <p className="text-xs text-muted-foreground">
              {t("contentTypes.published", { count: row.published })}
            </p>
          ) : null}
        </>
      ),
    },
    {
      id: "locales",
      accessorFn: (row) => row.locales.join(", "),
      header: t("contentTypes.colLocales"),
      cell: ({ row: { original: row } }) =>
        row.locales.length
          ? row.locales.map((code) => code.toUpperCase()).join(", ")
          : t("contentTypes.noLocales"),
    },
    {
      id: "state",
      accessorFn: (row) => (row.collection.archived ? 1 : 0),
      header: t("contentTypes.colState"),
      cell: ({ row: { original: row } }) =>
        row.collection.archived ? (
          <Badge variant="neutral">{t("contentTypes.stateOff")}</Badge>
        ) : (
          <Badge variant="success">{t("contentTypes.stateOn")}</Badge>
        ),
    },
    {
      id: "actions",
      header: t("contentTypes.colActions"),
      meta: { actions: true },
      cell: ({ row: { original: row } }) => {
        const collection = row.collection;
        const items: RowAction[] = collection.archived
          ? [
              {
                label: t("contentTypes.switchOn"),
                icon: <PowerIcon aria-hidden="true" />,
                inline: true,
                main: true,
                onSelect: () => void switchOn(collection),
              },
            ]
          : [
              {
                label: t("contentTypes.open"),
                icon: <ListIcon aria-hidden="true" />,
                inline: true,
                main: true,
                link: <Link href={contentTypeHref(siteId, collection.id)} />,
              },
              {
                label: t("contentTypes.settings"),
                icon: <SettingsIcon aria-hidden="true" />,
                link: (
                  <Link
                    href={contentTypeHref(siteId, collection.id, "/settings")}
                  />
                ),
              },
              {
                label: t("contentTypes.switchOff"),
                icon: <PowerOffIcon aria-hidden="true" />,
                separated: true,
                onSelect: () => setSwitchingOff(collection),
              },
            ];
        // Only an empty type is removed; one with entries is switched off.
        if (row.entries === 0)
          items.push({
            label: t("contentTypes.delete"),
            icon: <Trash2Icon aria-hidden="true" />,
            destructive: true,
            separated: collection.archived,
            onSelect: () => setDeleting(collection),
          });
        return (
          <RowActions
            items={items}
            label={t("contentTypes.actionsFor", { name: collection.name })}
          />
        );
      },
    },
  ];

  const limit = found?.limit;
  return (
    <div className="space-y-3">
      {limit && !limit.allowed ? (
        <p className="rounded-lg border bg-muted/40 p-3 text-sm">
          {limitMessage(limit, t)}
        </p>
      ) : limit && limit.additional_max !== null ? (
        <p className="text-sm text-muted-foreground">
          {t("contentTypes.limitUsed", {
            used: limit.additional_used,
            max: limit.additional_max,
          })}
        </p>
      ) : null}
      {notice ? (
        <p aria-live="polite" className="text-sm text-muted-foreground">
          {notice}
        </p>
      ) : null}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DataTable
        activeFilters={show === "off" ? 1 : 0}
        caption={t(
          show === "on" ? "contentTypes.caption" : "contentTypes.captionOff",
        )}
        columns={columns}
        data={rows}
        filters={
          <DataTableFilter
            id="content-types-show"
            label={t("contentTypes.show")}
            onChange={(event) => {
              setShow(event.target.value as Show);
              setNotice("");
            }}
            value={show}
          >
            <option value="on">{t("contentTypes.showOn")}</option>
            <option value="off">
              {offCount
                ? `${t("contentTypes.showOff")} (${offCount})`
                : t("contentTypes.showOff")}
            </option>
          </DataTableFilter>
        }
        getRowId={(row) => row.collection.id}
        labels={{
          ...labels,
          empty: t(
            show === "on" ? "contentTypes.empty" : "contentTypes.emptyOff",
          ),
          loading: t("contentTypes.loading"),
        }}
        loading={found === undefined && !problem}
      />
      {switchingOff ? (
        <SwitchOffDialog
          collection={switchingOff}
          key={switchingOff.id}
          onClose={() => setSwitchingOff(undefined)}
          onDone={() => {
            setNotice(
              t("contentTypes.switchedOff", { name: switchingOff.name }),
            );
            setSwitchingOff(undefined);
            setOwn((value) => value + 1);
          }}
        />
      ) : null}
      {deleting ? (
        <DeleteTypeDialog
          collection={deleting}
          key={deleting.id}
          onClose={() => setDeleting(undefined)}
          onDeleted={() => {
            setNotice(t("contentTypes.deleted", { name: deleting.name }));
            setDeleting(undefined);
            setOwn((value) => value + 1);
          }}
        />
      ) : null}
    </div>
  );
}

/** Deleting a type: asked first what it would take with it. A type with
 *  entries is not deleted (switch it off); one with removed entries erases
 *  them for good, which takes its name typed out. */
function DeleteTypeDialog({
  collection,
  onClose,
  onDeleted,
}: {
  collection: ContentCollection;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [preview, setPreview] = useState<ContentTypeRemoval>();
  const [typed, setTyped] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let current = true;
    previewContentTypeDelete(collection.id)
      .then((result) => {
        if (current) setPreview(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(contentTypeProblem(error, t));
      });
    return () => {
      current = false;
    };
  }, [collection.id, t]);

  async function confirm() {
    if (!preview) return;
    setBusy(true);
    setProblem(undefined);
    try {
      // What is confirmed is what the dialog showed: the name typed and the
      // number of removed entries on the screen.
      if (preview.confirmation_required)
        await deleteContentType(collection.id, {
          name: typed,
          removedEntries: preview.removed_entries,
        });
      else await deleteContentType(collection.id);
      onDeleted();
    } catch (error) {
      setProblem(contentTypeProblem(error, t));
      if (refusedWith(error, "confirmation_stale")) {
        // Another entry was removed meanwhile: show what would go now and
        // ask for the name again.
        setTyped("");
        try {
          setPreview(await previewContentTypeDelete(collection.id));
        } catch {
          setPreview(undefined);
        }
      }
      setBusy(false);
    }
  }

  const blocked = preview !== undefined && preview.entries > 0;
  const erasing = preview?.confirmation_required === true;
  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
      open
    >
      <DialogContent
        className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
        closeLabel={common("close")}
      >
        <DialogHeader>
          <DialogTitle>
            {blocked
              ? t("contentTypes.deleteBlockedTitle", { name: collection.name })
              : t("contentTypes.deleteDialogTitle", { name: collection.name })}
          </DialogTitle>
          {preview && !blocked && !erasing ? (
            <DialogDescription>
              {t("contentTypes.deleteDialogBody")}
            </DialogDescription>
          ) : null}
        </DialogHeader>
        <div className="space-y-3 text-sm">
          {preview === undefined && !problem ? (
            <p className="text-muted-foreground">
              {t("contentTypes.deleteLoading")}
            </p>
          ) : null}
          {blocked ? (
            <p>
              {t("contentTypes.deleteBlockedBody", {
                entries: preview.entries,
              })}
            </p>
          ) : null}
          {preview && !blocked && preview.categories > 0 ? (
            <p>
              {t("contentTypes.deleteCategories", {
                categories: preview.categories,
              })}
            </p>
          ) : null}
          {preview && !blocked && erasing ? (
            <>
              <div
                className="space-y-2 rounded-lg border border-destructive/30 bg-destructive/5 p-3"
                role="alert"
              >
                <p>
                  {t("contentTypes.eraseWarning", {
                    name: preview.name,
                    removed_entries: preview.removed_entries,
                    removed_publications: preview.removed_publications,
                  })}
                </p>
                <p>
                  {t("contentTypes.erasePaths", {
                    paths: Object.values(preview.paths).join(", "),
                  })}
                </p>
              </div>
              <Field>
                <FieldLabel htmlFor="content-type-erase-name">
                  {t("contentTypes.eraseConfirmLabel", { name: preview.name })}
                </FieldLabel>
                <Input
                  autoComplete="off"
                  id="content-type-erase-name"
                  onChange={(event) => setTyped(event.target.value)}
                  value={typed}
                />
              </Field>
            </>
          ) : null}
          {problem ? (
            <p className="text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          {blocked ? (
            <Button onClick={onClose} variant="outline">
              {common("close")}
            </Button>
          ) : (
            <>
              <Button
                disabled={busy}
                onClick={onClose}
                type="button"
                variant="outline"
              >
                {common("cancel")}
              </Button>
              <Button
                disabled={
                  busy || !preview || (erasing && typed !== preview.name)
                }
                onClick={() => void confirm()}
                variant="destructive"
              >
                <Trash2Icon aria-hidden="true" />
                {erasing
                  ? t("contentTypes.eraseConfirm")
                  : t("contentTypes.deleteDialogConfirm")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const LIMIT_CODES = [
  "quota_exceeded",
  "plan_access_denied",
  "content_types_not_offered",
];

/** The platform's or the plan's refusal of one more type, in the company's
 *  terms; undefined for any other problem. */
function limitRefusal(error: unknown, t: Translate): string | undefined {
  if (!(error instanceof ApiProblemError)) return undefined;
  const code = error.problem.code ?? "";
  return LIMIT_CODES.includes(code)
    ? limitMessage({ code, additional_max: null, message: "" }, t)
    : undefined;
}

/** A refusal of a content type's operation, in the panel's language. */
export function contentTypeProblem(error: unknown, t: Translate): string {
  return limitRefusal(error, t) ?? sitesErrorMessage(error, t);
}

/** Switching a type off: what stops answering, what stays, and whether the
 *  plan would let the type back — asked of the server before the button. */
export function SwitchOffDialog({
  collection,
  onClose,
  onDone,
}: {
  collection: ContentCollection;
  onClose: () => void;
  onDone: (result: ContentTypeSwitch) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [preview, setPreview] = useState<ContentTypeSwitch>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let current = true;
    previewContentTypeSwitchOff(collection.id)
      .then((result) => {
        if (current) setPreview(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(contentTypeProblem(error, t));
      });
    return () => {
      current = false;
    };
  }, [collection.id, t]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      onDone(await switchOffContentType(collection.id));
    } catch (error) {
      setProblem(contentTypeProblem(error, t));
      setBusy(false);
    }
  }

  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
      }}
      open
    >
      <DialogContent closeLabel={common("close")}>
        <DialogHeader>
          <DialogTitle>
            {t("contentTypes.offDialogTitle", { name: collection.name })}
          </DialogTitle>
          <DialogDescription>
            {t("contentTypes.offDialogKept")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          {preview === undefined && !problem ? (
            <p className="text-muted-foreground">
              {t("contentTypes.offDialogLoading")}
            </p>
          ) : null}
          {preview ? (
            <>
              <div>
                <p>{t("contentTypes.offDialogPaths")}</p>
                <ul className="mt-1 list-disc pl-5">
                  {Object.entries(preview.paths).map(([locale, path]) => (
                    <li key={locale}>
                      <code className="wrap-anywhere">{path}</code>
                    </li>
                  ))}
                </ul>
              </div>
              <p>
                {t("contentTypes.offDialogPublished", {
                  count: preview.published,
                })}
              </p>
              <p>{t("contentTypes.offDialogRest")}</p>
              {preview.scheduled > 0 ? (
                <p>
                  {t("contentTypes.offDialogScheduled", {
                    count: preview.scheduled,
                  })}
                </p>
              ) : null}
              {!preview.restorable ? (
                <p className="rounded-lg border border-destructive/30 bg-destructive/5 p-3">
                  {t("contentTypes.offDialogNotRestorable")}{" "}
                  {limitMessage(
                    {
                      code: preview.restore_problem_code,
                      additional_max: null,
                      message: preview.restore_problem,
                    },
                    t,
                  )}
                </p>
              ) : null}
            </>
          ) : null}
          {problem ? (
            <p className="text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
        </div>
        <DialogFooter>
          <Button disabled={busy} onClick={onClose} variant="outline">
            {common("cancel")}
          </Button>
          <Button
            disabled={busy || preview === undefined}
            onClick={() => void confirm()}
            variant="destructive"
          >
            <PowerOffIcon aria-hidden="true" />
            {t("contentTypes.offDialogConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

type CreateValues = {
  name: string;
  base_path: string;
  locale_paths: Record<string, string>;
  schema_type: ContentSchemaType;
  in_site_feed: boolean;
};

/** „Nowy typ treści”, the page's own action: a name, an address the name
 *  suggests, the address in the company's other languages, and the two
 *  things a company chooses about what the type is — what its entries are
 *  and whether they join the RSS feed. Where the platform or the plan allows
 *  no further type, it says so instead of offering a form. */
export function CreateContentTypeDialog({
  siteId,
  address,
  defaultLocale,
  onCreated,
}: {
  siteId: string;
  /** The site's public address, before the type's own part of it. */
  address?: string | null;
  defaultLocale?: string;
  onCreated: (created: ContentCollection) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const locale = useLocale();
  const [open, setOpen] = useState(false);
  const [offer, setOffer] = useState<ContentTypes>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [pathEdited, setPathEdited] = useState(false);
  const [feedEdited, setFeedEdited] = useState(false);
  // The address typed only redirects to another type today: asked to
  // confirm before it is taken.
  const [former, setFormer] = useState(false);
  const [takeOver, setTakeOver] = useState(false);
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  const companyLocales = useCompanyLocales(["pl", "en"]);
  const otherLocales = defaultLocale
    ? companyLocales.filter((item) => item.code !== defaultLocale)
    : [];

  const form = useForm<CreateValues>({
    resolver: zodResolver(
      z.object({
        name: z.string().trim().min(2, t("required")).max(160),
        base_path: z.string().regex(SECTION_PATH, t("invalidSlug")),
        locale_paths: z.record(
          z.string(),
          z
            .string()
            .refine(
              (value) => !value.trim() || SECTION_PATH.test(value.trim()),
              t("invalidSlug"),
            ),
        ),
        schema_type: z.enum([
          "BlogPosting",
          "NewsArticle",
          "Article",
          "WebPage",
        ]),
        in_site_feed: z.boolean(),
      }),
    ),
    defaultValues: {
      name: "",
      base_path: "",
      locale_paths: {},
      schema_type: "BlogPosting",
      in_site_feed: true,
    },
  });
  const name = useWatch({ control: form.control, name: "name" });
  const basePath = useWatch({ control: form.control, name: "base_path" });
  const schemaType = useWatch({ control: form.control, name: "schema_type" });

  // The address follows the name until somebody types an address.
  useEffect(() => {
    if (pathEdited) return;
    const suggestion = slugFromTitle(name ?? "");
    if (suggestion !== form.getValues("base_path"))
      form.setValue("base_path", suggestion);
  }, [form, name, pathEdited]);

  const options = offer?.schema_types ?? [];
  const chosen = options.find((option) => option.schema_type === schemaType);
  // The feed follows the kind of content until somebody decides otherwise.
  useEffect(() => {
    if (feedEdited || !chosen) return;
    form.setValue("in_site_feed", chosen.in_site_feed);
  }, [chosen, feedEdited, form]);

  const load = useCallback(() => {
    setOffer(undefined);
    setProblem(undefined);
    listContentTypes(siteId)
      .then(setOffer)
      .catch((error: unknown) => setProblem(sitesErrorMessage(error, t)));
  }, [siteId, t]);

  const submit: SubmitHandler<CreateValues> = async (values) => {
    setBusy(true);
    setProblem(undefined);
    const named = namedPaths(values.locale_paths);
    const input = {
      key: values.base_path,
      name: values.name.trim(),
      kind: "blog" as const,
      base_path: values.base_path,
      ...(Object.keys(named).length > 0 ? { locale_paths: named } : {}),
      schema_type: values.schema_type,
      in_site_feed: values.in_site_feed,
      // Sent only once the person ticked it, having read which redirect
      // stops (ADR-079 pkt 14).
      ...(takeOver ? { take_over_former: true } : {}),
    };
    try {
      const created = await createContentCollection(
        siteId,
        input,
        mutationKey(receipt, `content-type-${siteId}`, input),
      );
      setOpen(false);
      form.reset();
      setPathEdited(false);
      setFeedEdited(false);
      setFormer(false);
      setTakeOver(false);
      onCreated(created);
    } catch (error) {
      // A name that only redirects to another type today: the server names
      // the address and the type; the person confirms below and saves again.
      setFormer(
        error instanceof ApiProblemError &&
          (error.problem.errors ?? []).some(
            (item) => item.code === "section_path_former",
          ),
      );
      // The plan's or the platform's word is about the type, not about its
      // address; a name the server refuses is said at its field.
      const limited = limitRefusal(error, t);
      const refused = limited
        ? []
        : Object.entries(sectionPathErrors(error, t));
      if (limited) load();
      else if (refused.length === 0) setProblem(sitesErrorMessage(error, t));
      for (const [field, message] of refused)
        form.setError(field as "base_path" | `locale_paths.${string}`, {
          message,
        });
    } finally {
      setBusy(false);
    }
  };

  const errors = form.formState.errors;
  const limit = offer?.limit;
  return (
    <>
      <Button
        onClick={() => {
          setOpen(true);
          load();
        }}
      >
        <PlusIcon aria-hidden="true" />
        {t("contentTypes.add")}
      </Button>
      {open ? (
        <Dialog
          onOpenChange={(next) => {
            if (!next && !busy) setOpen(false);
          }}
          open
        >
          {/* Taller than a laptop's or a phone's screen once the company has
              three languages: the dialog scrolls instead of losing its buttons. */}
          <DialogContent
            className="max-h-[calc(100dvh-2rem)] overflow-y-auto"
            closeLabel={common("close")}
          >
            <DialogHeader>
              <DialogTitle>{t("contentTypes.createTitle")}</DialogTitle>
              <DialogDescription>
                {t("contentTypes.createDescription")}
              </DialogDescription>
            </DialogHeader>
            {offer === undefined && !problem ? (
              <p className="text-sm text-muted-foreground">
                {t("contentTypes.loading")}
              </p>
            ) : null}
            {limit && !limit.allowed ? (
              <>
                <p className="rounded-lg border bg-muted/40 p-3 text-sm">
                  {limitMessage(limit, t)}
                </p>
                <DialogFooter>
                  <Button onClick={() => setOpen(false)} variant="outline">
                    {common("close")}
                  </Button>
                </DialogFooter>
              </>
            ) : null}
            {limit?.allowed ? (
              <form
                className="space-y-4"
                noValidate
                onSubmit={(event) => {
                  void form.handleSubmit(submit)(event);
                }}
              >
                <FieldGroup>
                  <Field data-invalid={Boolean(errors.name?.message)}>
                    <FieldLabel htmlFor="content-type-name">
                      {t("contentTypes.name")}
                    </FieldLabel>
                    <Input
                      aria-describedby="content-type-name-hint"
                      id="content-type-name"
                      placeholder={t("contentTypes.nameExample")}
                      {...form.register("name")}
                    />
                    <FieldDescription id="content-type-name-hint">
                      {t("contentTypes.nameHint")}
                    </FieldDescription>
                    <FieldError>{errors.name?.message}</FieldError>
                  </Field>
                  <Field data-invalid={Boolean(errors.base_path?.message)}>
                    <FieldLabel htmlFor="content-type-path">
                      {t("contentTypes.address")}
                    </FieldLabel>
                    <InputGroup>
                      <InputGroupAddon>
                        <InputGroupText className="max-w-48 truncate">
                          {`${siteHost(address)}/`}
                        </InputGroupText>
                      </InputGroupAddon>
                      <InputGroupInput
                        id="content-type-path"
                        {...form.register("base_path")}
                        onInput={() => setPathEdited(true)}
                      />
                      <InputGroupAddon align="inline-end">
                        <InputGroupText>/</InputGroupText>
                      </InputGroupAddon>
                    </InputGroup>
                    <FieldError>{errors.base_path?.message}</FieldError>
                  </Field>
                  {former ? (
                    <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                      <input
                        checked={takeOver}
                        className="mt-1"
                        onChange={(event) => setTakeOver(event.target.checked)}
                        type="checkbox"
                      />
                      <span>{t("blogPathsTakeOverConfirm")}</span>
                    </label>
                  ) : null}
                  {otherLocales.length > 0 ? (
                    <fieldset className="space-y-3">
                      <legend className="text-sm font-medium">
                        {t("contentTypes.addressOther")}
                      </legend>
                      <p className="text-sm text-muted-foreground">
                        {t("contentTypes.addressOtherHint")}
                      </p>
                      {otherLocales.map((item) => (
                        <Field
                          data-invalid={Boolean(
                            errors.locale_paths?.[item.code],
                          )}
                          key={item.code}
                        >
                          <FieldLabel
                            htmlFor={`content-type-path-${item.code}`}
                          >
                            {t("contentTypes.addressLocale", {
                              language: item.name,
                            })}
                          </FieldLabel>
                          <InputGroup>
                            <InputGroupAddon>
                              <InputGroupText className="gap-0">
                                <span className="max-w-36 truncate">
                                  {siteHost(address)}
                                </span>
                                <span>{`/${item.code}/`}</span>
                              </InputGroupText>
                            </InputGroupAddon>
                            <InputGroupInput
                              id={`content-type-path-${item.code}`}
                              placeholder={basePath}
                              {...form.register(`locale_paths.${item.code}`)}
                            />
                            <InputGroupAddon align="inline-end">
                              <InputGroupText>/</InputGroupText>
                            </InputGroupAddon>
                          </InputGroup>
                          <FieldError>
                            {errors.locale_paths?.[item.code]?.message}
                          </FieldError>
                        </Field>
                      ))}
                    </fieldset>
                  ) : null}
                  <Field>
                    <FieldLabel htmlFor="content-type-kind">
                      {t("contentTypes.kind")}
                    </FieldLabel>
                    <NativeSelect
                      aria-describedby="content-type-kind-hint"
                      id="content-type-kind"
                      {...form.register("schema_type")}
                    >
                      {options.map((option) => (
                        <option
                          key={option.schema_type}
                          value={option.schema_type}
                        >
                          {schemaTypeText(option, locale, "title")}
                        </option>
                      ))}
                    </NativeSelect>
                    <FieldDescription id="content-type-kind-hint">
                      {chosen ? schemaTypeText(chosen, locale, "hint") : ""}{" "}
                      {t("contentTypes.kindHint")}
                    </FieldDescription>
                  </Field>
                  <label className="flex items-start gap-2 rounded-lg border p-3 text-sm">
                    <input
                      className="mt-1"
                      type="checkbox"
                      {...form.register("in_site_feed")}
                      onInput={() => setFeedEdited(true)}
                    />
                    <span>
                      <span className="font-medium">
                        {t("contentTypes.feed")}
                      </span>
                      <span className="block text-muted-foreground">
                        {t("contentTypes.feedHint")}
                      </span>
                    </span>
                  </label>
                </FieldGroup>
                {problem ? (
                  <p className="text-sm text-destructive" role="alert">
                    {problem}
                  </p>
                ) : null}
                <DialogFooter>
                  <Button
                    disabled={busy}
                    onClick={() => setOpen(false)}
                    type="button"
                    variant="outline"
                  >
                    {common("cancel")}
                  </Button>
                  <Button disabled={busy} type="submit">
                    <PlusIcon aria-hidden="true" />
                    {t("contentTypes.create")}
                  </Button>
                </DialogFooter>
              </form>
            ) : null}
            {problem && !limit?.allowed ? (
              <p className="text-sm text-destructive" role="alert">
                {problem}
              </p>
            ) : null}
          </DialogContent>
        </Dialog>
      ) : null}
    </>
  );
}
