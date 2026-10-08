"use client";

/** A section's name in the site's addresses, per language (ADR-071 pkt 14,
 *  „Uzupełnienie 2026-10-07”): `/poradnik/` in the site's own language,
 *  `/de/ratgeber/` in another. A language without a name of its own follows
 *  the site's. Every field shows the address as it will be, and the server's
 *  preview says which addresses move before anything is saved. */

import { useMemo, useState } from "react";
import { zodResolver } from "@hookform/resolvers/zod";
import { LinkIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { useForm, useWatch, type SubmitHandler } from "react-hook-form";
import { z } from "zod";

import {
  ApiProblemError,
  previewCollectionPaths,
  setCollectionPaths,
  type CollectionPathsResult,
  type ContentCollection,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import { Field, FieldError, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import {
  InputGroup,
  InputGroupAddon,
  InputGroupInput,
  InputGroupText,
} from "@saas-core/ui/components/input-group";

import { nativeName } from "#lib/company-locales";
import { sitesErrorMessage } from "./problem";

export const SECTION_PATH = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

/** The site's host as an address is read: without the scheme. */
export function siteHost(address?: string | null): string {
  return (address ?? "").replace(/^https?:\/\//, "").replace(/\/$/, "");
}

/** Names typed for other languages, without the empty ones: an empty field
 *  means „as in the site's language”. */
export function namedPaths(values: Record<string, string>) {
  return Object.fromEntries(
    Object.entries(values)
      .map(([code, name]) => [code, name.trim()] as const)
      .filter(([, name]) => name),
  );
}

type Translate = (key: string) => string;

/** What the server refused, by the field it named (`locale_paths.de`). */
export function sectionPathErrors(
  error: unknown,
  t: Translate,
): Record<string, string> {
  if (!(error instanceof ApiProblemError)) return {};
  const found: Record<string, string> = {};
  for (const item of error.problem.errors ?? []) {
    const message =
      item.code === "section_path_taken"
        ? t("blogPathTaken")
        : item.code === "slug_reserved"
          ? t("blogPathReserved")
          : item.code === "redirect_reason_required"
            ? t("blogPathsReasonRequired")
            : item.code === "section_path_former"
              ? t("blogPathFormer")
              : item.code === "invalid" || item.code === "section_path_invalid"
                ? t("invalidSlug")
                : item.message;
    // A refusal that names no field is about the site's own language.
    found[item.field ?? "base_path"] = message;
  }
  return found;
}

type PathValues = {
  base_path: string;
  locale_paths: Record<string, string>;
  reason: string;
};

/** The languages a section answers in: the site's own first, as the server
 *  lists them. */
function pathLocales(collection: ContentCollection): string[] {
  return Object.keys(collection.paths ?? {});
}

function pathValues(collection: ContentCollection): PathValues {
  return {
    base_path: collection.base_path,
    locale_paths: Object.fromEntries(
      pathLocales(collection)
        .slice(1)
        .map((code) => [code, collection.locale_paths?.[code] ?? ""]),
    ),
    reason: "",
  };
}

export function CollectionPaths({
  collection,
  address,
  onSaved,
  ofType = false,
}: {
  collection: ContentCollection;
  /** On a content type's settings (ADR-079): the words say „adres”, not
   *  „adres bloga” — the type may be projects or news. */
  ofType?: boolean;
  /** The site's public address, before the section's own part of it. */
  address?: string | null;
  onSaved: (collection: ContentCollection) => void;
}) {
  const t = useTranslations("Sites");
  const localeLabel = ofType
    ? "contentTypes.pathsLocaleLabel"
    : "blogPathsLocaleLabel";
  const common = useTranslations("Common");
  const [open, setOpen] = useState(false);
  const [problem, setProblem] = useState<string>();
  const [moved, setMoved] = useState<CollectionPathsResult["moved"]>([]);
  // Redirects to other sections that the new names would stop (ADR-079
  // pkt 14): shown before anything is saved, and saved only on a tick.
  const [takesOver, setTakesOver] = useState<
    CollectionPathsResult["takes_over"]
  >([]);
  const [takeOver, setTakeOver] = useState(false);
  const [takeOverMissing, setTakeOverMissing] = useState(false);
  const host = siteHost(address);
  const [source, ...others] = pathLocales(collection);
  const schema = useMemo(
    () =>
      z.object({
        base_path: z.string().regex(SECTION_PATH, t("invalidSlug")).max(80),
        locale_paths: z.record(
          z.string(),
          z
            .string()
            .max(80)
            .refine(
              (value) => !value.trim() || SECTION_PATH.test(value.trim()),
              t("invalidSlug"),
            ),
        ),
        reason: z.string().max(500),
      }),
    [t],
  );
  const form = useForm<PathValues>({
    resolver: zodResolver(schema),
    defaultValues: pathValues(collection),
  });
  const basePath = useWatch({ control: form.control, name: "base_path" });
  const errors = form.formState.errors;
  const id = (field: string) => `collection-path-${field}-${collection.id}`;

  const close = () => {
    setOpen(false);
    setMoved([]);
    setTakesOver([]);
    setTakeOver(false);
    setTakeOverMissing(false);
    setProblem(undefined);
    form.reset(pathValues(collection));
  };

  const submit: SubmitHandler<PathValues> = async (values) => {
    setProblem(undefined);
    const input = {
      base_path: values.base_path,
      locale_paths: namedPaths(values.locale_paths),
      reason: values.reason.trim(),
    };
    try {
      // Asked first: which addresses that answer today would move.
      const preview = await previewCollectionPaths(collection.id, input);
      setMoved(preview.moved);
      setTakesOver(preview.takes_over);
      if (!preview.changed) {
        close();
        return;
      }
      const unconfirmed = preview.takes_over.length > 0 && !takeOver;
      setTakeOverMissing(unconfirmed);
      if (preview.moved.length > 0 && !input.reason) {
        form.setError("reason", { message: t("blogPathsReasonRequired") });
        return;
      }
      if (unconfirmed) return;
      const saved = await setCollectionPaths(collection.id, {
        ...input,
        ...(preview.takes_over.length > 0 ? { take_over_former: true } : {}),
      });
      onSaved(saved.collection);
      setOpen(false);
      setMoved([]);
      setTakesOver([]);
      setTakeOver(false);
      form.reset(pathValues(saved.collection));
    } catch (error) {
      const refused = sectionPathErrors(error, t);
      const fields = Object.entries(refused);
      if (fields.length === 0) {
        setProblem(sitesErrorMessage(error, t));
        return;
      }
      for (const [field, message] of fields) {
        form.setError(
          field as "base_path" | "reason" | `locale_paths.${string}`,
          {
            message,
          },
        );
      }
    }
  };

  if (!source) return null;
  return (
    <section
      aria-labelledby={id("heading")}
      className="space-y-3 rounded-lg border p-3 text-sm"
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span
          className="flex items-center gap-2 font-medium"
          id={id("heading")}
        >
          <LinkIcon aria-hidden="true" className="size-4" />
          {t(ofType ? "contentTypes.pathsTitle" : "blogPathsTitle")}
        </span>
        {!open && (
          <Button
            onClick={() => setOpen(true)}
            size="sm"
            type="button"
            variant="outline"
          >
            {t("blogPathsChange")}
          </Button>
        )}
      </div>

      {!open ? (
        <ul className="space-y-1">
          {[source, ...others].map((code) => (
            <li className="flex flex-wrap gap-x-2" key={code}>
              <span className="text-muted-foreground">{nativeName(code)}</span>
              <span className="break-all">
                {`${host}${collection.paths[code]}`}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <form
          className="space-y-3"
          noValidate
          onSubmit={(event) => {
            void form.handleSubmit(submit)(event);
          }}
        >
          <Field data-invalid={Boolean(errors.base_path)}>
            <FieldLabel htmlFor={id("base")}>
              {t(localeLabel, { language: nativeName(source) })}
            </FieldLabel>
            <InputGroup>
              <InputGroupAddon>
                <InputGroupText className="max-w-48 truncate">{`${host}/`}</InputGroupText>
              </InputGroupAddon>
              <InputGroupInput
                aria-invalid={Boolean(errors.base_path)}
                id={id("base")}
                {...form.register("base_path")}
              />
              <InputGroupAddon align="inline-end">
                <InputGroupText>/</InputGroupText>
              </InputGroupAddon>
            </InputGroup>
            <FieldError>{errors.base_path?.message}</FieldError>
          </Field>
          {others.map((code) => (
            <Field
              data-invalid={Boolean(errors.locale_paths?.[code])}
              key={code}
            >
              <FieldLabel htmlFor={id(code)}>
                {t(localeLabel, { language: nativeName(code) })}
              </FieldLabel>
              <InputGroup>
                <InputGroupAddon>
                  {/* The host may be cut short; the language's part never is. */}
                  <InputGroupText className="gap-0">
                    <span className="max-w-36 truncate">{host}</span>
                    <span>{`/${code}/`}</span>
                  </InputGroupText>
                </InputGroupAddon>
                {/* Empty: the address follows the site's language, shown as
                    the placeholder so the field still reads as an address. */}
                <InputGroupInput
                  aria-invalid={Boolean(errors.locale_paths?.[code])}
                  id={id(code)}
                  placeholder={basePath}
                  {...form.register(`locale_paths.${code}`)}
                />
                <InputGroupAddon align="inline-end">
                  <InputGroupText>/</InputGroupText>
                </InputGroupAddon>
              </InputGroup>
              <FieldError>{errors.locale_paths?.[code]?.message}</FieldError>
            </Field>
          ))}
          {others.length > 0 && (
            <p className="text-muted-foreground">{t("blogPathsFollow")}</p>
          )}
          {moved.length > 0 && (
            <div className="rounded-md bg-muted p-3" role="status">
              <p className="font-medium">{t("blogPathsMoved")}</p>
              <ul className="mt-1 space-y-1">
                {moved.map((item) => (
                  <li className="break-all" key={item.locale}>
                    {`${host}${item.from_path} → ${host}${item.to_path}`}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {takesOver.length > 0 && (
            <div className="space-y-2 rounded-md border p-3">
              <p className="font-medium">{t("blogPathsTakesOver")}</p>
              <ul className="space-y-1">
                {takesOver.map((item) => (
                  <li className="break-all" key={`${item.locale}${item.path}`}>
                    {`${host}${item.path} → ${item.name}`}
                  </li>
                ))}
              </ul>
              <label className="flex items-start gap-2">
                <input
                  checked={takeOver}
                  className="mt-1"
                  onChange={(event) => {
                    setTakeOver(event.target.checked);
                    setTakeOverMissing(false);
                  }}
                  type="checkbox"
                />
                <span>{t("blogPathsTakeOverConfirm")}</span>
              </label>
              {takeOverMissing && (
                <p className="text-destructive" role="alert">
                  {t("blogPathsTakeOverRequired")}
                </p>
              )}
            </div>
          )}
          <Field data-invalid={Boolean(errors.reason)}>
            <FieldLabel htmlFor={id("reason")}>
              {t("blogPathsReason")}
            </FieldLabel>
            <Input
              aria-describedby={id("reason-hint")}
              aria-invalid={Boolean(errors.reason)}
              id={id("reason")}
              {...form.register("reason")}
            />
            <p className="text-muted-foreground" id={id("reason-hint")}>
              {t("blogPathsReasonHint")}
            </p>
            <FieldError>{errors.reason?.message}</FieldError>
          </Field>
          <div className="flex flex-wrap gap-2">
            <Button
              disabled={form.formState.isSubmitting}
              size="sm"
              type="submit"
            >
              {t("blogPathsSave")}
            </Button>
            <Button onClick={close} size="sm" type="button" variant="ghost">
              {common("cancel")}
            </Button>
          </div>
          {problem && (
            <p className="text-destructive" role="alert">
              {problem}
            </p>
          )}
        </form>
      )}
    </section>
  );
}
