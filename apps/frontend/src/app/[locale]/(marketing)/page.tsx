import type { Metadata } from "next";
import Image from "next/image";
import { CheckIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { Link } from "#i18n/navigation";
import { productCopy, productName } from "../../../marketing/content";
import { localizedUrl, marketingMetadata } from "../../../marketing/seo";
import { Badge } from "@saas-core/ui/components/badge";
import { Button } from "@saas-core/ui/components/button";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
} from "@saas-core/ui/components/card";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const { seo } = productCopy(locale);
  return marketingMetadata({ locale, path: "/", ...seo });
}

export default async function HomePage({ params }: Props) {
  const { locale } = await params;
  const copy = productCopy(locale);
  const t = await getTranslations("Marketing");

  const structuredData = [
    {
      "@context": "https://schema.org",
      "@type": "SoftwareApplication",
      name: productName,
      description: copy.seo.description,
      applicationCategory: "BusinessApplication",
      operatingSystem: "Web",
      url: localizedUrl(locale, "/"),
      inLanguage: locale,
    },
    {
      "@context": "https://schema.org",
      "@type": "FAQPage",
      mainEntity: copy.faq.map((item) => ({
        "@type": "Question",
        name: item.question,
        acceptedAnswer: { "@type": "Answer", text: item.answer },
      })),
    },
  ];

  return (
    <>
      <script
        type="application/ld+json"
        // Our own static copy, serialized — not user input.
        dangerouslySetInnerHTML={{
          __html: JSON.stringify(structuredData).replace(/</g, "\\u003c"),
        }}
      />

      <section className="relative overflow-hidden border-b bg-gradient-to-br from-primary/10 via-background to-background">
        {copy.hero.backgroundImage ? (
          <>
            <div
              aria-hidden="true"
              className="absolute inset-0 bg-cover bg-center"
              style={{ backgroundImage: `url(${copy.hero.backgroundImage})` }}
            />
            <div
              aria-hidden="true"
              className="absolute inset-0 bg-gradient-to-r from-background via-background/90 to-background/55"
            />
          </>
        ) : null}
        <div className="relative mx-auto grid w-full max-w-6xl items-center gap-12 px-5 py-16 sm:py-24 lg:grid-cols-[1.15fr_0.85fr] lg:py-28">
          <div className="flex flex-col items-start gap-6">
            <Badge variant="secondary">{copy.hero.eyebrow}</Badge>
            <h1 className="max-w-3xl text-4xl font-semibold tracking-tight text-balance sm:text-6xl">
              {copy.hero.headline}
            </h1>
            <p className="max-w-2xl text-lg leading-relaxed text-muted-foreground">
              {copy.hero.lead}
            </p>
            <div className="flex flex-wrap gap-3">
              <Button render={<Link href="/register" />} size="lg">
                {t("home.start")}
              </Button>
              <Button
                render={<Link href="/pricing" />}
                size="lg"
                variant="outline"
              >
                {t("home.seePricing")}
              </Button>
            </div>
            <ul className="flex flex-wrap gap-x-6 gap-y-2 pt-2 text-sm text-muted-foreground">
              {copy.hero.highlights.map((item) => (
                <li key={item} className="flex items-center gap-2">
                  <CheckIcon
                    aria-hidden="true"
                    className="size-4 text-primary"
                  />
                  {item}
                </li>
              ))}
            </ul>
          </div>
          <div className="rounded-3xl border bg-background/90 p-6 shadow-xl shadow-primary/10 sm:p-8">
            <p className="mb-6 text-sm font-medium text-primary">
              {copy.features.title}
            </p>
            <ol className="space-y-5">
              {copy.features.items.slice(0, 3).map((item, index) => (
                <li
                  key={item.title}
                  className="flex gap-4 border-t pt-5 first:border-0 first:pt-0"
                >
                  <span className="text-sm font-semibold text-primary">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <div className="space-y-1">
                    <p className="font-semibold">{item.title}</p>
                    <p className="text-sm leading-relaxed text-muted-foreground">
                      {item.body}
                    </p>
                  </div>
                </li>
              ))}
            </ol>
          </div>
        </div>
      </section>

      <section id="features" className="scroll-mt-20 border-t bg-muted/30">
        <div className="mx-auto flex w-full max-w-6xl flex-col gap-10 px-5 py-20">
          <div className="flex max-w-2xl flex-col gap-3">
            <h2 className="text-3xl font-semibold tracking-tight">
              {copy.features.title}
            </h2>
            <p className="text-muted-foreground">{copy.features.lead}</p>
          </div>
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {copy.features.items.map((item) => (
              <li key={item.title}>
                <Card className="h-full">
                  {item.image ? (
                    <Image
                      src={item.image}
                      alt=""
                      className="aspect-video w-full object-cover"
                      unoptimized
                    />
                  ) : null}
                  <CardHeader>
                    <CardTitle>
                      <h3>
                        {item.href ? (
                          <Link href={item.href}>{item.title}</Link>
                        ) : (
                          item.title
                        )}
                      </h3>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="space-y-4 text-sm text-muted-foreground">
                    <p>{item.body}</p>
                    {item.href && item.linkLabel ? (
                      <Link
                        href={item.href}
                        className="font-medium text-primary hover:underline"
                      >
                        {item.linkLabel} →
                      </Link>
                    ) : null}
                  </CardContent>
                </Card>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="mx-auto grid w-full max-w-6xl gap-10 px-5 py-20 md:grid-cols-2">
        {copy.audiences.map((audience) => (
          <div key={audience.title} className="flex flex-col gap-3">
            <p className="text-sm font-medium text-primary">{audience.title}</p>
            <h2 className="text-2xl font-semibold tracking-tight">
              {audience.headline}
            </h2>
            <p className="text-muted-foreground">{audience.body}</p>
            <ul className="flex flex-col gap-2 pt-1 text-sm">
              {audience.points.map((point) => (
                <li key={point} className="flex items-center gap-2">
                  <CheckIcon
                    aria-hidden="true"
                    className="size-4 text-primary"
                  />
                  {point}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </section>

      <section className="border-t bg-muted/30">
        <div className="mx-auto flex w-full max-w-3xl flex-col gap-6 px-5 py-20">
          <h2 className="text-3xl font-semibold tracking-tight">
            {t("home.faq")}
          </h2>
          <div className="flex flex-col divide-y rounded-lg border bg-background">
            {copy.faq.map((item) => (
              <details key={item.question} className="group px-5 py-4">
                <summary className="cursor-pointer font-medium">
                  {item.question}
                </summary>
                <p className="pt-3 text-sm text-muted-foreground">
                  {item.answer}
                </p>
              </details>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto flex w-full max-w-6xl flex-col items-start gap-4 px-5 py-20">
        <h2 className="text-3xl font-semibold tracking-tight">
          {t("home.ctaTitle", { product: productName })}
        </h2>
        <p className="max-w-2xl text-muted-foreground">{t("home.ctaLead")}</p>
        <div className="flex flex-wrap gap-3">
          <Button render={<Link href="/register" />} size="lg">
            {t("home.start")}
          </Button>
          <Button render={<Link href="/contact" />} size="lg" variant="outline">
            {t("nav.contact")}
          </Button>
        </div>
      </section>
    </>
  );
}
