"use client";

/** A content type's categories, or the site's tags as that type shows them
 *  (CT2): one list for both on the panel's list standard (ADR-054, ADR-057).
 *  A name or a place in the tree is the site's at once; an address that
 *  visitors could already open moves only with a stated reason, and the old
 *  one redirects. What cannot be removed says why in the company's terms —
 *  the server's counts, never its sentence. */

import { useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import {
  ArrowDownIcon,
  ArrowUpIcon,
  LinkIcon,
  PencilIcon,
  PlusIcon,
  Trash2Icon,
} from "lucide-react";
import { z } from "zod";

import {
  createTerm,
  deleteTerm,
  listContentTypes,
  listTerms,
  previewTermAddress,
  previewTermRemoval,
  previewTermUpdate,
  setTermAddress,
  setTermNames,
  updateTerm,
  type ContentCollection,
  type Term,
  type TermChange,
  type TermKind,
  type TermList,
  type TermRemoval,
  type TermUpdateInput,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
  type RowAction,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogContent,
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
import { nativeName, useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { SECTION_PATH, siteHost } from "./collection-paths";
import { contentTypesHref } from "./content-types-panel";
import { sitesErrorMessage } from "./problem";

/** A language by the name the company knows it under. */
export function useLanguageName(): (code: string) => string {
  const locales = useCompanyLocales(["pl", "en"]);
  return (code) =>
    locales.find((item) => item.code === code)?.name ?? nativeName(code);
}

/** A tree level in a select's option: spaces, since an option has no padding. */
const indent = (depth: number) =>
  String.fromCharCode(160).repeat(Math.max(0, depth - 1) * 3);

/** The term and everything under it, in the list's tree order. */
function subtreeIds(terms: Term[], id: string): Set<string> {
  const ids = new Set([id]);
  for (const term of terms)
    if (term.parent_id && ids.has(term.parent_id)) ids.add(term.id);
  return ids;
}

function PanelDialog({
  title,
  onClose,
  busy = false,
  children,
}: {
  title: string;
  onClose: () => void;
  busy?: boolean;
  children: React.ReactNode;
}) {
  const common = useTranslations("Common");
  return (
    <Dialog
      onOpenChange={(next) => {
        if (!next && !busy) onClose();
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
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        {children}
      </DialogContent>
    </Dialog>
  );
}

export function TermListPanel({
  siteId,
  typeId,
  kind,
  address,
  reloads = 0,
  onLoaded,
}: {
  siteId: string;
  /** The content type whose categories, or whose view of the tags, this is. */
  typeId: string;
  kind: TermKind;
  /** The site's public address, before an archive's own path. */
  address?: string | null;
  /** Bumped by the page's header when a category was added there. */
  reloads?: number;
  /** The type shown, for the page's title. */
  onLoaded?: (collection: ContentCollection) => void;
}) {
  const t = useTranslations("Sites");
  const labels = useDataTableLabels();
  const languageName = useLanguageName();
  const [list, setList] = useState<TermList>();
  const [collection, setCollection] = useState<ContentCollection | null>();
  const [problem, setProblem] = useState<string>();
  const [notes, setNotes] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Term>();
  const [addressing, setAddressing] = useState<Term>();
  const [removing, setRemoving] = useState<Term>();
  const [own, setOwn] = useState(0);
  const reload = () => setOwn((value) => value + 1);

  useEffect(() => {
    let current = true;
    Promise.all([listContentTypes(siteId), listTerms(typeId, kind)])
      .then(([types, terms]) => {
        if (!current) return;
        const found =
          types.types.find((row) => row.collection.id === typeId)?.collection ??
          null;
        setCollection(found);
        setList(terms);
        if (found) onLoaded?.(found);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
    // `onLoaded` is the page's own setter: asking again when it changes
    // identity would load the list on every render of the page.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [siteId, typeId, kind, reloads, own, t]);

  if (collection === null)
    return (
      <div className="space-y-3 text-sm">
        <p role="alert">{t("contentTypes.notFound")}</p>
        <Link className="underline" href={contentTypesHref(siteId)}>
          {t("contentTypes.backToList")}
        </Link>
      </div>
    );

  const terms = list?.terms ?? [];
  const defaultLocale = list?.default_locale ?? "";

  /** What moved, said once the change is saved — a note that stays on the
   *  page, since the old address is what somebody may have to pass on. */
  function noteMoved(changes: TermChange[]) {
    const seen = new Set<string>();
    const lines: string[] = [];
    for (const change of changes)
      for (const item of change.moved) {
        const key = `${item.locale}:${item.from_path}`;
        if (seen.has(key)) continue;
        seen.add(key);
        lines.push(
          t(`terms.${kind}.moved`, {
            language: languageName(item.locale),
            from: item.from_path,
            to: item.to_path,
          }),
        );
      }
    setNotes(lines);
  }

  async function move(term: Term, position: number) {
    if (busy) return;
    setBusy(true);
    setProblem(undefined);
    setNotes([]);
    try {
      await updateTerm(typeId, term.id, { position });
      reload();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  const columns: ColumnDef<Term, unknown>[] = [
    {
      id: "name",
      accessorFn: (term) => term.name,
      header: t("terms.name"),
      enableSorting: false,
      meta: { primary: true },
      cell: ({ row: { original: term } }) => (
        <p
          className="font-medium wrap-anywhere"
          style={{ paddingInlineStart: `${(term.depth - 1) * 1.25}rem` }}
        >
          {term.name}
        </p>
      ),
    },
    {
      id: "address",
      accessorFn: (term) => term.paths[defaultLocale] ?? "",
      header: t("contentTypes.colAddress"),
      enableSorting: false,
      cell: ({ row: { original: term } }) => {
        const path = term.paths[defaultLocale] ?? "";
        const live = (term.published[defaultLocale] ?? 0) > 0;
        if (live && address)
          return (
            <a
              className="text-sm underline-offset-4 wrap-anywhere hover:underline"
              href={`${address}${path}`}
              rel="noreferrer"
              target="_blank"
            >
              <code>{path}</code>
            </a>
          );
        return (
          <>
            <code className="text-sm text-muted-foreground wrap-anywhere">
              {path}
            </code>
            {live ? null : (
              <span className="block text-xs text-muted-foreground">
                {t("terms.noEntriesYet")}
              </span>
            )}
          </>
        );
      },
    },
    {
      id: "entries",
      accessorKey: "entries",
      header: t("contentTypes.colEntries"),
      enableSorting: false,
      cell: ({ row: { original: term } }) => {
        const onSite = Object.values(term.published).reduce(
          (sum, count) => sum + count,
          0,
        );
        return (
          <>
            <p>{t("contentTypes.entries", { count: term.entries })}</p>
            {onSite > 0 ? (
              <p className="text-xs text-muted-foreground">
                {t("contentTypes.published", { count: onSite })}
              </p>
            ) : null}
            {kind === "tags" && term.entries_elsewhere > 0 ? (
              <p className="text-xs text-muted-foreground">
                {t("terms.elsewhere", { count: term.entries_elsewhere })}
              </p>
            ) : null}
          </>
        );
      },
    },
    {
      id: "actions",
      header: t("contentTypes.colActions"),
      meta: { actions: true },
      cell: ({ row: { original: term } }) => {
        const siblings = terms
          .filter((other) => other.parent_id === term.parent_id)
          .sort((a, b) => a.position - b.position);
        const at = siblings.findIndex((other) => other.id === term.id);
        const before = at > 0 ? siblings[at - 1] : undefined;
        const after = at >= 0 ? siblings[at + 1] : undefined;
        const items: RowAction[] = [
          {
            label: t("terms.edit"),
            icon: <PencilIcon aria-hidden="true" />,
            inline: true,
            main: true,
            onSelect: () => setEditing(term),
          },
          ...(kind === "categories" && before
            ? [
                {
                  label: t("terms.moveUp"),
                  icon: <ArrowUpIcon aria-hidden="true" />,
                  onSelect: () => void move(term, before.position),
                },
              ]
            : []),
          ...(kind === "categories" && after
            ? [
                {
                  label: t("terms.moveDown"),
                  icon: <ArrowDownIcon aria-hidden="true" />,
                  onSelect: () => void move(term, after.position),
                },
              ]
            : []),
          {
            label: t("terms.changeAddress"),
            icon: <LinkIcon aria-hidden="true" />,
            onSelect: () => setAddressing(term),
          },
          {
            label: t("terms.remove"),
            icon: <Trash2Icon aria-hidden="true" />,
            destructive: true,
            separated: true,
            onSelect: () => setRemoving(term),
          },
        ];
        return (
          <RowActions
            items={items}
            label={t("terms.actionsFor", { name: term.name })}
          />
        );
      },
    },
  ];

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted-foreground">
        {t(`terms.${kind}.intro`)}
      </p>
      {notes.length > 0 ? (
        <div
          aria-live="polite"
          className="space-y-1 rounded-lg border bg-muted/40 p-3 text-sm"
          role="status"
        >
          {notes.map((note) => (
            <p key={note}>{note}</p>
          ))}
        </div>
      ) : null}
      {problem ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}
      <DataTable
        caption={t(`terms.${kind}.caption`)}
        columns={columns}
        data={terms}
        getRowId={(term) => term.id}
        labels={{
          ...labels,
          empty: t(`terms.${kind}.empty`),
          loading: t("terms.loading"),
        }}
        loading={list === undefined && !problem}
      />
      {editing && list ? (
        <EditTermDialog
          key={editing.id}
          kind={kind}
          list={list}
          onClose={() => setEditing(undefined)}
          onSaved={(changes) => {
            setEditing(undefined);
            noteMoved(changes);
            reload();
          }}
          term={editing}
          typeId={typeId}
        />
      ) : null}
      {addressing && list ? (
        <TermAddressDialog
          address={address}
          key={addressing.id}
          kind={kind}
          list={list}
          onClose={() => setAddressing(undefined)}
          onSaved={(change) => {
            setAddressing(undefined);
            noteMoved([change]);
            reload();
          }}
          term={addressing}
          typeId={typeId}
        />
      ) : null}
      {removing ? (
        <RemoveTermDialog
          key={removing.id}
          kind={kind}
          onClose={() => setRemoving(undefined)}
          onRemoved={() => {
            setRemoving(undefined);
            setNotes([]);
            reload();
          }}
          term={removing}
          typeId={typeId}
        />
      ) : null}
    </div>
  );
}

/** The categories a category may sit under: any with room below it. */
function ParentSelect({
  id,
  terms,
  maxDepth,
  register,
}: {
  id: string;
  terms: Term[];
  maxDepth: number;
  register: React.ComponentProps<typeof NativeSelect>;
}) {
  const t = useTranslations("Sites");
  return (
    <Field>
      <FieldLabel htmlFor={id}>{t("terms.parent")}</FieldLabel>
      <NativeSelect id={id} {...register}>
        <option value="">{t("terms.parentNone")}</option>
        {terms
          .filter((term) => term.depth < maxDepth)
          .map((term) => (
            <option key={term.id} value={term.id}>
              {`${indent(term.depth)}${term.name}`}
            </option>
          ))}
      </NativeSelect>
    </Field>
  );
}

const NAME_MAX = 120;

type CreateValues = { name: string; parent_id: string };

/** „Nowa kategoria”, the page's own action. */
export function CreateCategoryDialog({
  typeId,
  onCreated,
}: {
  typeId: string;
  onCreated: () => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [list, setList] = useState<TermList>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const form = useForm<CreateValues>({
    resolver: zodResolver(
      z.object({
        name: z.string().trim().min(1, t("required")).max(NAME_MAX),
        parent_id: z.string(),
      }),
    ),
    defaultValues: { name: "", parent_id: "" },
  });
  const errors = form.formState.errors;

  function show() {
    setOpen(true);
    setList(undefined);
    setProblem(undefined);
    form.reset();
    listTerms(typeId, "categories")
      .then(setList)
      .catch((error: unknown) => setProblem(sitesErrorMessage(error, t)));
  }

  async function submit(values: CreateValues) {
    setBusy(true);
    setProblem(undefined);
    try {
      await createTerm(typeId, {
        kind: "categories",
        name: values.name.trim(),
        ...(values.parent_id ? { parent_id: values.parent_id } : {}),
      });
      setOpen(false);
      onCreated();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <Button onClick={show}>
        <PlusIcon aria-hidden="true" />
        {t("terms.categories.add")}
      </Button>
      {open ? (
        <PanelDialog
          busy={busy}
          onClose={() => setOpen(false)}
          title={t("terms.categories.add")}
        >
          <form
            className="space-y-4"
            noValidate
            onSubmit={(event) => {
              void form.handleSubmit(submit)(event);
            }}
          >
            <FieldGroup>
              <Field data-invalid={Boolean(errors.name?.message)}>
                <FieldLabel htmlFor="term-create-name">
                  {t("terms.name")}
                </FieldLabel>
                <Input id="term-create-name" {...form.register("name")} />
                <FieldError>{errors.name?.message}</FieldError>
              </Field>
              <ParentSelect
                id="term-create-parent"
                maxDepth={list?.max_depth ?? 0}
                register={form.register("parent_id")}
                terms={list?.terms ?? []}
              />
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
                {t("terms.categories.add")}
              </Button>
            </DialogFooter>
          </form>
        </PanelDialog>
      ) : null}
    </>
  );
}

type EditValues = {
  name: string;
  parent_id: string;
  names: Record<string, string>;
};

/** Name, place in the tree and the name in each other language of the site. */
function EditTermDialog({
  typeId,
  kind,
  list,
  term,
  onClose,
  onSaved,
}: {
  typeId: string;
  kind: TermKind;
  list: TermList;
  term: Term;
  onClose: () => void;
  onSaved: (changes: TermChange[]) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const languageName = useLanguageName();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  // Published entries the new place brings to the pages above.
  const [above, setAbove] = useState(0);
  const others = list.locales.filter((code) => code !== list.default_locale);
  const own = subtreeIds(list.terms, term.id);
  const parentOf = term.parent_id ?? "";
  const form = useForm<EditValues>({
    resolver: zodResolver(
      z.object({
        name: z.string().trim().min(1, t("required")).max(NAME_MAX),
        parent_id: z.string(),
        names: z.record(z.string(), z.string().max(NAME_MAX)),
      }),
    ),
    defaultValues: {
      name: term.name,
      parent_id: parentOf,
      names: Object.fromEntries(
        others.map((code) => [code, term.names[code]?.text ?? ""]),
      ),
    },
  });
  const errors = form.formState.errors;
  const parent = useWatch({ control: form.control, name: "parent_id" });

  // Moving brings the term's published entries to other pages: asked of the
  // server, so the number is its own.
  useEffect(() => {
    if (kind !== "categories" || parent === parentOf) return;
    let current = true;
    previewTermUpdate(typeId, term.id, { parent_id: parent || null })
      .then((change) => {
        if (current) setAbove(change.published);
      })
      .catch(() => {
        if (current) setAbove(0);
      });
    return () => {
      current = false;
    };
  }, [kind, parent, parentOf, term.id, typeId]);

  async function submit(values: EditValues) {
    setBusy(true);
    setProblem(undefined);
    try {
      const changes: TermChange[] = [];
      const patch: TermUpdateInput = {};
      if (values.name.trim() !== term.name) patch.name = values.name.trim();
      if (kind === "categories" && values.parent_id !== parentOf)
        patch.parent_id = values.parent_id || null;
      if (Object.keys(patch).length > 0)
        changes.push(await updateTerm(typeId, term.id, patch));
      const names: Record<string, string> = {};
      for (const code of others) {
        const next = (values.names[code] ?? "").trim();
        if (next !== (term.names[code]?.text ?? "")) names[code] = next;
      }
      if (Object.keys(names).length > 0)
        changes.push(await setTermNames(typeId, term.id, names));
      onSaved(changes);
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
      setBusy(false);
    }
  }

  return (
    <PanelDialog
      busy={busy}
      onClose={onClose}
      title={t(`terms.${kind}.editTitle`, { name: term.name })}
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          void form.handleSubmit(submit)(event);
        }}
      >
        <FieldGroup>
          <Field data-invalid={Boolean(errors.name?.message)}>
            <FieldLabel htmlFor="term-edit-name">{t("terms.name")}</FieldLabel>
            <Input id="term-edit-name" {...form.register("name")} />
            <FieldError>{errors.name?.message}</FieldError>
          </Field>
          {kind === "categories" ? (
            <ParentSelect
              id="term-edit-parent"
              maxDepth={list.max_depth}
              register={form.register("parent_id")}
              terms={list.terms.filter((other) => !own.has(other.id))}
            />
          ) : null}
          {kind === "categories" && above > 0 && parent !== parentOf ? (
            <p className="text-sm text-muted-foreground" role="status">
              {t("terms.appearsAbove", { count: above })}
            </p>
          ) : null}
          {others.map((code) => {
            const name = term.names[code];
            return (
              <Field
                data-invalid={Boolean(errors.names?.[code]?.message)}
                key={code}
              >
                <FieldLabel htmlFor={`term-edit-name-${code}`}>
                  {t("terms.nameIn", { language: languageName(code) })}
                </FieldLabel>
                <Input
                  aria-describedby={`term-edit-name-${code}-hint`}
                  id={`term-edit-name-${code}`}
                  {...form.register(`names.${code}`)}
                />
                <FieldDescription id={`term-edit-name-${code}-hint`}>
                  {name?.origin === "ai" ? t("terms.hintAi") : null}
                  {name?.origin === "ai" && name.state === "stale" ? " " : null}
                  {name?.state === "stale" ? t("terms.hintStale") : null}
                </FieldDescription>
                <FieldError>{errors.names?.[code]?.message}</FieldError>
              </Field>
            );
          })}
        </FieldGroup>
        <p className="text-sm text-muted-foreground">{t("terms.editNote")}</p>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <Button
            disabled={busy}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            {common("cancel")}
          </Button>
          <Button disabled={busy} type="submit">
            {common("save")}
          </Button>
        </DialogFooter>
      </form>
    </PanelDialog>
  );
}

type AddressValues = { locale: string; slug: string; reason: string };

/** Moving one language's address of a term: the server says first which
 *  archives stop answering and which former redirects stop working. */
function TermAddressDialog({
  typeId,
  kind,
  list,
  term,
  address,
  onClose,
  onSaved,
}: {
  typeId: string;
  kind: TermKind;
  list: TermList;
  term: Term;
  address?: string | null;
  onClose: () => void;
  onSaved: (change: TermChange) => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const languageName = useLanguageName();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [preview, setPreview] = useState<TermChange>();
  const [checking, setChecking] = useState(false);
  const [taken, setTaken] = useState<Set<string>>(new Set());
  const [takeOverMissing, setTakeOverMissing] = useState(false);
  const asked = useRef(0);
  const form = useForm<AddressValues>({
    resolver: zodResolver(
      z.object({
        locale: z.string(),
        slug: z.string().regex(SECTION_PATH, t("invalidSlug")).max(80),
        reason: z.string().max(500),
      }),
    ),
    defaultValues: {
      locale: list.default_locale,
      slug: term.slugs[list.default_locale] ?? "",
      reason: "",
    },
  });
  const errors = form.formState.errors;
  const locale = useWatch({ control: form.control, name: "locale" });
  const slug = useWatch({ control: form.control, name: "slug" });
  const current = term.slugs[locale] ?? "";
  const valid = SECTION_PATH.test(slug) && slug !== current;

  // The preview follows the typing, a moment after it stops.
  useEffect(() => {
    asked.current += 1;
    const mine = asked.current;
    setPreview(undefined);
    setTaken(new Set());
    setTakeOverMissing(false);
    if (!valid) {
      setChecking(false);
      return;
    }
    setChecking(true);
    const timer = setTimeout(() => {
      previewTermAddress(typeId, term.id, {
        locale,
        slug,
        reason: "",
        take_over_former: false,
      })
        .then((change) => {
          if (asked.current === mine) {
            setPreview(change);
            setProblem(undefined);
          }
        })
        .catch((error: unknown) => {
          if (asked.current === mine) setProblem(sitesErrorMessage(error, t));
        })
        .finally(() => {
          if (asked.current === mine) setChecking(false);
        });
    }, 250);
    return () => clearTimeout(timer);
  }, [valid, locale, slug, term.id, typeId, t]);

  // The path as it will be: the archive's path with the term's own part
  // replaced by what is typed.
  const path = term.paths[locale] ?? "";
  const lead = path.replace(/[^/]+\/?$/, "");
  const moved = preview?.moved ?? [];
  const takesOver = preview?.takes_over ?? [];

  async function submit(values: AddressValues) {
    if (!preview) return;
    form.clearErrors("reason");
    setTakeOverMissing(false);
    if (moved.length > 0 && !values.reason.trim()) {
      form.setError("reason", { message: t("terms.reasonRequired") });
      return;
    }
    if (takesOver.some((item) => !taken.has(item.slug))) {
      setTakeOverMissing(true);
      return;
    }
    setBusy(true);
    setProblem(undefined);
    try {
      onSaved(
        await setTermAddress(typeId, term.id, {
          locale: values.locale,
          slug: values.slug,
          reason: values.reason.trim(),
          take_over_former: takesOver.length > 0,
        }),
      );
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
      setBusy(false);
    }
  }

  return (
    <PanelDialog
      busy={busy}
      onClose={onClose}
      title={t(`terms.${kind}.addressTitle`, { name: term.name })}
    >
      <form
        className="space-y-4"
        noValidate
        onSubmit={(event) => {
          void form.handleSubmit(submit)(event);
        }}
      >
        <FieldGroup>
          <Field>
            <FieldLabel htmlFor="term-address-locale">
              {t("terms.language")}
            </FieldLabel>
            <NativeSelect
              id="term-address-locale"
              {...form.register("locale", {
                onChange: (event: React.ChangeEvent<HTMLSelectElement>) =>
                  form.setValue("slug", term.slugs[event.target.value] ?? ""),
              })}
            >
              {list.locales.map((code) => (
                <option key={code} value={code}>
                  {languageName(code)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field data-invalid={Boolean(errors.slug?.message)}>
            <FieldLabel htmlFor="term-address-slug">
              {t("terms.address")}
            </FieldLabel>
            <InputGroup>
              <InputGroupAddon>
                <InputGroupText className="max-w-64 truncate">
                  {`${siteHost(address)}${lead}`}
                </InputGroupText>
              </InputGroupAddon>
              <InputGroupInput
                aria-describedby="term-address-help"
                id="term-address-slug"
                {...form.register("slug")}
              />
              <InputGroupAddon align="inline-end">
                <InputGroupText>/</InputGroupText>
              </InputGroupAddon>
            </InputGroup>
            <FieldDescription id="term-address-help">
              {t("terms.addressHelp")}
            </FieldDescription>
            <FieldError>{errors.slug?.message}</FieldError>
          </Field>
          {checking ? (
            <p className="text-sm text-muted-foreground">
              {t("terms.checking")}
            </p>
          ) : null}
          {moved.length > 0 ? (
            <div className="rounded-md bg-muted p-3 text-sm" role="status">
              <p className="font-medium">{t("terms.movedHeading")}</p>
              <ul className="mt-1 space-y-1">
                {moved.map((item) => (
                  <li className="break-all" key={item.locale}>
                    {t("terms.movedLine", {
                      from: item.from_path,
                      to: item.to_path,
                    })}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {moved.length > 0 ? (
            <Field data-invalid={Boolean(errors.reason?.message)}>
              <FieldLabel htmlFor="term-address-reason">
                {t("terms.reason")}
              </FieldLabel>
              <Input
                aria-invalid={Boolean(errors.reason?.message)}
                id="term-address-reason"
                {...form.register("reason")}
              />
              <FieldError>{errors.reason?.message}</FieldError>
            </Field>
          ) : null}
          {takesOver.map((item) => (
            <label
              className="flex items-start gap-2 rounded-lg border p-3 text-sm"
              key={item.slug}
            >
              <input
                checked={taken.has(item.slug)}
                className="mt-1"
                onChange={(event) =>
                  setTaken((previous) => {
                    const next = new Set(previous);
                    if (event.target.checked) next.add(item.slug);
                    else next.delete(item.slug);
                    return next;
                  })
                }
                type="checkbox"
              />
              <span>
                {t("terms.takeOver", { slug: item.slug, name: item.name })}
              </span>
            </label>
          ))}
          {takeOverMissing ? (
            <p className="text-sm text-destructive" role="alert">
              {t("terms.takeOverRequired")}
            </p>
          ) : null}
        </FieldGroup>
        {problem ? (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        ) : null}
        <DialogFooter>
          <Button
            disabled={busy}
            onClick={onClose}
            type="button"
            variant="outline"
          >
            {common("cancel")}
          </Button>
          <Button disabled={busy || !preview || !preview.changed} type="submit">
            {t("terms.addressSubmit")}
          </Button>
        </DialogFooter>
      </form>
    </PanelDialog>
  );
}

/** Removing a term: the server counts what keeps it; only a free one goes. */
function RemoveTermDialog({
  typeId,
  kind,
  term,
  onClose,
  onRemoved,
}: {
  typeId: string;
  kind: TermKind;
  term: Term;
  onClose: () => void;
  onRemoved: () => void;
}) {
  const t = useTranslations("Sites");
  const common = useTranslations("Common");
  const [preview, setPreview] = useState<TermRemoval>();
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();

  useEffect(() => {
    let current = true;
    previewTermRemoval(typeId, term.id)
      .then((result) => {
        if (current) setPreview(result);
      })
      .catch((error: unknown) => {
        if (current) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      current = false;
    };
  }, [typeId, term.id, t]);

  async function confirm() {
    setBusy(true);
    setProblem(undefined);
    try {
      await deleteTerm(typeId, term.id);
      onRemoved();
    } catch (error) {
      setProblem(sitesErrorMessage(error, t));
      setBusy(false);
    }
  }

  const blocked = preview !== undefined && !preview.removable;
  return (
    <PanelDialog
      busy={busy}
      onClose={onClose}
      title={
        blocked
          ? t("terms.blockedTitle", { name: term.name })
          : t(`terms.${kind}.removeTitle`, { name: term.name })
      }
    >
      <div className="space-y-3 text-sm">
        {preview === undefined && !problem ? (
          <p className="text-muted-foreground">{t("terms.checking")}</p>
        ) : null}
        {blocked ? (
          <p>
            {t(`terms.${kind}.blockedBody`, {
              drafts: preview.drafts,
              published: preview.published,
            })}
          </p>
        ) : null}
        {preview?.removable ? (
          <>
            <p>{t(`terms.${kind}.removeBody`)}</p>
            {preview.children > 0 ? (
              <p>{t("terms.removeChildren", { count: preview.children })}</p>
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
              disabled={busy || !preview?.removable}
              onClick={() => void confirm()}
              variant="destructive"
            >
              <Trash2Icon aria-hidden="true" />
              {t("terms.removeConfirm")}
            </Button>
          </>
        )}
      </DialogFooter>
    </PanelDialog>
  );
}
