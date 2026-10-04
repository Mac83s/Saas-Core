"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { TriangleAlertIcon } from "lucide-react";

import {
  listCustomerDocuments,
  type CustomerDocument,
} from "@saas-core/api-client";

import { Link } from "#i18n/navigation";
import { nativeName } from "#lib/company-locales";
import { useCompanyLanguages } from "../../core/organizations";

const TERMS = "booking_terms";

/**
 * Booking terms in force without a text in one of the company's languages
 * close online booking in that language (ADR-073 §9; the owner's decision of
 * 2026-10-04): the public form refuses it and names the languages that have
 * the terms. The panel says so where the company sets its documents and its
 * languages. Only the terms do that — never the privacy policy.
 */
export function termsLanguagesOff(
  document: Pick<CustomerDocument, "kind" | "in_force"> | undefined,
  companyLocales: string[],
): string[] {
  if (document?.kind !== TERMS || !document.in_force) return [];
  const written = document.in_force.locales;
  return companyLocales.filter((code) => !written.includes(code));
}

/** „Regulamin rezerwacji nie ma wersji w języku English — rezerwacja online
 *  w tym języku jest wyłączona.” `link` — where the text is added, for a
 *  screen that is not the document's own. */
export function TermsLanguagesWarning({
  languages,
  link = false,
}: {
  languages: string[];
  link?: boolean;
}) {
  const t = useTranslations("CustomerDocuments");
  if (!languages.length) return null;
  return (
    <p
      className="flex max-w-3xl items-start gap-2 rounded-lg border border-warning-foreground/30 bg-warning p-3 text-sm text-warning-foreground"
      data-testid="terms-languages-off"
      role="status"
    >
      <TriangleAlertIcon
        aria-hidden="true"
        className="mt-0.5 size-4 shrink-0"
      />
      <span>
        {t("termsLanguagesOff", {
          count: languages.length,
          languages: languages.map(nativeName).join(", "),
        })}{" "}
        {link ? (
          <Link
            className="underline underline-offset-2"
            href={`/panel/settings/documents/${TERMS}`}
          >
            {t("termsLanguagesAdd")}
          </Link>
        ) : (
          t("termsLanguagesAddHere")
        )}
      </span>
    </p>
  );
}

/** The warning on the screen of the company's languages: asked for again
 *  whenever a language is added or removed there. */
export function TermsLanguagesNotice() {
  const languages = useCompanyLanguages();
  const listed = languages?.join(",");
  const [off, setOff] = useState<string[]>([]);
  useEffect(() => {
    if (listed === undefined) return;
    let mounted = true;
    void listCustomerDocuments()
      .then((value) => {
        if (!mounted) return;
        setOff(
          termsLanguagesOff(
            value.documents.find((row) => row.kind === TERMS),
            value.options.locales,
          ),
        );
      })
      // No answer is no warning: the documents' own screen says it too.
      .catch(() => undefined);
    return () => {
      mounted = false;
    };
  }, [listed]);
  return <TermsLanguagesWarning languages={off} link />;
}
