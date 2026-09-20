import type { Metadata } from "next";
import { ArrowRightIcon, CheckIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";

import { Link } from "#i18n/navigation";
import { routing } from "#i18n/routing";
import { productCopy, productName } from "../../../../marketing/content";
import { localizedUrl, marketingMetadata } from "../../../../marketing/seo";
import { Button } from "@saas-core/ui/components/button";

type Props = { params: Promise<{ locale: string; slug: string }> };

function detailPage(locale: string, slug: string) {
  return productCopy(locale).pages?.find((page) => page.slug === slug);
}

export function generateStaticParams() {
  return routing.locales.flatMap((locale) =>
    (productCopy(locale).pages ?? []).map((page) => ({
      locale,
      slug: page.slug,
    })),
  );
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale, slug } = await params;
  const page = detailPage(locale, slug);
  if (!page) notFound();
  return marketingMetadata({
    locale,
    path: `/${slug}`,
    title: `${page.seo.title} — ${productName}`,
    description: page.seo.description,
  });
}

export default async function DetailPage({ params }: Props) {
  const { locale, slug } = await params;
  const page = detailPage(locale, slug);
  if (!page) notFound();
  const t = await getTranslations("Marketing");
  const url = localizedUrl(locale, `/${slug}`);
  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "WebPage",
      name: page.seo.title,
      description: page.seo.description,
      url,
      inLanguage: locale,
      isPartOf: {
        "@type": "WebSite",
        name: productName,
        url: localizedUrl(locale, "/"),
      },
    },
    {
      "@context": "https://schema.org",
      "@type": "BreadcrumbList",
      itemListElement: [
        {
          "@type": "ListItem",
          position: 1,
          name: productName,
          item: localizedUrl(locale, "/"),
        },
        { "@type": "ListItem", position: 2, name: page.navLabel, item: url },
      ],
    },
  ];

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(structuredData).replace(/</g, "\\u003c"),
        }}
      />
      <section className="relative overflow-hidden border-b bg-gradient-to-br from-primary/10 via-background to-background">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-6 px-5 py-16 sm:py-24">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-primary">
            {page.eyebrow}
          </p>
          <h1 className="max-w-4xl text-4xl font-semibold tracking-tight text-balance sm:text-6xl">
            {page.headline}
          </h1>
          <p className="max-w-3xl text-lg leading-relaxed text-muted-foreground sm:text-xl">
            {page.lead}
          </p>
          <div className="flex flex-wrap gap-3 pt-2">
            <Button render={<Link href="/pricing" />} size="lg">
              {t("nav.pricing")} <ArrowRightIcon aria-hidden="true" />
            </Button>
            <Button
              render={<Link href="/contact" />}
              size="lg"
              variant="outline"
            >
              {t("nav.contact")}
            </Button>
          </div>
        </div>
      </section>

      <div className="mx-auto flex w-full max-w-6xl flex-col gap-0 px-5">
        {page.sections.map((section, index) => (
          <section
            key={section.title}
            className="grid gap-6 border-b py-14 last:border-0 md:grid-cols-[12rem_1fr] md:gap-12 md:py-20"
          >
            <p className="text-sm font-semibold tracking-widest text-primary">
              {String(index + 1).padStart(2, "0")}
            </p>
            <div className="max-w-3xl space-y-5">
              <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
                {section.title}
              </h2>
              <p className="leading-relaxed text-muted-foreground">
                {section.body}
              </p>
              {section.points?.length ? (
                <ul className="grid gap-3 pt-2 sm:grid-cols-2">
                  {section.points.map((point) => (
                    <li key={point} className="flex items-start gap-3 text-sm">
                      <CheckIcon
                        aria-hidden="true"
                        className="mt-0.5 size-4 shrink-0 text-primary"
                      />
                      {point}
                    </li>
                  ))}
                </ul>
              ) : null}
            </div>
          </section>
        ))}
      </div>

      {page.faq.length ? (
        <section className="border-y bg-muted/30">
          <div className="mx-auto max-w-4xl space-y-8 px-5 py-16 sm:py-20">
            <h2 className="text-3xl font-semibold tracking-tight">
              {t("home.faq")}
            </h2>
            <div className="divide-y rounded-xl border bg-background px-6">
              {page.faq.map((item) => (
                <details key={item.question} className="group py-5">
                  <summary className="cursor-pointer font-medium">
                    {item.question}
                  </summary>
                  <p className="max-w-3xl pt-3 leading-relaxed text-muted-foreground">
                    {item.answer}
                  </p>
                </details>
              ))}
            </div>
          </div>
        </section>
      ) : null}

      <section className="mx-auto flex w-full max-w-6xl flex-col items-start gap-5 px-5 py-16 sm:py-20">
        <h2 className="max-w-3xl text-3xl font-semibold tracking-tight">
          {page.cta.title}
        </h2>
        <p className="max-w-2xl text-muted-foreground">{page.cta.body}</p>
        <Button render={<Link href="/contact" />} size="lg">
          {t("nav.contact")} <ArrowRightIcon aria-hidden="true" />
        </Button>
      </section>
    </>
  );
}
