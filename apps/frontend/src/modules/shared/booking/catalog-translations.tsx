"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { getPublicLocales } from "@saas-core/api-client";

import { TranslateMissing } from "../translation/translate-missing";

/** The booking catalogue is one translation object per company (TL12c). */
const SOURCE_KEY = "booking.catalog";

/**
 * The whole booking catalogue in the company's other languages (TL12e): where
 * each item's „Tłumaczenia” are, and „Przetłumacz brakujące” for all of them
 * at once. Nothing for a company with one language.
 */
export function CatalogTranslations({
  organizationId,
}: {
  organizationId: string;
}) {
  const t = useTranslations("Translations");
  const [others, setOthers] = useState<string[]>([]);

  useEffect(() => {
    let alive = true;
    getPublicLocales()
      // The first language is the one the items are written in.
      .then((answer) => {
        if (alive) setOthers(answer.public_locales.slice(1));
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
  }, []);

  if (others.length === 0) return null;
  return (
    <div className="max-w-3xl space-y-3">
      <p className="text-sm text-muted-foreground">{t("catalogHint")}</p>
      <TranslateMissing
        targets={others.map((locale) => ({
          source_key: SOURCE_KEY,
          object_id: organizationId,
          locale,
          basis: "published",
        }))}
      />
    </div>
  );
}
