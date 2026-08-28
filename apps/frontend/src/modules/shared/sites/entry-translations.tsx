"use client";

/** The language versions of one article.
 *
 *  Each language is its own entry with its own draft and its own publication,
 *  because the Polish and English texts are two different texts — often
 *  written weeks apart, and often only one of them ever exists. The shared
 *  group is what tells a search engine they are the same article. */

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { LanguagesIcon, PlusIcon } from "lucide-react";

import {
  createEntryTranslation,
  listEntryTranslations,
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
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";
import { slugifyTitle } from "./slug";

const LOCALES = ["pl", "en"] as const;
type Locale = (typeof LOCALES)[number];

export function EntryTranslations({
  entry,
  onCreated,
}: {
  entry: ContentEntry;
  onCreated: (translation: ContentEntry) => void;
}) {
  const t = useTranslations("Sites");
  const [translations, setTranslations] = useState<ContentEntry[]>([]);
  const [title, setTitle] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [slug, setSlug] = useState("");
  const [locale, setLocale] = useState<Locale>("en");
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const receipt = useRef<MutationReceipt | undefined>(undefined);

  useEffect(() => {
    let mounted = true;
    void listEntryTranslations(entry.id)
      .then((rows) => {
        if (mounted) setTranslations(rows);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      });
    return () => {
      mounted = false;
    };
  }, [entry.id, t]);

  // Derived rather than stored: until the operator types their own address it
  // simply *is* the title's, so there is no state to keep in step and no
  // effect writing into a field the user is looking at.
  const address = slugEdited ? slug : slugifyTitle(title);

  const missing = LOCALES.filter(
    (candidate) => !translations.some((item) => item.locale === candidate),
  );

  const submit = useCallback(() => {
    setBusy(true);
    setProblem(undefined);
    const input = { locale, slug: address, title };
    void createEntryTranslation(
      entry.id,
      input,
      mutationKey(receipt, `translation-${entry.id}`, input),
    )
      .then((created) => {
        setTranslations((current) => [...current, created]);
        setTitle("");
        setSlug("");
        setSlugEdited(false);
        onCreated(created);
      })
      .catch((error: unknown) => {
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        setBusy(false);
      });
  }, [address, entry.id, locale, onCreated, t, title]);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("entryTranslations")}</CardTitle>
        <CardDescription>{t("entryTranslationsDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {problem && (
          <p className="text-sm text-destructive" role="alert">
            {problem}
          </p>
        )}
        <ul className="space-y-2">
          {translations.map((item) => (
            <li
              className="flex flex-wrap items-center gap-2 rounded-lg border p-3"
              key={item.id}
            >
              <LanguagesIcon
                aria-hidden="true"
                className="size-4 text-muted-foreground"
              />
              <span className="font-medium uppercase">{item.locale}</span>
              <span className="flex-1 truncate">{item.title}</span>
              <Badge
                variant={item.state === "published" ? "default" : "secondary"}
              >
                {t(
                  item.state === "published"
                    ? "blogStatePublished"
                    : "blogStateDraft",
                )}
              </Badge>
            </li>
          ))}
        </ul>

        {missing.length > 0 && (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <Field>
              <FieldLabel htmlFor="translation-locale">
                {t("entryTranslationLocale")}
              </FieldLabel>
              <NativeSelect
                id="translation-locale"
                onChange={(event) => setLocale(event.target.value as Locale)}
                value={missing.includes(locale) ? locale : missing[0]}
              >
                {missing.map((candidate) => (
                  <option key={candidate} value={candidate}>
                    {t(candidate === "pl" ? "localePl" : "localeEn")}
                  </option>
                ))}
              </NativeSelect>
            </Field>
            <Field>
              <FieldLabel htmlFor="translation-title">
                {t("entryTranslationTitle")}
              </FieldLabel>
              <Input
                id="translation-title"
                onChange={(event) => setTitle(event.target.value)}
                value={title}
              />
            </Field>
            <Field>
              <FieldLabel htmlFor="translation-slug">
                {t("entryTranslationSlug")}
              </FieldLabel>
              <Input
                id="translation-slug"
                onChange={(event) => {
                  setSlugEdited(true);
                  setSlug(event.target.value);
                }}
                value={address}
              />
            </Field>
            <Button disabled={busy || title.length < 2} type="submit">
              <PlusIcon aria-hidden="true" />
              {t("entryAddTranslation")}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
