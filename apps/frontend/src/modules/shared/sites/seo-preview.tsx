"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import {
  readSeoPreview,
  type SeoPreview as Preview,
} from "@saas-core/api-client";
import { Button } from "@saas-core/ui/components/button";

import { PanelSection } from "#components/panel/panel-page";
import { sitesErrorMessage } from "./problem";

/** About what a search result shows before it cuts the text. */
export const TITLE_SHOWN = 60;
export const DESCRIPTION_SHOWN = 160;

const REASONS = [
  "not_written",
  "withheld",
  "language_off",
  "language_not_live",
];

function cut(text: string, limit: number): string {
  return text.length > limit ? `${text.slice(0, limit).trimEnd()}…` : text;
}

function graphTypes(data: Preview["structured_data"]): string[] {
  const graph = (data as { "@graph"?: unknown } | undefined)?.["@graph"];
  if (!Array.isArray(graph)) return [];
  return graph.flatMap((node: { "@type"?: unknown }) => {
    const type = node["@type"];
    return Array.isArray(type) ? type.map(String) : type ? [String(type)] : [];
  });
}

/**
 * „Podgląd w wyszukiwarce” (TL18): one page in one language as a search
 * engine would read it after the next publication — from the saved draft,
 * publishing nothing. `version` is whatever changes when the page or its
 * metadata is saved; the preview reads again when it does.
 *
 * Everything shown is the company's own text, printed as text.
 */
export function SeoPreview({
  siteId,
  pageId,
  locale,
  version,
}: {
  siteId: string;
  pageId: string;
  locale: string;
  version?: string | number;
}) {
  const t = useTranslations("SeoPreview");
  const sites = useTranslations("Sites");
  const [preview, setPreview] = useState<Preview>();
  const [problem, setProblem] = useState<string>();

  const load = useCallback(async () => {
    setProblem(undefined);
    try {
      setPreview(await readSeoPreview(siteId, pageId, locale));
    } catch (error) {
      setPreview(undefined);
      setProblem(sitesErrorMessage(error, sites));
    }
  }, [siteId, pageId, locale, sites]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- load on change
    void load();
  }, [load, version]);

  const types = preview
    ? [...new Set(graphTypes(preview.structured_data))]
    : [];
  const languages = Object.entries(preview?.hreflang ?? {});
  const title = preview?.title ?? "";
  const description = preview?.description ?? "";

  return (
    <PanelSection description={t("description")} title={t("title")}>
      {problem ? (
        <div className="flex flex-wrap items-center gap-3" role="alert">
          <p className="text-sm text-destructive">{problem}</p>
          <Button onClick={() => void load()} variant="outline">
            {t("retry")}
          </Button>
        </div>
      ) : !preview ? (
        <p className="text-sm text-muted-foreground" role="status">
          {t("loading")}
        </p>
      ) : !preview.public ? (
        <p className="text-sm text-muted-foreground">
          {t(
            `notPublic.${REASONS.includes(preview.reason) ? preview.reason : "other"}`,
          )}
        </p>
      ) : (
        <div className="space-y-4">
          <div
            aria-label={t("result")}
            className="space-y-1 rounded-lg border bg-card p-4"
            lang={locale}
            role="group"
          >
            <p className="wrap-anywhere text-sm text-muted-foreground">
              {preview.site_name ? `${preview.site_name} · ` : ""}
              {preview.url}
            </p>
            <p className="wrap-anywhere text-lg font-medium text-primary">
              {cut(title, TITLE_SHOWN)}
            </p>
            {description ? (
              <p className="wrap-anywhere text-sm">
                {cut(description, DESCRIPTION_SHOWN)}
              </p>
            ) : null}
          </div>
          <ul className="space-y-1 text-sm text-muted-foreground">
            {preview.noindex ? <li>{t("noindex")}</li> : null}
            {title.length > TITLE_SHOWN ? (
              <li>
                {t("titleLong", { count: title.length, limit: TITLE_SHOWN })}
              </li>
            ) : null}
            {!description ? <li>{t("noDescription")}</li> : null}
            {description.length > DESCRIPTION_SHOWN ? (
              <li>
                {t("descriptionLong", {
                  count: description.length,
                  limit: DESCRIPTION_SHOWN,
                })}
              </li>
            ) : null}
          </ul>
          {languages.length > 1 ? (
            <div className="space-y-1 text-sm">
              <h3 className="font-medium">{t("languages")}</h3>
              <ul className="space-y-0.5 text-muted-foreground">
                {languages.map(([code, url]) => (
                  <li className="wrap-anywhere" key={code}>
                    <span className="uppercase">{code}</span> · {url}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
          {types.length ? (
            <div className="space-y-1 text-sm">
              <h3 className="font-medium">{t("structured")}</h3>
              <p className="text-muted-foreground">
                {t("structuredTypes", { types: types.join(", ") })}
              </p>
              <details>
                <summary className="cursor-pointer text-primary">
                  {t("structuredSource")}
                </summary>
                <pre className="mt-2 max-h-80 overflow-auto rounded-lg border bg-muted p-3 text-xs">
                  {JSON.stringify(preview.structured_data, null, 2)}
                </pre>
              </details>
            </div>
          ) : null}
        </div>
      )}
    </PanelSection>
  );
}
