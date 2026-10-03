"use client";

/** The language versions of one article.
 *
 *  Each language is its own entry with its own draft and its own publication,
 *  because the Polish and English texts are two different texts — often
 *  written weeks apart, and often only one of them ever exists. The shared
 *  group is what tells a search engine they are the same article. */

import { useEffect, useRef, useState } from "react";
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
import { DataTable, type ColumnDef } from "@saas-core/ui/components/data-table";
import { Field, FieldLabel } from "@saas-core/ui/components/field";
import { Input } from "@saas-core/ui/components/input";
import { NativeSelect } from "@saas-core/ui/components/native-select";

import { nativeName, useCompanyLocales } from "#lib/company-locales";
import { useDataTableLabels } from "#lib/data-table-labels";
import {
  TranslateDialog,
  TranslationUnavailable,
} from "../translation/translate-dialog";
import {
  translationJobFinished,
  useTranslationJob,
  useTranslationOffer,
} from "../translation/use-translation";
import { mutationKey, type MutationReceipt } from "./idempotency";
import { sitesErrorMessage } from "./problem";
import { slugFromTitle } from "./slug";

export function EntryTranslations({
  entry,
  onCreated,
}: {
  entry: ContentEntry;
  /** A version appeared, written here or by an automatic translation. */
  onCreated: () => void;
}) {
  const t = useTranslations("Sites");
  const labels = useDataTableLabels();
  const [translations, setTranslations] = useState<ContentEntry[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [title, setTitle] = useState("");
  const [slugEdited, setSlugEdited] = useState(false);
  const [slug, setSlug] = useState("");
  const [locale, setLocale] = useState("en");
  // The company's languages, not a list written here (ADR-071 pkt 5).
  const companyLocaleOptions = useCompanyLocales(["pl", "en"]);
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState<string>();
  const receipt = useRef<MutationReceipt | undefined>(undefined);
  // Automatic translation into the languages still missing: the order runs
  // on the server, and the list reloads when it ends.
  const offer = useTranslationOffer();
  const [translating, setTranslating] = useState(false);
  const [jobId, setJobId] = useState<string>();
  const job = useTranslationJob(jobId);
  const jobDone = translationJobFinished(job);
  useEffect(() => {
    if (jobDone) onCreated();
    // `onCreated` is the same for the card's life.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobDone]);

  useEffect(() => {
    let mounted = true;
    void listEntryTranslations(entry.id)
      .then((rows) => {
        if (mounted) setTranslations(rows);
      })
      .catch((error: unknown) => {
        if (mounted) setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        if (mounted) setLoaded(true);
      });
    return () => {
      mounted = false;
    };
    // Again when an order ends: it wrote the versions listed here.
  }, [entry.id, t, jobDone]);

  // Derived rather than stored: until the operator types their own address it
  // simply *is* the title's, so there is no state to keep in step and no
  // effect writing into a field the user is looking at.
  // In the version's own language: "Über uns" becomes "ueber-uns", as the
  // backend writes it.
  const address = slugEdited ? slug : slugFromTitle(title);

  const missing = companyLocaleOptions.filter(
    (candidate) =>
      candidate.code !== entry.locale &&
      !translations.some((item) => item.locale === candidate.code),
  );
  // The picked language while it is still missing, otherwise the first one.
  const chosen = missing.some((candidate) => candidate.code === locale)
    ? locale
    : (missing[0]?.code ?? locale);

  const submit = () => {
    setBusy(true);
    setProblem(undefined);
    const input = { locale: chosen, slug: address, title };
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
        onCreated();
      })
      .catch((error: unknown) => {
        setProblem(sitesErrorMessage(error, t));
      })
      .finally(() => {
        setBusy(false);
      });
  };

  const stateLabel = (item: ContentEntry) =>
    t(item.state === "published" ? "blogStatePublished" : "blogStateDraft");
  const columns: ColumnDef<ContentEntry, unknown>[] = [
    {
      id: "title",
      accessorKey: "title",
      header: t("blogEntryTitle"),
      meta: { primary: true },
      cell: ({ row: { original: item } }) => (
        <span className="font-medium wrap-anywhere">{item.title}</span>
      ),
    },
    {
      id: "locale",
      // Each language named in itself, as the picker below names it.
      accessorFn: (item) =>
        companyLocaleOptions.find((option) => option.code === item.locale)
          ?.name ?? nativeName(item.locale),
      header: t("blogEntryLocale"),
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
  ];

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
        <DataTable
          caption={t("lists.translationsCaption")}
          columns={columns}
          data={translations}
          getRowId={(item) => item.id}
          labels={labels}
          loading={!loaded}
        />

        {/* A machine's version is translated from its original, not onward. */}
        {missing.length > 0 && !entry.translation_of && (
          <div className="space-y-2">
            {offer.state === "available" &&
              (jobId !== undefined && !jobDone ? (
                <p className="text-sm text-muted-foreground" role="status">
                  {t("entryTranslating")}
                </p>
              ) : (
                <>
                  <Button
                    type="button"
                    variant="outline"
                    onClick={() => {
                      // An order that ended is history: quote anew.
                      if (jobDone) setJobId(undefined);
                      setTranslating(true);
                    }}
                  >
                    <LanguagesIcon aria-hidden="true" />
                    {t("languageMode.actions.translate")}
                  </Button>
                  <p className="text-sm text-muted-foreground">
                    {t("entryTranslateHint", {
                      languages: missing.map((item) => item.name).join(", "),
                    })}
                  </p>
                </>
              ))}
            {offer.state === "unavailable" && (
              <TranslationUnavailable reasons={offer.reasons} />
            )}
          </div>
        )}
        {offer.state === "available" && (
          <TranslateDialog
            open={translating}
            onOpenChange={setTranslating}
            targets={missing.map((item) => ({
              source_key: "sites.entry",
              object_id: entry.id,
              locale: item.code,
              basis: "published" as const,
            }))}
            languageName={(code) =>
              companyLocaleOptions.find((item) => item.code === code)?.name ??
              nativeName(code)
            }
            reasonText={(reason) =>
              t.has(`languageMode.banner.reasons.${reason}`)
                ? t(`languageMode.banner.reasons.${reason}`)
                : t("languageMode.banner.reasons.other")
            }
            allowWorking
            offer={offer.offer}
            job={job}
            onOrdered={(started) => setJobId(started.id)}
          />
        )}

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
                onChange={(event) => setLocale(event.target.value)}
                value={chosen}
              >
                {missing.map((candidate) => (
                  <option key={candidate.code} value={candidate.code}>
                    {candidate.name}
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
