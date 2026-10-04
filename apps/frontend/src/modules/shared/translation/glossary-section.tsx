"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { PencilIcon, PlusIcon, Trash2Icon } from "lucide-react";

import {
  ApiProblemError,
  createGlossaryTerm,
  deleteGlossaryTerm,
  listGlossaryTerms,
  updateGlossaryTerm,
  type GlossaryTerm,
  type GlossaryTermInput,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  DataTable,
  RowActions,
  type ColumnDef,
} from "@saas-core/ui/components/data-table";
import {
  Dialog,
  DialogClose,
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
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";

import { nativeName, useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";

const PAGE_SIZE = 100;
const TERM_MAX = 120;
const FORMS_MAX = 10;
const RULES = ["keep", "name", "translate_as"] as const;

type Values = {
  term: string;
  rule: (typeof RULES)[number];
  source_locale: string;
  target_locale: string;
  translation: string;
  forms: string;
};
type Editing = { term?: GlossaryTerm; key: string };

const formsOf = (text: string) =>
  text
    .split("\n")
    .map((form) => form.trim())
    .filter(Boolean);

/**
 * The company's glossary (TL16e, ADR-069 pkt 7): names a translation keeps
 * as they are, people's names and the company's own translations of a term.
 * Everyone who may order a translation reads it; `translation.manage`
 * changes it.
 */
export function GlossarySection({
  canManage,
  limit,
}: {
  canManage: boolean;
  /** Terms a company may have (`glossary_limit` of the offer). */
  limit: number;
}) {
  const t = useTranslations("Translations.settings.glossary");
  const common = useTranslations("Common");
  const labels = useDataTableLabels();
  const ids = useId();
  const locales = useCompanyLocales([]);
  const [rows, setRows] = useState<GlossaryTerm[]>();
  const [cursor, setCursor] = useState<string | null>(null);
  // Every term the company has, whatever part of the list is on screen.
  const [count, setCount] = useState<number>();
  const [reloads, setReloads] = useState(0);
  const [problem, setProblem] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<Editing>();
  const [removing, setRemoving] = useState<Editing>();
  const [dialogProblem, setDialogProblem] = useState("");

  useEffect(() => {
    let alive = true;
    listGlossaryTerms({ limit: PAGE_SIZE })
      .then((page) => {
        if (!alive) return;
        setRows(page.items);
        setCursor(page.next_cursor);
        setCount(page.count);
      })
      .catch(() => {
        if (!alive) return;
        setRows([]);
        setProblem(t("loadError"));
      });
    return () => {
      alive = false;
    };
  }, [reloads, t]);

  const schema = useMemo(
    () =>
      z
        .object({
          term: z
            .string()
            .trim()
            .min(1, t("errors.glossary_term_empty"))
            .max(TERM_MAX, t("errors.glossary_term_too_long")),
          rule: z.enum(RULES),
          source_locale: z.string().min(1),
          target_locale: z.string(),
          translation: z
            .string()
            .trim()
            .max(TERM_MAX, t("errors.glossary_term_too_long")),
          forms: z.string(),
        })
        .superRefine((values, context) => {
          if (values.rule === "translate_as" && !values.translation)
            context.addIssue({
              code: "custom",
              path: ["translation"],
              message: t("errors.glossary_translation_required"),
            });
          if (
            values.target_locale &&
            values.target_locale === values.source_locale
          )
            context.addIssue({
              code: "custom",
              path: ["target_locale"],
              message: t("errors.same_as_source"),
            });
          const forms = formsOf(values.forms);
          if (forms.length > FORMS_MAX)
            context.addIssue({
              code: "custom",
              path: ["forms"],
              message: t("errors.glossary_too_many_forms"),
            });
          else if (forms.some((form) => form.length > TERM_MAX))
            context.addIssue({
              code: "custom",
              path: ["forms"],
              message: t("errors.glossary_term_too_long"),
            });
        }),
    [t],
  );
  const form = useForm<Values>({ resolver: zodResolver(schema) });
  const rule = useWatch({ control: form.control, name: "rule" });
  const { errors } = form.formState;

  function open(term?: GlossaryTerm) {
    setDialogProblem("");
    setNotice("");
    form.reset({
      term: term?.term ?? "",
      rule: term?.rule ?? "keep",
      source_locale: term?.source_locale ?? locales[0]?.code ?? "",
      target_locale: term?.target_locale ?? "",
      translation: term?.translation ?? "",
      forms: (term?.forms ?? []).join("\n"),
    });
    setEditing({ term, key: crypto.randomUUID() });
  }

  /** The words for what the server refused, on the field it names. */
  function refused(error: unknown, fallback: string) {
    const found = error instanceof ApiProblemError ? error.problem : undefined;
    if (found?.code === "translation_version_conflict") {
      setDialogProblem(t("conflict"));
      setReloads((value) => value + 1);
      return;
    }
    if (found?.status === 403) {
      setDialogProblem(t("forbidden"));
      return;
    }
    let placed = false;
    for (const item of found?.errors ?? []) {
      const field = (item.field ?? "").split(".")[0] as keyof Values;
      if (!(field in form.getValues())) continue;
      form.setError(field, {
        type: "server",
        message: t.has(`errors.${item.code}`)
          ? t(`errors.${item.code}`, { limit })
          : t("errors.other"),
      });
      placed = true;
    }
    if (!placed) setDialogProblem(fallback);
  }

  async function save(values: Values) {
    if (!editing) return;
    const input: GlossaryTermInput = {
      term: values.term,
      rule: values.rule,
      source_locale: values.source_locale,
      target_locale: values.target_locale,
      translation: values.rule === "translate_as" ? values.translation : "",
      forms: formsOf(values.forms),
    };
    setBusy(true);
    setDialogProblem("");
    try {
      if (editing.term)
        await updateGlossaryTerm(
          editing.term.id,
          input,
          editing.term.version,
          editing.key,
        );
      else await createGlossaryTerm(input, editing.key);
      setNotice(t(editing.term ? "saved" : "added", { term: values.term }));
      setEditing(undefined);
      setReloads((value) => value + 1);
    } catch (error) {
      refused(error, t("saveError"));
      // What was refused is sent again as a new request.
      setEditing((current) =>
        current ? { ...current, key: crypto.randomUUID() } : current,
      );
    } finally {
      setBusy(false);
    }
  }

  async function remove(asked: Editing) {
    if (!asked.term) return;
    setBusy(true);
    setDialogProblem("");
    try {
      await deleteGlossaryTerm(asked.term.id, asked.term.version, asked.key);
      setNotice(t("removed", { term: asked.term.term }));
      setRemoving(undefined);
      setReloads((value) => value + 1);
    } catch (error) {
      refused(error, t("removeError"));
    } finally {
      setBusy(false);
    }
  }

  async function loadMore(from: string) {
    setBusy(true);
    setProblem("");
    try {
      const page = await listGlossaryTerms({ limit: PAGE_SIZE, cursor: from });
      setRows((current) => [...(current ?? []), ...page.items]);
      setCursor(page.next_cursor);
      setCount(page.count);
    } catch {
      setProblem(t("loadError"));
    } finally {
      setBusy(false);
    }
  }

  const ruleText = (term: GlossaryTerm) =>
    term.rule === "translate_as"
      ? t("ruleLine.translate_as", { translation: term.translation })
      : t(`ruleLine.${term.rule}`);
  const columns: ColumnDef<GlossaryTerm, unknown>[] = [
    {
      id: "term",
      accessorKey: "term",
      header: t("colTerm"),
      meta: { primary: true },
      cell: ({ row: { original: term } }) => {
        const forms = term.forms;
        return (
          <div className="space-y-0.5">
            <p className="font-medium wrap-anywhere">{term.term}</p>
            {forms.length ? (
              <p className="text-xs text-muted-foreground wrap-anywhere">
                {t("formsLine", { forms: forms.join(", ") })}
              </p>
            ) : null}
          </div>
        );
      },
    },
    {
      id: "rule",
      accessorFn: ruleText,
      header: t("colRule"),
      meta: { long: true },
    },
    {
      id: "languages",
      accessorFn: (term) =>
        term.target_locale
          ? t("languagePair", {
              source: nativeName(term.source_locale),
              target: nativeName(term.target_locale),
            })
          : t("languageAll", { source: nativeName(term.source_locale) }),
      header: t("colLanguages"),
    },
    ...(canManage
      ? [
          {
            id: "actions",
            header: t("colActions"),
            meta: { actions: true },
            cell: ({ row: { original: term } }) => (
              <RowActions
                items={[
                  {
                    label: t("edit", { term: term.term }),
                    icon: <PencilIcon aria-hidden="true" />,
                    inline: true,
                    main: true,
                    onSelect: () => open(term),
                  },
                  {
                    label: t("remove", { term: term.term }),
                    icon: <Trash2Icon aria-hidden="true" />,
                    destructive: true,
                    onSelect: () => {
                      setDialogProblem("");
                      setNotice("");
                      setRemoving({ term, key: crypto.randomUUID() });
                    },
                  },
                ]}
                label={t("actionsFor", { term: term.term })}
              />
            ),
          } satisfies ColumnDef<GlossaryTerm, unknown>,
        ]
      : []),
  ];

  return (
    <section className="space-y-3">
      <div className="space-y-1">
        <div className="flex flex-wrap items-end justify-between gap-x-3 gap-y-2">
          <h3 className="min-w-0 flex-1 basis-40 font-medium">{t("title")}</h3>
          {canManage ? (
            <Button
              onClick={() => open()}
              size="sm"
              type="button"
              variant="outline"
            >
              <PlusIcon aria-hidden="true" />
              {t("add")}
            </Button>
          ) : null}
        </div>
        <p className="max-w-3xl text-sm text-muted-foreground">
          {t("description")}
        </p>
        {count === undefined ? null : (
          <p className="text-sm text-muted-foreground">
            {t("count", { count, limit })}
          </p>
        )}
      </div>
      <p className="text-sm empty:hidden" role="status">
        {notice}
      </p>
      {problem ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{problem}</p>
          <Button
            onClick={() => {
              setProblem("");
              setReloads((value) => value + 1);
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("retry")}
          </Button>
        </div>
      ) : null}
      <DataTable
        caption={t("caption")}
        columns={columns}
        data={rows ?? []}
        getRowId={(term) => term.id}
        labels={{ ...labels, empty: t("empty") }}
        loading={!rows}
        pageSize={PAGE_SIZE}
      />
      {cursor ? (
        <Button
          disabled={busy}
          onClick={() => void loadMore(cursor)}
          type="button"
          variant="outline"
        >
          {t("loadMore")}
        </Button>
      ) : null}

      <Dialog
        onOpenChange={(next) => (next ? undefined : setEditing(undefined))}
        open={editing !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {t(editing?.term ? "editTitle" : "addTitle")}
            </DialogTitle>
            <DialogDescription>{t("dialogDescription")}</DialogDescription>
          </DialogHeader>
          <form
            className="space-y-4"
            noValidate
            onSubmit={form.handleSubmit(save)}
          >
            <FieldGroup>
              <Field data-invalid={Boolean(errors.term)}>
                <FieldLabel htmlFor={`${ids}-term`}>
                  {t("fieldTerm")}
                </FieldLabel>
                <Input
                  aria-invalid={Boolean(errors.term)}
                  id={`${ids}-term`}
                  maxLength={TERM_MAX}
                  {...form.register("term")}
                />
                <FieldDescription>{t("fieldTermHelp")}</FieldDescription>
                <FieldError errors={[errors.term]} />
              </Field>
              <Field data-invalid={Boolean(errors.rule)}>
                <FieldLabel htmlFor={`${ids}-rule`}>
                  {t("fieldRule")}
                </FieldLabel>
                <NativeSelect id={`${ids}-rule`} {...form.register("rule")}>
                  {RULES.map((value) => (
                    <option key={value} value={value}>
                      {t(`rules.${value}`)}
                    </option>
                  ))}
                </NativeSelect>
                <FieldDescription>
                  {t(`ruleHelp.${rule ?? "keep"}`)}
                </FieldDescription>
                <FieldError errors={[errors.rule]} />
              </Field>
              {rule === "translate_as" ? (
                <Field data-invalid={Boolean(errors.translation)}>
                  <FieldLabel htmlFor={`${ids}-translation`}>
                    {t("fieldTranslation")}
                  </FieldLabel>
                  <Input
                    aria-invalid={Boolean(errors.translation)}
                    id={`${ids}-translation`}
                    maxLength={TERM_MAX}
                    {...form.register("translation")}
                  />
                  <FieldError errors={[errors.translation]} />
                </Field>
              ) : null}
              <Field data-invalid={Boolean(errors.source_locale)}>
                <FieldLabel htmlFor={`${ids}-source`}>
                  {t("fieldSource")}
                </FieldLabel>
                <NativeSelect
                  id={`${ids}-source`}
                  {...form.register("source_locale")}
                >
                  {locales.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </NativeSelect>
                <FieldError errors={[errors.source_locale]} />
              </Field>
              <Field data-invalid={Boolean(errors.target_locale)}>
                <FieldLabel htmlFor={`${ids}-target`}>
                  {t("fieldTarget")}
                </FieldLabel>
                <NativeSelect
                  aria-invalid={Boolean(errors.target_locale)}
                  id={`${ids}-target`}
                  {...form.register("target_locale")}
                >
                  <option value="">{t("everyLanguage")}</option>
                  {locales.map((item) => (
                    <option key={item.code} value={item.code}>
                      {item.name}
                    </option>
                  ))}
                </NativeSelect>
                <FieldError errors={[errors.target_locale]} />
              </Field>
              <Field data-invalid={Boolean(errors.forms)}>
                <FieldLabel htmlFor={`${ids}-forms`}>
                  {t("fieldForms")}
                </FieldLabel>
                <Textarea
                  aria-invalid={Boolean(errors.forms)}
                  id={`${ids}-forms`}
                  rows={3}
                  {...form.register("forms")}
                />
                <FieldDescription>{t("fieldFormsHelp")}</FieldDescription>
                <FieldError errors={[errors.forms]} />
              </Field>
            </FieldGroup>
            {dialogProblem ? (
              <p className="text-sm text-destructive" role="alert">
                {dialogProblem}
              </p>
            ) : null}
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>
                {common("cancel")}
              </DialogClose>
              <Button disabled={busy} type="submit">
                {t(editing?.term ? "save" : "add")}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(next) => (next ? undefined : setRemoving(undefined))}
        open={removing !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {t("removeTitle", { term: removing?.term?.term ?? "" })}
            </DialogTitle>
            <DialogDescription>{t("removeDescription")}</DialogDescription>
          </DialogHeader>
          {dialogProblem ? (
            <p className="text-sm text-destructive" role="alert">
              {dialogProblem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy}
              onClick={() => removing && void remove(removing)}
              type="button"
              variant="destructive"
            >
              {t("removeConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </section>
  );
}
