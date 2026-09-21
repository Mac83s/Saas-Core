"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLinkIcon, SearchIcon } from "lucide-react";

import {
  readCatalogDictionary,
  searchCatalog,
  type CatalogDictionary,
  type CatalogPage,
} from "@saas-core/api-client";
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

import { profileProblem } from "./problem";

/**
 * The public listing. Filters are dictionary values only — the API refuses
 * anything else (ADR-053 §7), so the form offers exactly what it accepts.
 */
export function CatalogSearch({
  initialCity = "",
  locale,
}: {
  initialCity?: string;
  locale: string;
}) {
  const t = useTranslations("Catalog");
  const [dictionary, setDictionary] = useState<CatalogDictionary | null>(null);
  const [city, setCity] = useState(initialCity);
  const [category, setCategory] = useState("");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState<CatalogPage | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const loaded = await readCatalogDictionary();
        if (!cancelled) setDictionary(loaded);
      } catch (caught) {
        if (!cancelled) setError(profileProblem(caught, t("loadFailed")));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const found = await searchCatalog({ city, category, q: query });
        if (!cancelled) {
          setPage(found);
          setError(null);
        }
      } catch (caught) {
        if (!cancelled) setError(profileProblem(caught, t("loadFailed")));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [city, category, query, t]);

  return (
    <div className="space-y-8">
      <form
        className="grid gap-4 sm:grid-cols-3"
        onSubmit={(event) => event.preventDefault()}
        role="search"
      >
        <Field>
          <FieldLabel htmlFor="catalog-q">{t("query")}</FieldLabel>
          <Input
            id="catalog-q"
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("queryPlaceholder")}
            type="search"
            value={query}
          />
        </Field>
        <Field>
          <FieldLabel htmlFor="catalog-city">{t("city")}</FieldLabel>
          <NativeSelect
            id="catalog-city"
            onChange={(event) => setCity(event.target.value)}
            value={city}
          >
            <option value="">{t("anyCity")}</option>
            {(dictionary?.cities ?? []).map((entry) => (
              <option key={entry.slug} value={entry.slug}>
                {entry.name}
              </option>
            ))}
          </NativeSelect>
        </Field>
        <Field>
          <FieldLabel htmlFor="catalog-category">{t("category")}</FieldLabel>
          <NativeSelect
            id="catalog-category"
            onChange={(event) => setCategory(event.target.value)}
            value={category}
          >
            <option value="">{t("anyCategory")}</option>
            {(dictionary?.categories ?? []).map((entry) => (
              <option key={entry.key} value={entry.key}>
                {entry.labels[locale] ?? entry.labels.pl ?? entry.key}
              </option>
            ))}
          </NativeSelect>
        </Field>
      </form>

      {error && (
        <p className="text-destructive text-sm" role="alert">
          {error}
        </p>
      )}

      {page && page.total === 0 && (
        <p className="text-muted-foreground flex items-center gap-2 text-sm">
          <SearchIcon aria-hidden="true" className="size-4" />
          {t("empty")}
        </p>
      )}

      <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {(page?.items ?? []).map((item) => (
          <li key={`${item.city_slug}/${item.slug}`}>
            <Card className="h-full">
              <CardHeader>
                <CardTitle>
                  <a
                    className="hover:underline"
                    href={item.url}
                    // An entry that leaves the platform opens in a new tab and
                    // says so; one that stays does neither.
                    rel={item.is_external ? "noreferrer" : undefined}
                    target={item.is_external ? "_blank" : undefined}
                  >
                    {item.display_name}
                    {item.is_external && (
                      <ExternalLinkIcon
                        aria-hidden="true"
                        className="ml-1 inline size-3.5 align-baseline"
                      />
                    )}
                  </a>
                </CardTitle>
                <CardDescription>{item.headline}</CardDescription>
              </CardHeader>
              <CardContent className="text-muted-foreground text-sm">
                {item.city}
              </CardContent>
            </Card>
          </li>
        ))}
      </ul>

      {page && page.total > page.items.length && (
        <Button
          onClick={() => {
            void searchCatalog({
              city,
              category,
              q: query,
              page: page.page + 1,
            }).then((next) =>
              setPage({ ...next, items: [...page.items, ...next.items] }),
            );
          }}
          variant="outline"
        >
          {t("more")}
        </Button>
      )}
    </div>
  );
}
