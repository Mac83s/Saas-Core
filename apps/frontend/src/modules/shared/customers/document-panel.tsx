"use client";

import { useCallback, useEffect, useId, useState } from "react";
import { useFormatter, useTranslations } from "next-intl";

import {
  addCustomerDocumentText,
  ApiProblemError,
  approveCustomerDocument,
  previewCustomerDocumentApproval,
  readCustomerDocument,
  saveCustomerDocumentDraft,
  type CustomerDocument,
  type CustomerDocumentApprovalEffect,
  type CustomerDocumentOptions,
  type CustomerDocumentVersion,
} from "@saas-core/api-client";
import { Badge } from "@saas-core/ui/components/badge";
import { Button, buttonVariants } from "@saas-core/ui/components/button";
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
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
  FieldLabel,
} from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";
import { Textarea } from "@saas-core/ui/components/textarea";
import { cn } from "@saas-core/ui/lib/utils";

import { PanelPage } from "#components/panel/panel-page";
import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import { useStepUp } from "../../core/organizations/step-up";
import { TranslateMissing } from "../translation/translate-missing";
import { translationComposed } from "../translation/use-translation";

type Kind = CustomerDocument["kind"];
type TextEdit = { number: number; locale: string; text: string };

/** Where a machine translation of a document waits for a person. */
const REVIEW = "/panel/sites/translations/review";

function message(error: unknown, fallback: string): string {
  return error instanceof ApiProblemError ? error.message : fallback;
}

/**
 * One document for the company's customers (ADR-073 §9): the draft somebody
 * is writing, the version in force with its text per language, and the
 * versions so far. A draft binds nobody; approving it and adding a text in
 * another language take a fresh code from the authenticator app, and what was
 * approved is never rewritten — a correction is a new text, a change the next
 * version. A missing language can be ordered from the translation engine; its
 * text never reaches customers by itself — it waits in the translation review
 * for a person's acceptance, with the same code.
 */
