"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { SearchIcon } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { getSettingsSchema, type SettingsSchema } from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@saas-core/ui/components/dialog";
import { Input } from "@saas-core/ui/components/input";

import { Link } from "#i18n/navigation";

type Localized = { pl: string; en: string };

/** One place a person may look for: an area, a group, or a single setting. */
export type SettingsSearchEntry = {
  href: string;
  title: string;
  /** Where it is, e.g. „Rezerwacje › Przypomnienia o wizycie”. */
  path: string;
  words: string;
};

const MAX_RESULTS = 20;

function text(labels: Localized | null | undefined, locale: string): string {
  if (!labels) return "";
  return locale === "en" ? labels.en : labels.pl;
}

/** Case and Polish letters aside: „wazne” finds „Ważne”. */
function folded(value: string): string {
  return value
    .toLocaleLowerCase("pl")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/ł/g, "l");
}

/**
 * Everything „Ustawienia” holds, from the schema (ADR-078 R4, answer 33a):
 * each area, each group and each setting, leading to the page that shows it
 * and — for a setting the generic form draws — to the field itself.
 */
export function settingsIndex(
  schema: SettingsSchema,
  locale: string,
): SettingsSearchEntry[] {
  const areas = new Map(schema.areas.map((area) => [area.key, area]));
  const entries: SettingsSearchEntry[] = [];
  for (const area of schema.areas) {
    const title = text(area.title, locale);
    entries.push({
      href: area.page ?? `/panel/settings/${area.key}`,
      title,
      path: "",
      words: folded(`${title} ${text(area.description, locale)}`),
    });
  }
  for (const group of schema.groups) {
    const area = areas.get(group.area);
    if (!area) continue;
    const page = area.page ?? `/panel/settings/${area.key}`;
    const areaTitle = text(area.title, locale);
    const groupTitle = text(group.title, locale);
    entries.push({
      href: page,
      title: groupTitle,
      path: areaTitle,
      words: folded(
        `${groupTitle} ${text(group.description, locale)} ${areaTitle}`,
      ),
    });
    for (const option of group.keys) {
      const field = option.key.slice(option.key.lastIndexOf(".") + 1);
      const label = text(option.label, locale);
      entries.push({
        // A group its module stores itself has a form of its own: the page.
        href: group.api ? page : `${page}#setting-${group.key}-${field}`,
        title: label,
        path: `${areaTitle} › ${groupTitle}`,
        words: folded(
          `${label} ${text(option.help, locale)} ${groupTitle} ${areaTitle}`,
        ),
      });
    }
  }
  return entries;
}

/** Every word of the query, in any order, anywhere in the entry. */
export function searchSettings(
  entries: SettingsSearchEntry[],
  query: string,
): SettingsSearchEntry[] {
  const words = folded(query).split(/\s+/).filter(Boolean);
  if (words.length === 0) return [];
  return entries
    .filter((entry) => words.every((word) => entry.words.includes(word)))
    .slice(0, MAX_RESULTS);
}

/**
 * „Szukaj w ustawieniach” beside a settings page's title: one field that finds
 * a setting wherever it stands (answer 33a), read from the same schema the
 * forms are drawn from — so a module's new setting is found without code here.
 */
export function SettingsSearch() {
  const t = useTranslations("CompanySettings");
  const locale = useLocale();
  const inputId = useId();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [schema, setSchema] = useState<SettingsSchema>();
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!open || schema) return;
    let mounted = true;
    void getSettingsSchema()
      .then((value) => mounted && setSchema(value))
      .catch(() => mounted && setFailed(true));
    return () => {
      mounted = false;
    };
  }, [open, schema]);

  const entries = useMemo(
    () => (schema ? settingsIndex(schema, locale) : []),
    [schema, locale],
  );
  const found = searchSettings(entries, query);

  return (
    <>
      <Button onClick={() => setOpen(true)} type="button" variant="outline">
        <SearchIcon aria-hidden="true" />
        {t("searchOpen")}
      </Button>
      <Dialog onOpenChange={setOpen} open={open}>
        <DialogContent closeLabel={t("cancel")}>
          <DialogHeader>
            <DialogTitle>{t("searchTitle")}</DialogTitle>
            <DialogDescription>{t("searchHint")}</DialogDescription>
          </DialogHeader>
          <label className="sr-only" htmlFor={inputId}>
            {t("searchLabel")}
          </label>
          <Input
            autoFocus
            id={inputId}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("searchPlaceholder")}
            type="search"
            value={query}
          />
          <div aria-live="polite" className="min-h-6 text-sm">
            {failed ? (
              <p className="text-destructive">{t("loadError")}</p>
            ) : !schema ? (
              <p className="text-muted-foreground">{t("searchLoading")}</p>
            ) : query.trim() && found.length === 0 ? (
              <p className="text-muted-foreground">
                {t("searchEmpty", { query: query.trim() })}
              </p>
            ) : (
              <ul className="max-h-80 space-y-1 overflow-y-auto">
                {found.map((entry) => (
                  <li key={`${entry.href} ${entry.title}`}>
                    <Link
                      className="block rounded-md px-3 py-2 hover:bg-foreground/6 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
                      href={entry.href}
                      onClick={() => setOpen(false)}
                    >
                      <span className="block font-medium">{entry.title}</span>
                      {entry.path ? (
                        <span className="block text-xs text-muted-foreground">
                          {entry.path}
                        </span>
                      ) : null}
                    </Link>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
