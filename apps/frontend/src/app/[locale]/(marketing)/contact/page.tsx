import type { Metadata } from "next";
import { MailIcon, MapPinIcon, PhoneIcon } from "lucide-react";
import { getTranslations } from "next-intl/server";

import { productCopy, productName } from "../../../../marketing/content";
import { marketingMetadata } from "../../../../marketing/seo";

type Props = { params: Promise<{ locale: string }> };

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { locale } = await params;
  const { contact } = productCopy(locale);
  return marketingMetadata({
    locale,
    path: "/contact",
    title: `${contact.title} — ${productName}`,
    description: contact.lead,
  });
}

// ponytail: e-mail link only; a contact form needs mail delivery (Resend keys pending) and anti-spam.
export default async function ContactPage({ params }: Props) {
  const { locale } = await params;
  const { contact } = productCopy(locale);
  const t = await getTranslations("Marketing.contact");

  return (
    <section className="mx-auto flex w-full max-w-3xl flex-col gap-8 px-5 py-20">
      <div className="flex flex-col gap-3">
        <h1 className="text-4xl font-semibold tracking-tight">
          {contact.title}
        </h1>
        <p className="text-lg text-muted-foreground">{contact.lead}</p>
      </div>
      <dl className="grid gap-6 rounded-lg border p-6 sm:grid-cols-2">
        <div className="flex gap-3">
          <MailIcon aria-hidden="true" className="mt-0.5 size-5 text-primary" />
          <div>
            <dt className="text-sm text-muted-foreground">{t("email")}</dt>
            <dd>
              <a
                href={`mailto:${contact.email}`}
                className="font-medium underline-offset-4 hover:underline"
              >
                {contact.email}
              </a>
            </dd>
          </div>
        </div>
        {contact.phone ? (
          <div className="flex gap-3">
            <PhoneIcon
              aria-hidden="true"
              className="mt-0.5 size-5 text-primary"
            />
            <div>
              <dt className="text-sm text-muted-foreground">{t("phone")}</dt>
              <dd>
                <a
                  href={`tel:${contact.phone.replace(/\s/g, "")}`}
                  className="font-medium"
                >
                  {contact.phone}
                </a>
              </dd>
            </div>
          </div>
        ) : null}
        <div className="flex gap-3">
          <MapPinIcon
            aria-hidden="true"
            className="mt-0.5 size-5 text-primary"
          />
          <div>
            <dt className="text-sm text-muted-foreground">{t("area")}</dt>
            <dd className="font-medium">{contact.area}</dd>
          </div>
        </div>
      </dl>
    </section>
  );
}