export function CustomerDocumentPanel({
  kind,
  canManage,
}: {
  kind: Kind;
  canManage: boolean;
}) {
  const t = useTranslations("CustomerDocuments");
  const common = useTranslations("Common");
  const format = useFormatter();
  const labels = useDataTableLabels();
  const stepUp = useStepUp(t("stepUp"));
  const ids = useId();
  const [document, setDocument] = useState<CustomerDocument>();
  const [options, setOptions] = useState<CustomerDocumentOptions>();
  const [failed, setFailed] = useState(false);
  const [text, setText] = useState("");
  const [locale, setLocale] = useState("");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [notice, setNotice] = useState<string>();
  const [approval, setApproval] = useState<{
    effect: CustomerDocumentApprovalEffect;
    date: string;
  }>();
  const [edit, setEdit] = useState<TextEdit>();

  const show = useCallback(
    (value: CustomerDocument, defaults?: CustomerDocumentOptions) => {
      setDocument(value);
      setText(value.draft?.text ?? "");
      setLocale(
        (current) =>
          value.draft?.locale || current || defaults?.default_locale || "",
      );
    },
    [],
  );

  const load = useCallback(async () => {
    setFailed(false);
    try {
      const value = await readCustomerDocument(kind);
      setOptions(value.options);
      show(value.document, value.options);
    } catch {
      setFailed(true);
    }
  }, [kind, show]);

  useEffect(() => {
    let mounted = true;
    void readCustomerDocument(kind)
      .then((value) => {
        if (!mounted) return;
        setOptions(value.options);
        show(value.document, value.options);
      })
      .catch(() => {
        if (mounted) setFailed(true);
      });
    return () => {
      mounted = false;
    };
  }, [kind, show]);

  const day = (value: string) =>
    format.dateTime(new Date(`${value}T12:00:00`), { dateStyle: "medium" });
  const dirty =
    document !== undefined &&
    (text.trim() !== (document.draft?.text ?? "") ||
      (text.trim() !== "" && locale !== (document.draft?.locale ?? locale)));

  /** The draft as the editor has it, saved when it differs; the document after. */
  async function saved(): Promise<CustomerDocument | undefined> {
    if (!document) return undefined;
    if (!dirty) return document;
    const next = await saveCustomerDocumentDraft(kind, {
      text,
      locale,
      expected_version: document.version,
    });
    show(next);
    return next;
  }

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setProblem(undefined);
    try {
      await action();
    } catch (error) {
      if (stepUp.handled(error, () => run(action, fallback))) {
        // An account without two-factor sign-in: the hook says where to turn
        // it on, on the page — behind the open dialog, so the dialog says it
        // too and keeps what was typed.
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "step_up_mfa_setup_required"
        ) {
          setProblem(t("needsTwoFactor"));
        }
      } else {
        setProblem(message(error, fallback));
        if (
          error instanceof ApiProblemError &&
          error.problem.code === "customers_document_version_conflict"
        ) {
          await load();
        }
      }
    } finally {
      setBusy(false);
    }
  }

  const saveDraft = () =>
    run(async () => {
      await saved();
      setNotice(text.trim() ? t("draftSaved") : t("draftCleared"));
    }, t("saveError"));

  const askApproval = () =>
    run(async () => {
      const current = await saved();
      if (!current) return;
      const preview = await previewCustomerDocumentApproval(kind, {
        expected_version: current.version,
      });
      setApproval({
        effect: preview.effect,
        date: preview.effect.effective_from,
      });
    }, t("saveError"));

  const approve = () =>
    run(async () => {
      if (!document || !approval) return;
      const result = await approveCustomerDocument(kind, {
        expected_version: document.version,
        effective_from: approval.date,
      });
      setApproval(undefined);
      show(result.document);
      setNotice(t("approved", { number: result.effect.number }));
    }, t("approveError"));

  const saveText = () =>
    run(async () => {
      if (!document || !edit) return;
      const next = await addCustomerDocumentText(kind, {
        number: edit.number,
        locale: edit.locale,
        text: edit.text,
        expected_version: document.version,
      });
      setEdit(undefined);
      show(next);
      setNotice(t("textAdded", { language: nativeName(edit.locale) }));
    }, t("saveError"));

  const versionColumns: ColumnDef<CustomerDocumentVersion, unknown>[] = [
    {
      id: "number",
      header: t("colVersion"),
      meta: { primary: true },
      cell: ({ row: { original: row } }) => (
        <span className="font-medium">
          {t("versionNumber", { number: row.number })}
        </span>
      ),
    },
    {
      id: "effective",
      header: t("colEffective"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => day(row.effective_from),
    },
    {
      id: "approved",
      header: t("colApproved"),
      enableSorting: false,
      cell: ({ row: { original: row } }) =>
        t("approvedBy", {
          date: format.dateTime(new Date(row.approved_at), {
            dateStyle: "medium",
            timeStyle: "short",
          }),
          person: row.approved_by || "—",
        }),
    },
    {
      id: "languages",
      header: t("colLanguages"),
      enableSorting: false,
      cell: ({ row: { original: row } }) => (
        <span className="flex flex-wrap gap-1.5">
          {row.locales.map((code) => (
            <Badge key={code} variant="secondary">
              {code.toUpperCase()}
            </Badge>
          ))}
        </span>
      ),
    },
  ];

  function versionSection(version: CustomerDocumentVersion, title: string) {
    const texts = new Map(
      (version.texts ?? []).map((row) => [row.locale, row]),
    );
    const codes = [
      ...new Set([...(options?.locales ?? []), ...version.locales]),
    ];
    // A machine translation is made for one version: the one in force, or
    // the one approved for a later day.
    const translation =
      document?.translation?.version === version.number && translationComposed()
        ? document.translation
        : undefined;
    return (
      <section
        aria-label={title}
        className="space-y-3 rounded-lg border p-4"
        key={version.number}
      >
        <div className="space-y-1">
          <h2 className="text-base font-semibold">{title}</h2>
          <p className="text-sm text-muted-foreground">
            {t("approvedBy", {
              date: format.dateTime(new Date(version.approved_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
              person: version.approved_by || "—",
            })}
          </p>
        </div>
        <ul className="space-y-3">
          {codes.map((code) => {
            const row = texts.get(code);
            return (
              <li className="space-y-2" key={code}>
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="flex flex-wrap items-center gap-2">
                    <span className="font-medium">{nativeName(code)}</span>
                    {row ? null : (
                      <Badge variant="outline">{t("noText")}</Badge>
                    )}
                  </span>
                  {canManage ? (
                    <Button
                      onClick={() => {
                        setProblem(undefined);
                        setEdit({
                          number: version.number,
                          locale: code,
                          text: row?.text ?? "",
                        });
                      }}
                      size="sm"
                      variant="outline"
                    >
                      {row
                        ? t("correctText", { language: nativeName(code) })
                        : t("addText", { language: nativeName(code) })}
                    </Button>
                  ) : null}
                </div>
                {row ? (
                  <details className="rounded-md bg-muted/40 px-3 py-2 text-sm">
                    <summary className="cursor-pointer">
                      {t("showText")}
                    </summary>
                    <p className="mt-2 wrap-anywhere whitespace-pre-wrap">
                      {row.text}
                    </p>
                  </details>
                ) : (
                  <p className="text-sm text-muted-foreground">
                    {t("noTextHelp", { language: nativeName(code) })}
                  </p>
                )}
                {translation?.waiting.includes(code) ? (
                  <p className="text-sm" role="status">
                    {t("translationWaits", { language: nativeName(code) })}{" "}
                    <Link
                      className="underline underline-offset-2"
                      href={REVIEW}
                    >
                      {t("translationReview")}
                    </Link>
                  </p>
                ) : null}
              </li>
            );
          })}
        </ul>
        {translation && canManage ? (
          <div className="space-y-2 border-t pt-3">
            <p className="max-w-3xl text-sm text-muted-foreground">
              {t("translateHelp")}{" "}
              <Link className="underline underline-offset-2" href={REVIEW}>
                {t("translationReview")}
              </Link>
            </p>
            <TranslateMissing
              onOrdered={() => void load()}
              orderedMessage={t("translationOrdered")}
              // A language whose translation already waits is not ordered
              // (and paid for) a second time.
              targets={codes
                .filter(
                  (code) =>
                    code !== version.source_locale &&
                    !translation.waiting.includes(code),
                )
                .map((locale) => ({
                  source_key: "customers.document",
                  object_id: translation.object_id,
                  locale,
                  basis: "published" as const,
                }))}
            />
          </div>
        ) : null}
      </section>
    );
  }

  const source = document?.in_force?.texts?.find(
    (row) => row.locale === document.in_force?.source_locale,
  );
  return (
    <PanelPage
      actions={
        document?.public_url ? (
          <a
            // Merged, or the base's transparent border hides the outline.
            className={cn(buttonVariants({ variant: "outline" }))}
            href={document.public_url}
            rel="noreferrer"
            target="_blank"
          >
            {t("openPublic")}
          </a>
        ) : null
      }
      description={t(`about.${kind}`)}
      eyebrow={t("title")}
      eyebrowHref="/panel/settings/documents"
      notice={notice}
      title={t(`kinds.${kind}`)}
    >
      {failed ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{t("loadError")}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : null}
      {stepUp.ui}
      {problem && !approval && !edit ? (
        <p className="text-sm text-destructive" role="alert">
          {problem}
        </p>
      ) : null}

      {document && canManage ? (
        <section
          aria-label={t("draftTitle")}
          className="space-y-4 rounded-lg border p-4"
        >
          <div className="space-y-1">
            <h2 className="text-base font-semibold">{t("draftTitle")}</h2>
            <p className="text-sm text-muted-foreground">{t("draftHelp")}</p>
            {/* Written by the assistant, not yet saved by a person: whoever
                approves it should know whose words they are (ADR-073 §9). */}
            {document.draft?.origin_ref ? (
              <p className="text-sm font-medium" role="note">
                {t("draftFromAssistant")}
              </p>
            ) : null}
          </div>
          <Field className="max-w-xs">
            <FieldLabel htmlFor={`${ids}-locale`}>
              {t("draftLanguage")}
            </FieldLabel>
            <NativeSelect
              id={`${ids}-locale`}
              onChange={(event) => setLocale(event.target.value)}
              value={locale}
            >
              {(options?.locales ?? []).map((code) => (
                <option key={code} value={code}>
                  {nativeName(code)}
                </option>
              ))}
            </NativeSelect>
          </Field>
          <Field>
            <FieldLabel htmlFor={`${ids}-text`}>{t("draftText")}</FieldLabel>
            <Textarea
              className="min-h-64"
              id={`${ids}-text`}
              maxLength={options?.text_max}
              onChange={(event) => setText(event.target.value)}
              value={text}
            />
            <FieldDescription>{t("draftTextHelp")}</FieldDescription>
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={busy || !dirty}
              onClick={() => void saveDraft()}
              variant="outline"
            >
              {t("saveDraft")}
            </Button>
            <Button
              disabled={busy || !text.trim()}
              onClick={() => void askApproval()}
            >
              {t("approve")}
            </Button>
            {source && !text.trim() ? (
              <Button
                disabled={busy}
                onClick={() => {
                  setText(source.text);
                  setLocale(source.locale);
                }}
                variant="ghost"
              >
                {t("startFromCurrent")}
              </Button>
            ) : null}
          </div>
        </section>
      ) : null}

      {document?.in_force ? (
        versionSection(
          document.in_force,
          t("inForce", {
            number: document.in_force.number,
            date: day(document.in_force.effective_from),
          }),
        )
      ) : document ? (
        <p className="text-sm text-muted-foreground">{t("notInForceHelp")}</p>
      ) : null}
      {document?.upcoming
        ? versionSection(
            document.upcoming,
            t("upcoming", {
              number: document.upcoming.number,
              date: day(document.upcoming.effective_from),
            }),
          )
        : null}

      {document?.versions?.length ? (
        <section aria-label={t("versionsTitle")} className="space-y-3">
          <h2 className="text-base font-semibold">{t("versionsTitle")}</h2>
          <DataTable
            caption={t("versionsTitle")}
            columns={versionColumns}
            data={document.versions}
            getRowId={(row) => String(row.number)}
            labels={labels}
          />
        </section>
      ) : null}

      <Dialog
        onOpenChange={(next) => (next ? undefined : setApproval(undefined))}
        open={approval !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>{t("approveTitle")}</DialogTitle>
            <DialogDescription>
              {approval
                ? t("approveDescription", { number: approval.effect.number })
                : ""}
            </DialogDescription>
          </DialogHeader>
          <Field className="max-w-xs">
            <FieldLabel htmlFor={`${ids}-date`}>
              {t("effectiveFrom")}
            </FieldLabel>
            <Input
              id={`${ids}-date`}
              min={approval?.effect.effective_from}
              onChange={(event) =>
                setApproval((current) =>
                  current && event.target.value
                    ? { ...current, date: event.target.value }
                    : current,
                )
              }
              type="date"
              value={approval?.date ?? ""}
            />
          </Field>
          {approval?.effect.locales_without_text.length ? (
            <p className="text-sm">
              {t("approveMissing", {
                languages: approval.effect.locales_without_text
                  .map(nativeName)
                  .join(", "),
              })}
            </p>
          ) : null}
          <p className="text-sm text-muted-foreground">{t("approveFinal")}</p>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button disabled={busy} onClick={() => void approve()}>
              {t("approveConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog
        onOpenChange={(next) => (next ? undefined : setEdit(undefined))}
        open={edit !== undefined}
      >
        <DialogContent closeLabel={common("close")}>
          <DialogHeader>
            <DialogTitle>
              {edit
                ? t("textTitle", {
                    language: nativeName(edit.locale),
                    number: edit.number,
                  })
                : ""}
            </DialogTitle>
            <DialogDescription>{t("textDescription")}</DialogDescription>
          </DialogHeader>
          <Field>
            <FieldLabel htmlFor={`${ids}-edit`}>{t("draftText")}</FieldLabel>
            <Textarea
              className="max-h-[50vh] min-h-48"
              id={`${ids}-edit`}
              maxLength={options?.text_max}
              onChange={(event) =>
                setEdit((current) =>
                  current ? { ...current, text: event.target.value } : current,
                )
              }
              value={edit?.text ?? ""}
            />
          </Field>
          {problem ? (
            <p className="text-sm text-destructive" role="alert">
              {problem}
            </p>
          ) : null}
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              {common("cancel")}
            </DialogClose>
            <Button
              disabled={busy || !edit?.text.trim()}
              onClick={() => void saveText()}
            >
              {t("textConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </PanelPage>
  );
}
