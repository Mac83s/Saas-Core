import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getFormatter, getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { getServerPublicCustomerDocument } from "#lib/server-auth";

// A company's terms or policy: a page a customer opens from a form or a
// mail, not one to find in a search engine.
export const metadata: Metadata = { robots: { index: false, follow: false } };

/** A language named in itself ("Deutsch"). */
function nativeName(code: string): string {
  try {
    const name = new Intl.DisplayNames([code], { type: "language" }).of(code);
    if (name) return name.charAt(0).toLocaleUpperCase(code) + name.slice(1);
  } catch {
    // An unknown code names itself.
  }
  return code.toUpperCase();
}

export default async function CustomerDocumentPage({
  params,
}: {
  params: Promise<{ locale: string; publicId: string }>;
}) {
  const { locale, publicId } = await params;
  const document = await getServerPublicCustomerDocument(publicId, locale);
  if (!document) notFound();
  const [t, format] = await Promise.all([
    getTranslations("CustomerDocument"),
    getFormatter(),
  ]);
  return (
    <main className="mx-auto min-h-screen max-w-2xl px-5 py-12">
      <article className="space-y-6">
        <header className="space-y-2">
          <p className="text-sm text-muted-foreground">
            {document.organization_name}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">
            {t(`kinds.${document.kind}`)}
          </h1>
          <p className="text-sm text-muted-foreground">
            {t("version", {
              number: document.version,
              date: format.dateTime(
                new Date(`${document.effective_from}T12:00:00`),
                { dateStyle: "long" },
              ),
            })}
          </p>
        </header>
        {document.locale !== locale ? (
          <p className="rounded-md border px-3 py-2 text-sm" role="note">
            {t("otherLanguage", { language: nativeName(document.locale) })}
          </p>
        ) : null}
        <div className="space-y-4" lang={document.locale}>
          {document.text.split(/\n{2,}/).map((paragraph, index) => (
            <p className="wrap-anywhere whitespace-pre-line" key={index}>
              {paragraph}
            </p>
          ))}
        </div>
        {document.locales.length > 1 ? (
          <nav aria-label={t("readIn")} className="border-t pt-4 text-sm">
            <span className="text-muted-foreground">{t("readIn")}: </span>
            {document.locales.map((code) => (
              <Link
                className="mr-3 underline"
                href={`/documents/${publicId}`}
                key={code}
                locale={code}
              >
                {nativeName(code)}
              </Link>
            ))}
          </nav>
        ) : null}
      </article>
    </main>
  );
}
